#!/usr/bin/env python3
"""Focused tests for the bounded FIREX-AQ Tier-F acquisition."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fetch_firex_aq_tier_f import (
    ACQUISITION_SEAL,
    ARCHIVE_ORIGIN,
    ARCHIVE_PAGES,
    TARGETS,
    AcquisitionError,
    FetchResult,
    _normalize_fetch_result,
    _publish_noreplace,
    _validate_payload_identity,
    acquire,
    discover_sources,
    extract_icartt_header,
)


def payload(header_lines: list[str], data_lines: list[str] | None = None) -> bytes:
    lines = [f"{len(header_lines) + 1},1001", *header_lines]
    lines.extend(data_lines or ["0,1"])
    return ("\r\n".join(lines) + "\r\n").encode("latin1")


def archive_page(targets: tuple = TARGETS) -> bytes:
    links = []
    for index, target in enumerate(targets):
        links.append(
            f'<a href="/cgi-bin/enzFile?opaque={index}">'
            f"{target.filename}</a>"
        )
    return "\n".join(links).encode("latin1")


class TierFAcquisitionTests(unittest.TestCase):
    def test_discovers_exact_targets_and_resolves_opaque_links(self) -> None:
        pages = {
            key: archive_page(
                tuple(target for target in TARGETS if target.archive_page == key)
            )
            for key in ARCHIVE_PAGES
        }
        sources = discover_sources(pages)
        self.assertEqual(
            [source.target.filename for source in sources],
            [target.filename for target in TARGETS],
        )
        self.assertTrue(
            all(source.url.startswith("https://www-air.larc.nasa.gov/cgi-bin/")
                for source in sources)
        )

    def test_duplicate_exact_link_fails_closed(self) -> None:
        target = TARGETS[0]
        pages = {key: archive_page(tuple()) for key in ARCHIVE_PAGES}
        exact = (
            f'<a href="/one">{target.filename}</a>'
            f'<a href="/two">{target.filename}</a>'
        )
        pages[target.archive_page] = exact.encode("latin1")
        with self.assertRaisesRegex(AcquisitionError, "found 2"):
            discover_sources(pages)

    def test_wrong_revision_fails_closed(self) -> None:
        pages = {
            key: archive_page(
                tuple(target for target in TARGETS if target.archive_page == key)
            )
            for key in ARCHIVE_PAGES
        }
        expected = TARGETS[1].filename
        pages[TARGETS[1].archive_page] = pages[
            TARGETS[1].archive_page
        ].replace(expected.encode(), expected.replace("_R2.", "_R1.").encode())
        with self.assertRaisesRegex(AcquisitionError, "found 0"):
            discover_sources(pages)

    def test_external_download_origin_fails_closed(self) -> None:
        pages = {
            key: archive_page(
                tuple(target for target in TARGETS if target.archive_page == key)
            )
            for key in ARCHIVE_PAGES
        }
        target = TARGETS[0]
        pages[target.archive_page] = pages[target.archive_page].replace(
            b"/cgi-bin/enzFile?opaque=0",
            b"https://example.invalid/payload",
        )
        with self.assertRaisesRegex(AcquisitionError, "unexpected archive origin"):
            discover_sources(pages)

    def test_non_200_response_fails_closed(self) -> None:
        result = FetchResult(
            payload=b"partial",
            final_url=f"{ARCHIVE_ORIGIN}/cgi-bin/enzFile?opaque=1",
            http_status=206,
        )
        with self.assertRaisesRegex(AcquisitionError, "HTTP status 206"):
            _normalize_fetch_result(result, result.final_url)

    def test_content_disposition_must_name_the_exact_payload(self) -> None:
        target = TARGETS[0]
        wrong = FetchResult(
            payload=b"bytes",
            final_url=f"{ARCHIVE_ORIGIN}/cgi-bin/enzFile?opaque=1",
            http_status=200,
            content_disposition='attachment; filename="wrong.ict"',
        )
        with self.assertRaisesRegex(AcquisitionError, "served filename"):
            _validate_payload_identity(wrong, target.filename)

        exact = FetchResult(
            payload=b"bytes",
            final_url=wrong.final_url,
            http_status=200,
            content_disposition=(
                f'attachment; filename="{target.filename}"'
            ),
        )
        self.assertEqual(
            _validate_payload_identity(exact, target.filename),
            target.filename,
        )

    def test_icartt_header_count_and_exact_bytes_are_preserved(self) -> None:
        raw = payload(["PI", "Time_Start,seconds"], ["0,1", "1,2"])
        header, count, records = extract_icartt_header(raw)
        self.assertEqual(count, 3)
        self.assertEqual(records, 2)
        self.assertEqual(header, b"3,1001\r\nPI\r\nTime_Start,seconds\r\n")

    def test_malformed_icartt_header_fails_closed(self) -> None:
        with self.assertRaisesRegex(AcquisitionError, "header-line count"):
            extract_icartt_header(b"not-a-count,1001\nmetadata\n")
        with self.assertRaisesRegex(AcquisitionError, "declares 9"):
            extract_icartt_header(b"9,1001\nmetadata\n")

    def test_acquisition_is_sealed_last_and_refuses_overwrite(self) -> None:
        pages = {
            key: archive_page(
                tuple(target for target in TARGETS if target.archive_page == key)
            )
            for key in ARCHIVE_PAGES
        }
        source_map = discover_sources(pages)
        payloads = {
            source.url: payload(
                [
                    f"PI for {source.target.family}",
                    "Time_Start, seconds from midnight UTC",
                    "Missing values: -9999; QC Flag; uncertainty",
                ]
            )
            for source in source_map
        }
        responses = {
            **{ARCHIVE_PAGES[key]: value for key, value in pages.items()},
            **payloads,
        }

        def fake_fetch(url: str) -> bytes:
            return responses[url]

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"authorized: true\n")
            contract_hash = hashlib.sha256(contract.read_bytes()).hexdigest()
            destination = parent / "tier-f"
            manifest = acquire(
                destination,
                contract_path=contract,
                expected_contract_sha256=contract_hash,
                fetcher=fake_fetch,
                clock=lambda: "2026-07-27T12:00:00+00:00",
            )

            self.assertTrue(destination.is_dir())
            self.assertEqual(manifest["acquisition_gate"]["byte_and_header_seal"], "PASS")
            self.assertEqual(
                manifest["acquisition_gate"]["semantic_authority_review"],
                "PENDING",
            )
            self.assertEqual(len(manifest["payloads"]), 5)
            self.assertEqual(
                json.loads(
                    (destination / "tier_f_acquisition_manifest.json").read_text()
                ),
                manifest,
            )
            self.assertEqual(
                (destination / "acquisition_contract.yml").read_bytes(),
                contract.read_bytes(),
            )
            seal = json.loads((destination / ACQUISITION_SEAL).read_text())
            self.assertEqual(seal["status"], "SEALED")
            self.assertEqual(
                seal["manifest_sha256"],
                hashlib.sha256(
                    (
                        destination / "tier_f_acquisition_manifest.json"
                    ).read_bytes()
                ).hexdigest(),
            )
            for record in manifest["payloads"]:
                raw_path = destination / record["raw_relative_path"]
                header_path = destination / record["header_relative_path"]
                self.assertEqual(
                    hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    record["sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(header_path.read_bytes()).hexdigest(),
                    record["header_sha256"],
                )
                self.assertEqual(record["data_record_count"], 1)

            with self.assertRaises(FileExistsError):
                acquire(
                    destination,
                    contract_path=contract,
                    expected_contract_sha256=contract_hash,
                    fetcher=fake_fetch,
                )

    def test_contract_hash_mismatch_leaves_no_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"authorized: true\n")
            destination = parent / "tier-f"
            with self.assertRaisesRegex(AcquisitionError, "contract SHA-256"):
                acquire(
                    destination,
                    contract_path=contract,
                    expected_contract_sha256="0" * 64,
                    fetcher=lambda _: b"",
                )
            self.assertFalse(destination.exists())

    def test_atomic_publish_cannot_replace_an_empty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            staging = parent / ".staging"
            destination = parent / "tier-f"
            staging.mkdir()
            (staging / "sealed").write_bytes(b"candidate")
            destination.mkdir()

            with self.assertRaises(FileExistsError):
                _publish_noreplace(staging, destination, b'{"status":"SEALED"}\n')

            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual((staging / "sealed").read_bytes(), b"candidate")

    def test_failed_seal_publication_removes_owned_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            staging = parent / ".staging"
            destination = parent / "tier-f"
            staging.mkdir()
            (staging / "sealed").write_bytes(b"candidate")

            with patch(
                "fetch_firex_aq_tier_f.os.link",
                side_effect=OSError("simulated seal failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated seal"):
                    _publish_noreplace(
                        staging,
                        destination,
                        b'{"status":"SEALED"}\n',
                    )

            self.assertFalse(destination.exists())
            self.assertFalse(staging.exists())

    def test_link_commit_survives_interrupt_before_python_state_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            staging = parent / ".staging"
            destination = parent / "tier-f"
            seal_payload = b'{"status":"SEALED"}\n'
            staging.mkdir()
            (staging / "sealed").write_bytes(b"candidate")
            real_link = os.link

            def link_then_interrupt(source: Path, target: Path) -> None:
                real_link(source, target)
                raise KeyboardInterrupt("simulated post-commit interrupt")

            with patch(
                "fetch_firex_aq_tier_f.os.link",
                side_effect=link_then_interrupt,
            ):
                _publish_noreplace(staging, destination, seal_payload)

            self.assertFalse(staging.exists())
            self.assertEqual(
                (destination / ACQUISITION_SEAL).read_bytes(),
                seal_payload,
            )
            self.assertEqual(
                (destination / "sealed").read_bytes(),
                b"candidate",
            )

    def test_download_failure_leaves_no_partial_destination(self) -> None:
        pages = {
            key: archive_page(
                tuple(target for target in TARGETS if target.archive_page == key)
            )
            for key in ARCHIVE_PAGES
        }

        def failing_fetch(url: str) -> bytes:
            if url in ARCHIVE_PAGES.values():
                key = next(key for key, page_url in ARCHIVE_PAGES.items()
                           if page_url == url)
                return pages[key]
            raise OSError("simulated download failure")

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"authorized: true\n")
            destination = parent / "tier-f"
            with self.assertRaisesRegex(OSError, "simulated"):
                acquire(
                    destination,
                    contract_path=contract,
                    expected_contract_sha256=hashlib.sha256(
                        contract.read_bytes()
                    ).hexdigest(),
                    fetcher=failing_fetch,
                )
            self.assertFalse(destination.exists())
            self.assertEqual(
                [path for path in parent.iterdir() if path.name.startswith(".tier-f.")],
                [],
            )


if __name__ == "__main__":
    unittest.main()
