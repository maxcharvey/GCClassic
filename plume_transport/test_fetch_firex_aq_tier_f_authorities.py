#!/usr/bin/env python3
"""Focused tests for the frozen Tier-F ancillary-authority acquisition."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib

from fetch_firex_aq_tier_f_authorities import (
    AUTHORITY_SEAL,
    NASA_ORIGIN,
    NASA_TARGETS,
    PAGE_BY_KEY,
    R12_HEADERS,
    R9_FIELDS,
    AcquisitionError,
    FetchResult,
    PdfTarget,
    R9Expectations,
    WorkbookExpectations,
    _NoRedirect,
    _normalize_response,
    _pdf_page_count,
    _publish_noreplace,
    _sentinel_kind,
    _serialize_mrg01_continuous,
    _served_filename,
    acquire,
    audit_pdf,
    audit_r12,
    audit_r9,
    canonical_identifier,
    compare_r9_r12_intervals,
    discover_nasa_urls,
)


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def archive_page(targets: tuple = NASA_TARGETS) -> bytes:
    return "\n".join(
        f'<a href="/cgi-bin/enzFile?opaque={index}">{target.filename}</a>'
        for index, target in enumerate(targets)
    ).encode("latin1")


def r9_fixture() -> tuple[bytes, R9Expectations]:
    header = [
        "PLACEHOLDER",
        "PI",
        "Institution",
        "Data source",
        "FIREX-AQ",
        "1,1",
        "2019,08,06,2023,03,08",
        "1",
        "TIME_START, seconds since midnight UTC",
        "15",
        ",".join(["1"] * 15),
        ",".join(R9_FIELDS),
    ]
    header[0] = f"{len(header)},1001"
    header.insert(11, "Missing -9999; ULOD -7777; LLOD -8888")
    header[0] = f"{len(header)},1001"
    fields_line = header.pop()
    header.append(fields_line)

    rows = []
    fire_ids = ("10.1", "10.2", "10", "11")
    plume_ids = ("13.1", "13.2", "14", "15")
    smoke_ordinal = 0
    for ordinal, time in enumerate(range(100, 149)):
        smoke = ordinal % 2 == 0
        if smoke:
            fire = fire_ids[smoke_ordinal % len(fire_ids)]
            plume = plume_ids[smoke_ordinal % len(plume_ids)]
            transect = str(smoke_ordinal)
            smoke_ordinal += 1
        else:
            fire = plume = transect = "-9999"
        rows.append(
            [
                str(time),
                "1" if smoke else "-9999",
                "1" if smoke else "-9999",
                "218",
                fire,
                "1" if (not smoke and ordinal % 4 == 1) else "-9999",
                "100" if smoke else "-9999",
                "0.9" if smoke else "-9999",
                transect,
                plume,
                "0.91" if smoke else "-9999",
                "1.2" if smoke else "-9999",
                "5000" if smoke else "-9999",
                "1" if smoke else "-9999",
                "2" if smoke else "-9999",
                "3" if smoke else "-9999",
            ]
        )
    raw = (
        "\r\n".join(header)
        + "\r\n"
        + "\r\n".join(",".join(row) for row in rows)
        + "\r\n"
    ).encode("latin1")
    header_bytes = ("\r\n".join(header) + "\r\n").encode("latin1")
    expectations = R9Expectations(
        header_lines=len(header),
        header_bytes=len(header_bytes),
        header_sha256=hashlib.sha256(header_bytes).hexdigest(),
        records=len(rows),
        columns=16,
        first_time=100,
        last_time=148,
        smoke_intervals=25,
        smoke_records=25,
    )
    return raw, expectations


def column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def inline_cell(reference: str, value: str) -> ET.Element:
    cell = ET.Element(f"{{{MAIN_NS}}}c", {"r": reference, "t": "inlineStr"})
    inline = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
    text = ET.SubElement(inline, f"{{{MAIN_NS}}}t")
    text.text = value
    return cell


def numeric_cell(reference: str, value: str) -> ET.Element:
    cell = ET.Element(f"{{{MAIN_NS}}}c", {"r": reference})
    node = ET.SubElement(cell, f"{{{MAIN_NS}}}v")
    node.text = value
    return cell


def workbook_fixture(
    *,
    formula: bool = False,
    external_relationship: bool = False,
    unsafe_member: bool = False,
) -> bytes:
    ET.register_namespace("", MAIN_NS)
    ET.register_namespace("r", REL_NS)

    workbook = ET.Element(f"{{{MAIN_NS}}}workbook")
    sheets = ET.SubElement(workbook, f"{{{MAIN_NS}}}sheets")
    ET.SubElement(
        sheets,
        f"{{{MAIN_NS}}}sheet",
        {
            "name": "30_June_2022",
            "sheetId": "1",
            f"{{{REL_NS}}}id": "rId1",
        },
    )

    worksheet = ET.Element(f"{{{MAIN_NS}}}worksheet")
    ET.SubElement(worksheet, f"{{{MAIN_NS}}}dimension", {"ref": "A1:AF718"})
    sheet_data = ET.SubElement(worksheet, f"{{{MAIN_NS}}}sheetData")
    header_row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": "164"})
    for column, value in enumerate(R12_HEADERS, start=1):
        header_row.append(inline_cell(f"{column_name(column)}164", value))

    fire_ids = ("10.1", "10.199999999999999", "10", "11")
    fire_names = {
        "10.1": "Spokane/WF/BC",
        "10.199999999999999": "Eagles Bluff, BC/WF",
        "10": "Williams Flats",
        "11": "Horsefly",
    }
    plume_ids = ("13.1", "13.2", "14", "15")
    for row_number in range(165, 719):
        row = ET.SubElement(
            sheet_data, f"{{{MAIN_NS}}}row", {"r": str(row_number)}
        )
        row.append(inline_cell(f"G{row_number}", "NaN"))
        row.append(inline_cell(f"N{row_number}", "NaN"))
        is_august6 = 324 <= row_number <= 348
        row.append(
            numeric_cell(f"S{row_number}", "218" if is_august6 else "217")
        )
        if is_august6:
            ordinal = row_number - 324
            fire = fire_ids[ordinal % len(fire_ids)]
            plume = plume_ids[ordinal % len(plume_ids)]
            start = 1000 + ordinal * 10
            row.append(inline_cell(f"C{row_number}", fire_names[fire]))
            row.append(numeric_cell(f"D{row_number}", fire))
            row.append(numeric_cell(f"E{row_number}", str(start)))
            row.append(numeric_cell(f"F{row_number}", str(start + 4)))
            row.append(numeric_cell(f"H{row_number}", "3"))
            row.append(numeric_cell(f"T{row_number}", str(ordinal)))
            row.append(numeric_cell(f"U{row_number}", plume))
        if formula and row_number == 165:
            cell = ET.SubElement(row, f"{{{MAIN_NS}}}c", {"r": "A165"})
            expression = ET.SubElement(cell, f"{{{MAIN_NS}}}f")
            expression.text = "1+1"

    relationships = ET.Element(f"{{{PACKAGE_REL_NS}}}Relationships")
    ET.SubElement(
        relationships,
        f"{{{PACKAGE_REL_NS}}}Relationship",
        {
            "Id": "rId1",
            "Type": (
                "http://schemas.openxmlformats.org/officeDocument/"
                "2006/relationships/worksheet"
            ),
            "Target": "worksheets/sheet1.xml",
        },
    )
    if external_relationship:
        ET.SubElement(
            relationships,
            f"{{{PACKAGE_REL_NS}}}Relationship",
            {
                "Id": "rId2",
                "Type": "http://example.invalid/external",
                "Target": "https://example.invalid/workbook.xlsx",
                "TargetMode": "External",
            },
        )

    content_types = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
        b'package.relationships+xml"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b"</Types>"
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr(
            "xl/workbook.xml",
            ET.tostring(workbook, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            ET.tostring(relationships, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            ET.tostring(worksheet, encoding="utf-8", xml_declaration=True),
        )
        if unsafe_member:
            archive.writestr("../escape", b"bad")
    return output.getvalue()


class AuthorityAcquisitionTests(unittest.TestCase):
    def test_exact_nasa_anchor_discovery(self) -> None:
        pages = {
            "NASA_DC8_index": archive_page((NASA_TARGETS[0],)),
            "NASA_ANALYSIS_index": archive_page((NASA_TARGETS[1],)),
        }
        sources = discover_nasa_urls(pages)
        self.assertEqual(set(sources), {"fire_flags_R9", "fire_glossary_R12"})
        self.assertTrue(
            all(url.startswith(f"{NASA_ORIGIN}/cgi-bin/") for _, url in sources.values())
        )

    def test_duplicate_wrong_revision_and_external_anchor_fail_closed(self) -> None:
        pages = {
            "NASA_DC8_index": archive_page((NASA_TARGETS[0],)),
            "NASA_ANALYSIS_index": archive_page((NASA_TARGETS[1],)),
        }
        target = NASA_TARGETS[0]
        exact = target.filename.encode()
        pages["NASA_DC8_index"] += (
            f'<a href="/duplicate">{target.filename}</a>'.encode()
        )
        with self.assertRaisesRegex(AcquisitionError, "found 2"):
            discover_nasa_urls(pages)

        pages["NASA_DC8_index"] = archive_page((target,)).replace(
            exact, target.filename.replace("_R9.", "_R8.").encode()
        )
        with self.assertRaisesRegex(AcquisitionError, "found 0"):
            discover_nasa_urls(pages)

        pages["NASA_DC8_index"] = archive_page((target,)).replace(
            b"/cgi-bin/enzFile?opaque=0",
            b"https://example.invalid/payload",
        )
        with self.assertRaisesRegex(AcquisitionError, "unexpected NASA"):
            discover_nasa_urls(pages)

    def test_response_status_origin_final_url_and_filename_are_strict(self) -> None:
        url = PAGE_BY_KEY["NASA_DC8_index"].url
        with self.assertRaisesRegex(AcquisitionError, "redirect prohibited"):
            _NoRedirect().redirect_request(
                urllib.request.Request(url),
                None,
                302,
                "Found",
                {},
                "https://example.invalid/payload",
            )
        with self.assertRaisesRegex(AcquisitionError, "HTTP status"):
            _normalize_response(
                FetchResult(b"x", url, 206, {}), url, exact_final_url=True
            )
        with self.assertRaisesRegex(AcquisitionError, "final response URL"):
            _normalize_response(
                FetchResult(b"x", url + "&redirected=1", 200, {}),
                url,
                exact_final_url=True,
            )
        with self.assertRaisesRegex(AcquisitionError, "origin"):
            _normalize_response(
                FetchResult(b"x", "https://example.invalid/x", 200, {}),
                url,
                exact_final_url=True,
            )

        target = NASA_TARGETS[0]
        wrong = FetchResult(
            b"x",
            url,
            200,
            {"content-disposition": 'attachment; filename="wrong.ict"'},
        )
        with self.assertRaisesRegex(AcquisitionError, "served filename"):
            _served_filename(wrong, target.filename)
        exact = replace(
            wrong,
            headers={
                "content-disposition": f'attachment; filename="{target.filename}"'
            },
        )
        self.assertEqual(_served_filename(exact, target.filename), target.filename)

    def test_exact_decimal_identifier_normalization_never_uses_float(self) -> None:
        self.assertEqual(canonical_identifier("10.199999999999999"), "10.2")
        self.assertEqual(canonical_identifier("13.100000000000000"), "13.1")
        self.assertEqual(canonical_identifier("10.234567890123"), "10.234567890123")
        self.assertEqual(_sentinel_kind("-9999.000000", True), "missing")
        self.assertEqual(_sentinel_kind("-777777.0", False), "ULOD")
        with self.assertRaisesRegex(AcquisitionError, "non-finite"):
            canonical_identifier("NaN")

    def test_mrg01_continuous_serialization_is_field_specific_and_exact(self) -> None:
        self.assertEqual(
            _serialize_mrg01_continuous("transect_smoke_mce", "0.854945")[0],
            "0.85494",
        )
        self.assertEqual(
            _serialize_mrg01_continuous("transect_mce_ODR", "0.994073")[0],
            "0.99407",
        )
        self.assertEqual(
            _serialize_mrg01_continuous(
                "transect_mce_ODR_chisq", "0.0123456"
            )[0],
            "0.012346",
        )
        self.assertEqual(
            _serialize_mrg01_continuous(
                "transect_mce_ODR_chisq", "9.123456"
            )[0],
            "9.12346",
        )
        self.assertEqual(
            _serialize_mrg01_continuous(
                "transect_mce_ODR_chisq", "10.12345"
            )[0],
            "10.1235",
        )
        with self.assertRaisesRegex(AcquisitionError, "outside"):
            _serialize_mrg01_continuous(
                "transect_mce_ODR_chisq", "100.0"
            )

    def test_r9_complete_header_cadence_and_lexical_ids(self) -> None:
        raw, expectations = r9_fixture()
        audit, records, intervals = audit_r9(raw, expectations)
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["record_count"], 49)
        self.assertEqual(audit["smoke_interval_count"], 25)
        self.assertEqual(len(records), 49)
        self.assertEqual(intervals[0]["fire_id"], "10.1")
        self.assertFalse(audit["science_transformation_or_join_performed"])

        broken = raw.replace(b"101,-9999", b"102,-9999", 1)
        with self.assertRaisesRegex(AcquisitionError, "cadence discontinuity"):
            audit_r9(broken, expectations)

    def test_lossless_ooxml_schema_and_known_identifier(self) -> None:
        audit, rows = audit_r12(workbook_fixture())
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["data_row_count"], 554)
        self.assertEqual(len(rows), 25)
        examples = audit["identifier_contract"]["lexical_examples"]
        self.assertTrue(
            any(
                item["raw_lexeme"] == "10.199999999999999"
                and item["exact_decimal_canonical"] == "10.2"
                for item in examples
            )
        )
        self.assertEqual(audit["columns_G_and_N"]["use"], "PROHIBITED")

    def test_ooxml_formula_external_link_and_unsafe_path_fail_closed(self) -> None:
        with self.assertRaisesRegex(AcquisitionError, "formula"):
            audit_r12(workbook_fixture(formula=True))
        with self.assertRaisesRegex(AcquisitionError, "external relationships"):
            audit_r12(workbook_fixture(external_relationship=True))
        with self.assertRaisesRegex(AcquisitionError, "unsafe OOXML"):
            audit_r12(workbook_fixture(unsafe_member=True))

    def test_interval_mapping_is_one_to_one_and_exact(self) -> None:
        rows = [
            {
                "start": 100,
                "end": 104,
                "record_count": 5,
                "fire_id": "10.2",
                "transect_number": "1",
                "plume_id": "13.2",
            }
        ]
        audit = compare_r9_r12_intervals(rows, [dict(rows[0])])
        self.assertEqual(audit["status"], "PASS")
        changed = [dict(rows[0], end=105)]
        with self.assertRaisesRegex(AcquisitionError, "mapping mismatch"):
            compare_r9_r12_intervals(rows, changed)

    def test_pdf_identity_uses_exact_bytes_and_page_objects(self) -> None:
        object_stream = zlib.compress(b"2 0 <</Type /Page>>")
        content_stream = b"/Type /Page"
        payload = (
            b"%PDF-1.4\n"
            b"1 0 obj <</Type /Page>> endobj\n"
            + (
                b"3 0 obj <</Type /ObjStm /N 1 /First 4 /Length "
                + str(len(object_stream)).encode("ascii")
                + b" /Filter /FlateDecode>>\nstream\n"
                + object_stream
                + b"\nendstream\nendobj\n"
            )
            + (
                b"4 0 obj <</Length "
                + str(len(content_stream)).encode("ascii")
                + b">>\nstream\n"
                + content_stream
                + b"\nendstream\nendobj\n"
            )
            + b"%%EOF\n"
        )
        target = PdfTarget(
            key="test",
            filename="test.pdf",
            url="https://essd.copernicus.org/test.pdf",
            relative_path="raw/test.pdf",
            title="Test PDF",
            doi="10.test/example",
            publication_state="test",
            identity_date="published-test-date",
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_pages=2,
        )
        audit = audit_pdf(payload, target)
        self.assertEqual(audit["page_count"], 2)
        self.assertEqual(audit["direct_page_dictionary_count"], 1)
        self.assertEqual(audit["parsed_object_stream_count"], 1)
        self.assertEqual(audit["title"], "Test PDF")
        with self.assertRaisesRegex(AcquisitionError, "expansion exceeds bound"):
            _pdf_page_count(payload, maximum_object_stream_bytes=5)
        with self.assertRaisesRegex(AcquisitionError, "identity mismatch"):
            audit_pdf(payload + b"x", target)

    def test_atomic_publication_seals_last_and_never_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            staging = parent / ".staging"
            destination = parent / "authority-root"
            staging.mkdir()
            (staging / "payload").write_bytes(b"complete")
            seal = b'{"status":"SEALED"}\n'
            _publish_noreplace(staging, destination, seal)
            self.assertEqual((destination / AUTHORITY_SEAL).read_bytes(), seal)
            self.assertEqual((destination / "payload").read_bytes(), b"complete")
            self.assertFalse((destination / ".authority_acquisition_owner").exists())

            second_staging = parent / ".second"
            second_staging.mkdir()
            (second_staging / "payload").write_bytes(b"replacement")
            with self.assertRaises(FileExistsError):
                _publish_noreplace(second_staging, destination, seal)
            self.assertEqual((destination / "payload").read_bytes(), b"complete")

    def test_failed_seal_removes_only_the_owned_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            staging = parent / ".staging"
            destination = parent / "authority-root"
            staging.mkdir()
            (staging / "payload").write_bytes(b"complete")
            with patch(
                "fetch_firex_aq_tier_f_authorities.os.link",
                side_effect=OSError("simulated seal failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    _publish_noreplace(staging, destination, b"seal")
            self.assertFalse(destination.exists())
            self.assertFalse(staging.exists())

    def test_contract_mismatch_and_preexisting_root_fail_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"authorized: true\n")
            destination = parent / "authority-root"
            source = Path(__file__).with_name(
                "fetch_firex_aq_tier_f_authorities.py"
            )
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            test_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            common = {
                "contract_path": contract,
                "expected_source_sha256": source_hash,
                "expected_test_sha256": test_hash,
                "focused_tests_verdict": "PASS",
                "independent_code_audit_verdict": "PASS",
                "independent_code_auditor": "unit-test",
                "expected_destination": destination,
                "expected_contract_path": contract,
                "enforce_runtime": False,
                "fetcher": lambda _: self.fail("network must not be called"),
            }
            with self.assertRaisesRegex(AcquisitionError, "contract SHA-256"):
                acquire(
                    destination,
                    expected_contract_sha256="0" * 64,
                    **common,
                )
            self.assertFalse(destination.exists())

            destination.mkdir()
            with self.assertRaises(FileExistsError):
                acquire(
                    destination,
                    expected_contract_sha256=hashlib.sha256(
                        contract.read_bytes()
                    ).hexdigest(),
                    **common,
                )

    def test_post_commit_interrupt_preserves_valid_seal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            staging = parent / ".staging"
            destination = parent / "authority-root"
            staging.mkdir()
            (staging / "payload").write_bytes(b"complete")
            seal = b'{"status":"SEALED"}\n'
            real_link = os.link

            def link_then_interrupt(source: Path, target: Path) -> None:
                real_link(source, target)
                raise KeyboardInterrupt("simulated post-commit interrupt")

            with patch(
                "fetch_firex_aq_tier_f_authorities.os.link",
                side_effect=link_then_interrupt,
            ):
                _publish_noreplace(staging, destination, seal)
            self.assertEqual((destination / AUTHORITY_SEAL).read_bytes(), seal)
            self.assertEqual((destination / "payload").read_bytes(), b"complete")


if __name__ == "__main__":
    unittest.main()
