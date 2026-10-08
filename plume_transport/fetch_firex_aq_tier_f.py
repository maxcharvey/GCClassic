#!/usr/bin/env python3
"""Acquire and byte-seal the five frozen FIREX-AQ Tier-F payloads.

The NASA archive exposes opaque, short-lived download links. This tool fetches
the authoritative archive pages, discovers exactly one link for each frozen
August 6 filename, downloads only those five files, preserves each complete
ICARTT header, reserves a fresh output root without replacement, and publishes
an atomic completion seal only after every complete staged file is in place.
It never overwrites an existing acquisition.

Header evidence is inventoried without assigning undocumented meanings. A
separate semantic-authority review is therefore required before transformation
or joining.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import secrets
import stat
import sys
import tempfile
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit
import urllib.request


ARCHIVE_ORIGIN = "https://www-air.larc.nasa.gov"
ARCHIVE_PAGES = {
    "dc8": f"{ARCHIVE_ORIGIN}/cgi-bin/ArcView/firexaq?DC8=1",
    "merge": f"{ARCHIVE_ORIGIN}/cgi-bin/ArcView/firexaq?MERGE=1",
}
ARCHIVE_SNAPSHOT_NAMES = {
    "dc8": "dc8.html",
    "merge": "merge.html",
}
ACQUISITION_SEAL = "ACQUISITION_SEAL.json"


class AcquisitionError(RuntimeError):
    """Raised when the bounded acquisition contract cannot be proven."""


@dataclass(frozen=True)
class Target:
    family: str
    revision: str
    filename: str
    archive_page: str


@dataclass(frozen=True)
class Source:
    target: Target
    href: str
    url: str


@dataclass(frozen=True)
class FetchResult:
    payload: bytes
    final_url: str
    http_status: int | None
    content_disposition: str | None = None


TARGETS = (
    Target(
        family="final_mrg01_carrier",
        revision="R3",
        filename="FIREXAQ-mrg01-DC8_merge_20190806_R3.ict",
        archive_page="merge",
    ),
    Target(
        family="direct_AOP_optical",
        revision="R2",
        filename="firexaq-AOP-optical_DC8_20190806_R2.ict",
        archive_page="dc8",
    ),
    Target(
        family="direct_FSU_smoke_age",
        revision="R1",
        filename="firexaq-FSU-smokeage_dc8_20190806_R1.ict",
        archive_page="dc8",
    ),
    Target(
        family="direct_SP2_BC_1HZ",
        revision="R4",
        filename="FIREXAQ-SP2-BC-1HZ_DC8_20190806_R4.ict",
        archive_page="dc8",
    ),
    Target(
        family="direct_AMS",
        revision="R3",
        filename="FIREXAQ-AMS_DC8_20190806_R3.ict",
        archive_page="dc8",
    ),
)


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href is not None:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.anchors.append((self._href, "".join(self._text).strip()))
        self._href = None
        self._text = []


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_resource(url: str) -> FetchResult:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "gc-plume-transport-tier-f-acquisition/1",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return FetchResult(
            payload=response.read(),
            final_url=response.geturl(),
            http_status=response.getcode(),
            content_disposition=response.headers.get("Content-Disposition"),
        )


def _normalize_fetch_result(
    result: bytes | FetchResult,
    requested_url: str,
) -> FetchResult:
    if isinstance(result, bytes):
        normalized = FetchResult(
            payload=result,
            final_url=requested_url,
            http_status=None,
            content_disposition=None,
        )
    elif isinstance(result, FetchResult):
        normalized = result
    else:
        raise TypeError(
            "fetcher must return bytes or FetchResult, got "
            f"{type(result).__name__}"
        )
    parsed = urlsplit(normalized.final_url)
    if parsed.scheme != "https" or parsed.netloc != "www-air.larc.nasa.gov":
        raise AcquisitionError(
            "unexpected final download origin: "
            f"{normalized.final_url!r} for {requested_url!r}"
        )
    if normalized.http_status is not None and normalized.http_status != 200:
        raise AcquisitionError(
            f"unexpected HTTP status {normalized.http_status} for "
            f"{requested_url!r}"
        )
    return normalized


def _validate_payload_identity(
    response: FetchResult,
    expected_filename: str,
) -> str | None:
    """Validate the server-declared filename for a real HTTP response."""
    if response.http_status is None and response.content_disposition is None:
        return None
    if response.content_disposition is None:
        raise AcquisitionError(
            f"missing Content-Disposition for {expected_filename}"
        )
    message = Message()
    message["Content-Disposition"] = response.content_disposition
    served_filename = message.get_filename()
    if served_filename != expected_filename:
        raise AcquisitionError(
            f"served filename mismatch: expected {expected_filename!r}, "
            f"got {served_filename!r}"
        )
    return served_filename


def _parse_anchors(page: bytes) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    try:
        parser.feed(page.decode("latin1"))
        parser.close()
    except Exception as error:
        raise AcquisitionError(f"could not parse archive page: {error}") from error
    return parser.anchors


def _validated_archive_url(page_url: str, href: str) -> str:
    url = urljoin(page_url, href)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www-air.larc.nasa.gov":
        raise AcquisitionError(
            f"unexpected archive origin for discovered link {href!r}: {url!r}"
        )
    return url


def discover_sources(pages: Mapping[str, bytes]) -> list[Source]:
    """Resolve exactly one current NASA link for each frozen filename."""
    expected_page_keys = set(ARCHIVE_PAGES)
    if set(pages) != expected_page_keys:
        raise AcquisitionError(
            "archive page set mismatch: expected "
            f"{sorted(expected_page_keys)}, got {sorted(pages)}"
        )

    anchors = {key: _parse_anchors(pages[key]) for key in ARCHIVE_PAGES}
    sources: list[Source] = []
    for target in TARGETS:
        candidates = [
            (href, text)
            for href, text in anchors[target.archive_page]
            if text == target.filename
        ]
        if len(candidates) != 1:
            raise AcquisitionError(
                f"{target.filename}: expected exactly one exact archive link, "
                f"found {len(candidates)}"
            )
        href, _ = candidates[0]
        sources.append(
            Source(
                target=target,
                href=href,
                url=_validated_archive_url(
                    ARCHIVE_PAGES[target.archive_page],
                    href,
                ),
            )
        )
    return sources


def extract_icartt_header(payload: bytes) -> tuple[bytes, int, int]:
    """Return exact header bytes, declared header lines, and data record count."""
    lines = payload.splitlines(keepends=True)
    if not lines:
        raise AcquisitionError("empty payload has no ICARTT header")
    try:
        first_field = lines[0].decode("latin1").strip().split(",", 1)[0]
        header_line_count = int(first_field)
    except (UnicodeError, ValueError) as error:
        raise AcquisitionError(
            "invalid ICARTT header-line count in first record"
        ) from error
    if header_line_count < 1:
        raise AcquisitionError(
            f"ICARTT header-line count must be positive, got {header_line_count}"
        )
    if header_line_count > len(lines):
        raise AcquisitionError(
            f"ICARTT header declares {header_line_count} lines but payload has "
            f"only {len(lines)}"
        )
    header = b"".join(lines[:header_line_count])
    data_record_count = sum(
        1 for line in lines[header_line_count:] if line.strip()
    )
    return header, header_line_count, data_record_count


_EVIDENCE_PATTERNS = {
    "time_basis_and_bounds": (
        "time_start",
        "time_stop",
        "time_mid",
        "seconds from midnight",
        " utc",
        "start time",
        "stop time",
        "midpoint",
    ),
    "sentinel_and_censor_states": (
        "-999",
        "-777",
        "-888",
        "missing",
        "censor",
        "detection limit",
        "lower limit",
        "upper limit",
        "llod",
        "ulod",
    ),
    "qc_fields": (
        "flag",
        "quality",
        "valid",
        "filter",
        "bypass",
        "dilution",
        "cloud",
    ),
    "uncertainty_semantics": (
        "uncert",
        "precision",
        "standard deviation",
        "confidence",
        "detection limit",
        "method",
        "error",
    ),
    "standard_state": (
        "273",
        "1013",
        "stp",
        "standard temperature",
        "standard pressure",
        "dry",
    ),
}


def inventory_header_evidence(header: bytes) -> dict[str, list[dict[str, object]]]:
    """Inventory relevant exact header lines without interpreting them."""
    lines = header.decode("latin1").splitlines()
    inventory: dict[str, list[dict[str, object]]] = {}
    for category, patterns in _EVIDENCE_PATTERNS.items():
        matches = []
        for line_number, line in enumerate(lines, start=1):
            lowered = line.lower()
            if any(pattern in lowered for pattern in patterns):
                matches.append({"line_number": line_number, "text": line})
        inventory[category] = matches
    return inventory


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_noreplace(
    staging: Path,
    destination: Path,
    seal_payload: bytes,
) -> None:
    """Reserve a fresh root and publish an atomic completion seal last.

    Lustre does not necessarily implement ``renameat2(RENAME_NOREPLACE)`` for
    directories. An exclusive ``mkdir`` therefore reserves the exact target
    without replacing anything. Complete staged entries are moved into that
    owned root, and a hard-linked seal file becomes the atomic validity signal.
    A root without that seal is never a valid acquisition.
    """
    nonce = secrets.token_hex(16)
    owner_path = destination / ".acquisition_owner"
    seal_path = destination / ACQUISITION_SEAL
    temporary_seal_path = destination / f".{ACQUISITION_SEAL}.{nonce}.partial"
    destination_created = False

    def seal_is_committed() -> bool:
        try:
            metadata = seal_path.lstat()
            return (
                stat.S_ISREG(metadata.st_mode)
                and seal_path.read_bytes() == seal_payload
            )
        except OSError:
            return False

    def cleanup_commit_metadata() -> None:
        for path in (temporary_seal_path, owner_path):
            try:
                path.unlink()
            except OSError:
                pass

    try:
        destination.mkdir()
        destination_created = True
        _write_new(owner_path, (nonce + "\n").encode("ascii"))

        entries = sorted(
            staging.iterdir(),
            key=lambda path: (
                path.name == "tier_f_acquisition_manifest.json",
                path.name,
            ),
        )
        for entry in entries:
            target = destination / entry.name
            if target.exists():
                raise FileExistsError(f"publication target appeared: {target}")
            entry.rename(target)
        staging.rmdir()
        _fsync_directory(destination)

        _write_new(temporary_seal_path, seal_payload)
        os.link(temporary_seal_path, seal_path)

        # The hard link above is the commit point. Cleanup after it is
        # best-effort and cannot invalidate the sealed acquisition.
        cleanup_commit_metadata()
        try:
            _fsync_directory(destination)
            _fsync_directory(destination.parent)
        except OSError:
            pass
    except BaseException:
        if seal_is_committed():
            cleanup_commit_metadata()
            return
        if destination_created:
            try:
                owned = owner_path.read_text(encoding="ascii").strip() == nonce
            except OSError:
                owned = False
            if owned:
                shutil.rmtree(destination)
        raise


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def acquire(
    destination: Path,
    *,
    contract_path: Path,
    expected_contract_sha256: str,
    fetcher: Callable[[str], bytes | FetchResult] = fetch_resource,
    clock: Callable[[], str] = _utc_now,
) -> dict[str, object]:
    """Acquire into a fresh directory and publish it atomically."""
    destination = destination.resolve()
    contract_path = contract_path.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite acquisition {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(
            f"acquisition parent must already exist: {destination.parent}"
        )
    if not contract_path.is_file():
        raise FileNotFoundError(f"acquisition contract does not exist: {contract_path}")
    contract_bytes = contract_path.read_bytes()
    contract_sha256 = sha256_bytes(contract_bytes)
    if contract_sha256 != expected_contract_sha256:
        raise AcquisitionError(
            "acquisition contract SHA-256 mismatch: "
            f"expected {expected_contract_sha256}, got {contract_sha256}"
        )

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            suffix=".partial",
            dir=destination.parent,
        )
    )
    try:
        contract_snapshot_relative_path = Path("acquisition_contract.yml")
        _write_new(
            staging / contract_snapshot_relative_path,
            contract_bytes,
        )
        archive_payloads: dict[str, bytes] = {}
        archive_records: list[dict[str, object]] = []
        for key, url in ARCHIVE_PAGES.items():
            response = _normalize_fetch_result(fetcher(url), url)
            page = response.payload
            retrieved_utc = clock()
            archive_payloads[key] = page
            relative_path = Path("archive_pages") / ARCHIVE_SNAPSHOT_NAMES[key]
            _write_new(staging / relative_path, page)
            archive_records.append(
                {
                    "key": key,
                    "url": url,
                    "http_final_url": response.final_url,
                    "http_status": response.http_status,
                    "retrieved_utc": retrieved_utc,
                    "bytes": len(page),
                    "sha256": sha256_bytes(page),
                    "relative_path": relative_path.as_posix(),
                }
            )

        sources = discover_sources(archive_payloads)
        payload_records: list[dict[str, object]] = []
        archive_hashes = {
            record["key"]: record["sha256"] for record in archive_records
        }
        for source in sources:
            response = _normalize_fetch_result(fetcher(source.url), source.url)
            served_filename = _validate_payload_identity(
                response,
                source.target.filename,
            )
            raw = response.payload
            retrieved_utc = clock()
            header, header_line_count, data_record_count = extract_icartt_header(raw)
            raw_relative_path = Path("raw") / source.target.filename
            header_relative_path = (
                Path("headers") / f"{source.target.filename}.header"
            )
            _write_new(staging / raw_relative_path, raw)
            _write_new(staging / header_relative_path, header)
            digest = sha256_bytes(raw)
            payload_records.append(
                {
                    "family": source.target.family,
                    "revision": source.target.revision,
                    "archive_filename": source.target.filename,
                    "archive_page_key": source.target.archive_page,
                    "archive_href": source.href,
                    "archive_url": source.url,
                    "http_final_url": response.final_url,
                    "http_status": response.http_status,
                    "content_disposition": response.content_disposition,
                    "served_filename": served_filename,
                    "archive_page_sha256": archive_hashes[
                        source.target.archive_page
                    ],
                    "retrieved_utc": retrieved_utc,
                    "bytes": len(raw),
                    "sha256": digest,
                    "raw_relative_path": raw_relative_path.as_posix(),
                    "header_relative_path": header_relative_path.as_posix(),
                    "header_bytes": len(header),
                    "header_line_count": header_line_count,
                    "header_sha256": sha256_bytes(header),
                    "header_encoding": "latin1-byte-preserving",
                    "data_record_count": data_record_count,
                    "source_record_identifier": {
                        "scheme": "payload-sha256:data-record-ordinal-zero-based",
                        "namespace": digest,
                        "first_identifier": (
                            f"{digest}:0" if data_record_count else None
                        ),
                    },
                    "header_evidence": inventory_header_evidence(header),
                    "authority_interpretation": (
                        "not inferred during byte acquisition; independent "
                        "semantic review required before transformation"
                    ),
                }
            )

        tool_path = Path(__file__).resolve()
        test_path = tool_path.with_name("test_fetch_firex_aq_tier_f.py")
        manifest: dict[str, object] = {
            "schema_version": 1,
            "manifest_id": "stage1-firex-aq-tier-f-acquisition-20190806-v1",
            "status": "byte-and-header-sealed-semantic-authority-review-pending",
            "campaign": "FIREX-AQ",
            "platform": "DC-8",
            "flight_date": "2019-08-06",
            "created_utc": clock(),
            "contract": {
                "path": str(contract_path),
                "sha256": contract_sha256,
                "snapshot_relative_path": (
                    contract_snapshot_relative_path.as_posix()
                ),
            },
            "tool": {
                "path": str(tool_path),
                "sha256": sha256_file(tool_path),
                "focused_test_path": str(test_path),
                "focused_test_sha256": (
                    sha256_file(test_path) if test_path.is_file() else None
                ),
            },
            "runtime": {
                "python_executable": sys.executable,
                "python_version": sys.version,
            },
            "archive_pages": archive_records,
            "payloads": payload_records,
            "acquisition_gate": {
                "expected_payload_count": len(TARGETS),
                "observed_payload_count": len(payload_records),
                "exact_filename_and_revision_links": "PASS",
                "byte_and_header_seal": "PASS",
                "complete_headers_preserved": True,
                "fresh_destination_no_overwrite": True,
                "publication_protocol": (
                    "exclusive-root-reservation-and-atomic-seal-last"
                ),
                "required_completion_seal": ACQUISITION_SEAL,
                "semantic_authority_review": "PENDING",
                "transformation_authorized": False,
                "join_authorized": False,
            },
        }
        rendered = (
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        _write_new(staging / "tier_f_acquisition_manifest.json", rendered)
        seal_payload = (
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "SEALED",
                    "manifest_relative_path": (
                        "tier_f_acquisition_manifest.json"
                    ),
                    "manifest_sha256": sha256_bytes(rendered),
                    "contract_sha256": contract_sha256,
                    "payload_count": len(payload_records),
                    "sealed_utc": clock(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        _publish_noreplace(staging, destination, seal_payload)
        return manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = acquire(
        args.output_dir,
        contract_path=args.contract,
        expected_contract_sha256=args.contract_sha256,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
