#!/usr/bin/env python3
"""Focused synthetic tests for the August-2/3 Phase-1 authority tool.

The suite uses only temporary synthetic bytes.  It performs no network access,
does not read campaign payload bodies, and does not create the frozen
acquisition or audit roots.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from fetch_firex_aq_phase1_authorities_20190802_20190803 import (
    FINAL_SEAL_NAME,
    FROZEN_PYTHON,
    MIRROR_FIELDS,
    NASA_ORIGIN,
    PAGES,
    R12_HEADERS,
    R9_FIELDS,
    STOP_RECORD_NAME,
    TARGETS,
    AcquisitionError,
    DocumentaryFile,
    DocumentarySpec,
    FetchResult,
    IcarttPayload,
    PageTarget,
    PayloadTarget,
    _NoRedirect,
    _audit_exact_inventory,
    _normalize_response,
    _seal_attempt_noreplace,
    _served_filename,
    acquire,
    audit_product_header,
    audit_r12_workbook,
    audit_r9,
    audit_r9_mrg01,
    canonical_identifier,
    compare_r9_r12_intervals,
    confirm_r12_archive_anchor,
    discover_payload_urls,
    parse_icartt,
    sha256_bytes,
    verify_documentary_authorities,
    verify_frozen_parent_files,
)


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def archive_pages(
    targets: tuple[PayloadTarget, ...] = TARGETS,
    pages: tuple[PageTarget, ...] = PAGES,
) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for page in pages:
        entries = [
            (
                f'<a href="/cgi-bin/enzFile?date={target.date}&amp;'
                f'product={target.product}">{target.filename}</a>'
            )
            for target in targets
            if target.page_key == page.key
        ]
        if page.key == "NASA_ANALYSIS":
            entries.append(
                '<a href="/analysis/r12">'
                "FIREXAQ-FIREFLAG-TABULARDATA_Analysis_"
                "20190724_R12_thru20190905.xlsx</a>"
            )
        result[page.key] = ("\n".join(entries) + "\n").encode("latin1")
    return result


def _descriptions(product: str, fields: tuple[str, ...]) -> list[str]:
    exact: dict[str, tuple[str, str]] = {
        "smoke_flag": (
            "unitless",
            "smoke classification flag; 1=smoke; 0=no smoke",
        ),
        "background_flag": (
            "unitless",
            "background classification flag; 1=background; 0=no background",
        ),
        "transect_mce_ODR_chisq": (
            "unitless",
            "uncertainty chi-square diagnostic for orthogonal distance regression",
        ),
        "Latitude": ("degree_north", "aircraft latitude"),
        "Longitude": ("degree_east", "aircraft longitude"),
        "GPS_Altitude": ("m", "aircraft GPS altitude"),
        "abs_dry_405": ("Mm-1", "dry PAS absorption coefficient at 405 nm"),
        "abs_dry_532": ("Mm-1", "dry PAS absorption coefficient at 532 nm"),
        "abs_dry_664": ("Mm-1", "dry PAS absorption coefficient at 664 nm"),
        "AOP_Dilution_ratio": ("unitless", "AOP dilution context ratio"),
        "RH_CABIN": ("percent", "cabin relative humidity"),
        "AOP_Quality_Flag": ("unitless", "AOP quality flag"),
        "smoke_age": ("s", "age of smoke at time of aircraft measurement"),
        "smoke_age_unc": ("s", "uncertainty in age of smoke"),
        "smoke_age_corr": (
            "s",
            "age of smoke at time of aircraft measurement with correction",
        ),
        "smoke_agemethod": ("unitless", "trajectory age method code"),
        "rBC_mass_concentration": (
            "ng m-3",
            "refractory black carbon mass concentration",
        ),
        "rBC_precision": ("ng m-3", "refractory black carbon precision"),
        "BC_Dilution_Flag": ("unitless", "SP2 dilution state flag"),
        "SP2_QC_Flag": ("unitless", "SP2 quality control flag"),
        "Org": ("ug m-3", "organic aerosol mass concentration"),
        "Org_precision": ("ug m-3", "organic aerosol precision"),
        "Cloud_Flag": ("unitless", "AMS cloud-screen flag"),
        "AMS_QC_Flag": ("unitless", "AMS quality control flag"),
    }
    result = []
    for field in fields[1:]:
        units, description = exact.get(
            field,
            ("unitless", f"synthetic numeric {product} field {field}"),
        )
        result.append(f"{field}, {units}, none, {description}")
    return result


def icartt_fixture(
    target: PayloadTarget,
    *,
    rows: list[list[str]] | None = None,
    remove_marker: str | None = None,
    ffi: int = 1001,
    scale_value: str = "1",
    missing_value_override: str | None = None,
) -> bytes:
    sentinel = "-999999" if target.product == "mrg01" else "-9999"
    ulod = "-777777" if target.product == "mrg01" else "-7777"
    llod = "-888888" if target.product == "mrg01" else "-8888"
    if missing_value_override is not None:
        sentinel = missing_value_override
    comments: list[str] = [
        f"Missing values {sentinel}; ULOD {ulod}; LLOD {llod}",
    ]
    if target.product == "R9":
        fields = R9_FIELDS
        if rows is None:
            base = 100 if target.date == "2019-08-02" else 200
            fire = "2.1" if target.date == "2019-08-02" else "3.2"
            plume = "5.1" if target.date == "2019-08-02" else "6.2"
            rows = [
                [
                    str(time),
                    "1",
                    "3",
                    str(target.julian_day),
                    fire,
                    "-9999",
                    "1200",
                    "0.90000",
                    "7",
                    plume,
                    "0.91000",
                    "1.20000",
                    "5000",
                    "1",
                    "2",
                    "3",
                ]
                for time in (base, base + 1)
            ]
    elif target.product == "mrg01":
        fields = (
            "Time_Start",
            "Time_Stop",
            "Latitude",
            "Longitude",
            "GPS_Altitude",
        ) + MIRROR_FIELDS
        r9_target = next(
            item
            for item in TARGETS
            if item.date == target.date and item.product == "R9"
        )
        r9 = parse_icartt(icartt_fixture(r9_target), target.date)
        r9_lookup = {name.casefold(): index for index, name in enumerate(r9.fields)}
        rows = []
        for direct in r9.rows:
            start = direct[r9_lookup["time_start"]]
            rows.append(
                [start, str(int(start) + 1), "40", "-120", "1000"]
                + [
                    {
                        "-9999": "-999999",
                        "-7777": "-777777",
                        "-8888": "-888888",
                    }.get(direct[r9_lookup[field.casefold()]], direct[r9_lookup[field.casefold()]])
                    for field in MIRROR_FIELDS
                ]
            )
    elif target.product == "AOP":
        fields = (
            "Time_Start",
            "abs_dry_405",
            "abs_dry_532",
            "abs_dry_664",
            "AOP_Dilution_ratio",
            "RH_CABIN",
            "AOP_Quality_Flag",
        )
        comments.extend(
            (
                "PM2.5_STP dry PAS at 273 K and 1013 mbar",
                "high signal accuracy of 20%",
                "low signal precision varies with altitude and flight to flight",
                "AOP_Dilution_ratio is AOP context only",
            )
        )
    elif target.product == "FSU":
        fields = (
            "Time_Start",
            "smoke_age",
            "smoke_age_unc",
            "smoke_age_corr",
            "smoke_agemethod",
        )
        comments.extend(
            (
                "smoke_age, s, none, age of smoke at time of aircraft measurement",
                "smoke_age_unc, s, none, uncertainty in age of smoke",
                "smoke_age_corr, s, none, age of smoke at time of aircraft measurement with correction",
                'OTHER_COMMENTS: Key to "smoke_agemethod": '
                "1=HRRR,NAM,GFS (default); 2=HRRR,NAM; 3=HRRR,GFS; "
                "4=NAM,GFS; 5=HRRR; 6=NAM; 7=GFS",
            )
        )
    elif target.product == "SP2":
        fields = (
            "Time_Start",
            "rBC_mass_concentration",
            "rBC_precision",
            "BC_Dilution_Flag",
            "SP2_QC_Flag",
        )
        comments.extend(
            (
                "rBC precision and uncertainty are revision-local",
                "BC_Dilution_Flag is occupancy state, not AOP dilution magnitude",
            )
        )
    elif target.product == "AMS":
        fields = (
            "Time_Start",
            "Org",
            "Org_precision",
            "Cloud_Flag",
            "AMS_QC_Flag",
        )
        comments.extend(
            (
                "Org precision is revision-local",
                "Org detection limit and cloud-screen semantics",
            )
        )
    else:
        raise AssertionError(target.product)

    if rows is None:
        values = ["1"] * (len(fields) - 1)
        rows = [["10", *values], ["11", *values]]
    if remove_marker is not None:
        comments = [line.replace(remove_marker, "REMOVED") for line in comments]
    dependent_count = len(fields) - 1
    descriptions = _descriptions(target.product, fields)
    header = [
        "PLACEHOLDER",
        "Synthetic PI",
        "Synthetic organization",
        "Synthetic data source",
        "FIREX-AQ",
        "1,1",
        f"{target.date.replace('-', ',')},2026,08,11",
        "1",
        "Time_Start, seconds from midnight UTC",
        str(dependent_count),
        ",".join([scale_value] * dependent_count),
        ",".join([sentinel] * dependent_count),
        *descriptions,
        "0",
        str(len(comments)),
        *comments,
        ",".join(fields),
    ]
    header[0] = f"{len(header)},{ffi}"
    return (
        "\r\n".join(header)
        + "\r\n"
        + "\r\n".join(",".join(row) for row in rows)
        + "\r\n"
    ).encode("latin1")


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
        {"name": "30_June_2022", "sheetId": "1", f"{{{REL_NS}}}id": "rId1"},
    )
    worksheet = ET.Element(f"{{{MAIN_NS}}}worksheet")
    sheet_data = ET.SubElement(worksheet, f"{{{MAIN_NS}}}sheetData")
    header = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": "10"})
    for column, value in enumerate(R12_HEADERS, start=1):
        header.append(inline_cell(f"{column_name(column)}10", value))
    records = (
        (11, 214, 100, 101, "2.1", "7", "5.1"),
        (12, 215, 200, 201, "3.2", "7", "6.2"),
    )
    for number, julian, start, end, fire, transect, plume in records:
        row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": str(number)})
        row.append(inline_cell(f"C{number}", f"Fire {fire}"))
        row.append(numeric_cell(f"D{number}", fire))
        row.append(numeric_cell(f"E{number}", str(start)))
        row.append(numeric_cell(f"F{number}", str(end)))
        row.append(numeric_cell(f"H{number}", "3"))
        row.append(numeric_cell(f"S{number}", str(julian)))
        row.append(numeric_cell(f"T{number}", transect))
        row.append(numeric_cell(f"U{number}", plume))
    if formula:
        cell = ET.SubElement(
            sheet_data.find(f"{{{MAIN_NS}}}row"),
            f"{{{MAIN_NS}}}c",
            {"r": "AF10"},
        )
        ET.SubElement(cell, f"{{{MAIN_NS}}}f").text = "1+1"

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


def documentary_fixture(parent: Path) -> DocumentarySpec:
    root = parent / "documentary"
    raw = root / "raw"
    raw.mkdir(parents=True)
    payloads = {
        "R12": (
            "raw/r12.xlsx",
            workbook_fixture(),
            "glossary-codebook-exact-lexical-identifier-authority",
        ),
        "Holmes": (
            "raw/holmes.pdf",
            b"synthetic Holmes bytes",
            "provisional-FSU-trajectory-age-semantics-only",
        ),
        "Zeng": (
            "raw/zeng.pdf",
            b"synthetic Zeng bytes",
            "dataset-level-273K-1013mbar-state-only",
        ),
    }
    files = []
    for key, (relative, payload, role) in payloads.items():
        (root / relative).write_bytes(payload)
        files.append(DocumentaryFile(key, relative, sha256_bytes(payload), role))
    manifest_payload = b'{"status":"SEALED-EVIDENCE"}\n'
    manifest_name = "manifest.json"
    (root / manifest_name).write_bytes(manifest_payload)
    manifest_hash = sha256_bytes(manifest_payload)
    seal_payload = (
        json.dumps(
            {"status": "SEALED", "manifest_sha256": manifest_hash},
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    seal_name = "seal.json"
    (root / seal_name).write_bytes(seal_payload)
    return DocumentarySpec(
        root=root,
        seal_name=seal_name,
        seal_sha256=sha256_bytes(seal_payload),
        manifest_name=manifest_name,
        manifest_sha256=manifest_hash,
        files=tuple(files),
    )


def synthetic_fetch_map(
    targets: tuple[PayloadTarget, ...] = TARGETS,
    pages: tuple[PageTarget, ...] = PAGES,
) -> dict[str, FetchResult]:
    page_payloads = archive_pages(targets, pages)
    mapping: dict[str, FetchResult] = {}
    for page in pages:
        mapping[page.url] = FetchResult(
            page_payloads[page.key], page.url, 200, {"content-type": "text/html"}
        )
    discovered = discover_payload_urls(page_payloads, targets=targets, pages=pages)
    for target in targets:
        _, url = discovered[(target.date, target.product)]
        mapping[url] = FetchResult(
            icartt_fixture(target),
            url,
            200,
            {
                "content-disposition": f'attachment; filename="{target.filename}"',
                "content-type": "text/plain",
            },
        )
    return mapping


def synthetic_release_evidence(
    parent: Path,
    *,
    contract: Path,
    source: Path,
    test: Path,
    destination: Path,
    interpreter_sha256: str = "0" * 64,
    parent_aggregate_sha256: str | None = None,
    status: str = "PASS",
    authority_status: str = "AUTHORIZED",
    prefix: str = "evidence",
) -> tuple[Path, str, Path, str]:
    source = source.absolute()
    test = test.absolute()
    if parent_aggregate_sha256 is None:
        parent_aggregate_sha256 = sha256_bytes(b"")
    preflight = {
        "schema_version": 1,
        "evidence_kind": "phase1-authority-tooling-preflight",
        "status": status,
        "contract_sha256": sha256_bytes(contract.read_bytes()),
        "source_path": str(source),
        "source_sha256": sha256_bytes(source.read_bytes()),
        "test_path": str(test),
        "test_sha256": sha256_bytes(test.read_bytes()),
        "interpreter_path": str(FROZEN_PYTHON),
        "interpreter_sha256": interpreter_sha256,
        "attempt_root": str(destination.absolute()),
        "frozen_parent_inventory_sha256": parent_aggregate_sha256,
        "focused_tests_verdict": "PASS",
        "independent_code_audit_verdict": "PASS",
        "contract_audit_verdict": "PASS",
        "independent_code_auditor": "synthetic-independent-auditor",
    }
    preflight_payload = (json.dumps(preflight, sort_keys=True) + "\n").encode()
    preflight_path = parent / f"{prefix}-preflight.json"
    preflight_path.write_bytes(preflight_payload)
    preflight_sha = sha256_bytes(preflight_payload)
    authority = {
        "schema_version": 1,
        "evidence_kind": "explicit-same-turn-execution-authority",
        "status": authority_status,
        "action": "retrieve-audit-and-seal-exact-twelve-payload-phase1-bundle-only",
        "contract_sha256": sha256_bytes(contract.read_bytes()),
        "source_sha256": sha256_bytes(source.read_bytes()),
        "test_sha256": sha256_bytes(test.read_bytes()),
        "interpreter_path": str(FROZEN_PYTHON),
        "interpreter_sha256": interpreter_sha256,
        "attempt_root": str(destination.absolute()),
        "preflight_evidence_sha256": preflight_sha,
        "same_turn": True,
        "authority_id": f"{prefix}-synthetic-authority",
        "authorized_by": "synthetic-user",
        "issued_utc": "2026-08-10T23:59:00+00:00",
        "expires_utc": "2026-08-11T01:00:00+00:00",
    }
    authority_payload = (json.dumps(authority, sort_keys=True) + "\n").encode()
    authority_path = parent / f"{prefix}-authority.json"
    authority_path.write_bytes(authority_payload)
    return (
        preflight_path,
        preflight_sha,
        authority_path,
        sha256_bytes(authority_payload),
    )


class Phase1AuthorityTests(unittest.TestCase):
    def test_target_inventory_is_exact_and_date_local(self) -> None:
        self.assertEqual(len(TARGETS), 12)
        self.assertEqual(
            {date: sum(target.date == date for target in TARGETS) for date in {t.date for t in TARGETS}},
            {"2019-08-02": 6, "2019-08-03": 6},
        )
        self.assertEqual(len({(target.date, target.product) for target in TARGETS}), 12)
        self.assertEqual(
            next(t.revision for t in TARGETS if t.date == "2019-08-02" and t.product == "SP2"),
            "R2",
        )
        self.assertEqual(
            next(t.revision for t in TARGETS if t.date == "2019-08-03" and t.product == "AMS"),
            "R2",
        )
        self.assertEqual(
            [(target.date, target.product, target.revision, target.filename) for target in TARGETS],
            [
                ("2019-08-02", "mrg01", "R3", "FIREXAQ-mrg01-DC8_merge_20190802_R3.ict"),
                ("2019-08-02", "AOP", "R2", "firexaq-AOP-optical_DC8_20190802_R2.ict"),
                ("2019-08-02", "FSU", "R1", "firexaq-FSU-smokeage_dc8_20190802_R1.ict"),
                ("2019-08-02", "R9", "R9", "firexaq-fire-Flags-1HZ_DC8_20190802_R9.ict"),
                ("2019-08-02", "SP2", "R2", "FIREXAQ-SP2-BC-1HZ_DC8_20190802_R2.ict"),
                ("2019-08-02", "AMS", "R3", "FIREXAQ-AMS_DC8_20190802_R3.ict"),
                ("2019-08-03", "mrg01", "R3", "FIREXAQ-mrg01-DC8_merge_20190803_R3.ict"),
                ("2019-08-03", "AOP", "R2", "firexaq-AOP-optical_DC8_20190803_R2.ict"),
                ("2019-08-03", "FSU", "R1", "firexaq-FSU-smokeage_dc8_20190803_R1.ict"),
                ("2019-08-03", "R9", "R9", "firexaq-fire-Flags-1HZ_DC8_20190803_R9.ict"),
                ("2019-08-03", "SP2", "R3", "FIREXAQ-SP2-BC-1HZ_DC8_20190803_R3.ict"),
                ("2019-08-03", "AMS", "R2", "FIREXAQ-AMS_DC8_20190803_R2.ict"),
            ],
        )

    def test_import_has_no_side_effects(self) -> None:
        module_dir = Path(__file__).absolute().parent
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(module_dir)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import fetch_firex_aq_phase1_authorities_20190802_20190803; print('IMPORTED')",
            ],
            cwd=module_dir,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "IMPORTED\n")

    def test_archive_discovery_is_exact_unique_and_same_origin(self) -> None:
        pages = archive_pages()
        result = discover_payload_urls(pages)
        self.assertEqual(len(result), 12)
        self.assertTrue(all(url.startswith(NASA_ORIGIN) for _, url in result.values()))
        self.assertEqual(confirm_r12_archive_anchor(pages)["status"], "PASS")
        target = TARGETS[0]
        pages[target.page_key] += (
            f'<a href="/duplicate">{target.filename}</a>'.encode("latin1")
        )
        with self.assertRaisesRegex(AcquisitionError, "found 2"):
            discover_payload_urls(pages)
        analysis = archive_pages()
        analysis["NASA_ANALYSIS"] = b"<html>no sealed workbook anchor</html>"
        with self.assertRaisesRegex(AcquisitionError, "sealed R12 workbook"):
            confirm_r12_archive_anchor(analysis)

    def test_response_redirect_status_url_and_filename_fail_closed(self) -> None:
        url = PAGES[0].url
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
            _normalize_response(FetchResult(b"x", url, 206, {}), url)
        with self.assertRaisesRegex(AcquisitionError, "final response URL"):
            _normalize_response(FetchResult(b"x", url + "&moved=1", 200, {}), url)
        target = TARGETS[0]
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

    def test_complete_icartt_headers_and_revision_roles_are_audited(self) -> None:
        for target in TARGETS:
            parsed = parse_icartt(icartt_fixture(target), target.date)
            audit = audit_product_header(target, parsed)
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["revision"], target.revision)
            self.assertEqual(audit["file_format_index"], 1001)
            self.assertTrue(audit["time_domain_and_cadence"]["strictly_increasing"])
            self.assertEqual(
                audit["time_domain_and_cadence"]["cadence_seconds_exact_decimals"],
                ["1"],
            )
            self.assertEqual(
                len(audit["dependent_field_contracts"]),
                len(parsed.fields) - 1,
            )
            self.assertFalse(audit["values_transformed"])
        aop = next(target for target in TARGETS if target.product == "AOP")
        parsed = parse_icartt(
            icartt_fixture(aop, remove_marker="high signal accuracy of 20%"),
            aop.date,
        )
        with self.assertRaisesRegex(AcquisitionError, "accuracy/precision wording"):
            audit_product_header(aop, parsed)
        with self.assertRaisesRegex(AcquisitionError, "FFI 9999"):
            parse_icartt(icartt_fixture(aop, ffi=9999), aop.date)
        with self.assertRaisesRegex(AcquisitionError, "scale factor.*zero"):
            parse_icartt(icartt_fixture(aop, scale_value="0"), aop.date)
        with self.assertRaisesRegex(AcquisitionError, "non-finite"):
            parse_icartt(
                icartt_fixture(aop, missing_value_override="NaN"), aop.date
            )
        duplicate_time = parse_icartt(
            icartt_fixture(
                aop,
                rows=[
                    ["10", "1", "1", "1", "1", "1", "1"],
                    ["10", "1", "1", "1", "1", "1", "1"],
                ],
            ),
            aop.date,
        )
        with self.assertRaisesRegex(AcquisitionError, "duplicated, reversed, or unordered"):
            audit_product_header(aop, duplicate_time)

    def test_r9_r12_and_mrg01_are_date_local_without_august6_exceptions(self) -> None:
        r12_audit, rows_by_day = audit_r12_workbook(workbook_fixture(), (214, 215))
        self.assertFalse(
            r12_audit["counts_row_ranges_or_identifiers_inherited_from_August6"]
        )
        for date in ("2019-08-02", "2019-08-03"):
            r9_target = next(
                target for target in TARGETS if target.date == date and target.product == "R9"
            )
            merge_target = next(
                target
                for target in TARGETS
                if target.date == date and target.product == "mrg01"
            )
            r9 = parse_icartt(icartt_fixture(r9_target), date)
            merge = parse_icartt(icartt_fixture(merge_target), date)
            _, records, intervals = audit_r9(r9_target, r9)
            mirror = audit_r9_mrg01(date, r9, records, merge)
            self.assertEqual(mirror["time_domain_relation"], "exactly-equal")
            self.assertFalse(
                mirror["August6_fixed_format_or_terminal_exception_inherited"]
            )
            interval = compare_r9_r12_intervals(
                date, intervals, rows_by_day[r9_target.julian_day]
            )
            self.assertTrue(interval["one_to_one"])

            shortened = IcarttPayload(
                header=merge.header,
                header_line_count=merge.header_line_count,
                file_format_index=merge.file_format_index,
                header_lines=merge.header_lines,
                fields=merge.fields,
                rows=merge.rows[:-1],
                dependent_variable_count=merge.dependent_variable_count,
                scale_factors=merge.scale_factors,
                missing_values=merge.missing_values,
                variable_descriptions=merge.variable_descriptions,
                independent_variable_description=merge.independent_variable_description,
                file_date=merge.file_date,
            )
            with self.assertRaisesRegex(AcquisitionError, "exactly equal"):
                audit_r9_mrg01(date, r9, records, shortened)

            merge_lookup = {
                field.casefold(): index for index, field in enumerate(merge.fields)
            }
            unequal_rows = [list(row) for row in merge.rows]
            unequal_rows[0][merge_lookup["fire_id"]] = "2.100000000000001"
            unequal_identifier = replace(
                merge, rows=tuple(tuple(row) for row in unequal_rows)
            )
            with self.assertRaisesRegex(AcquisitionError, "unexplained date-local mismatches"):
                audit_r9_mrg01(date, r9, records, unequal_identifier)

            without_ulod = parse_icartt(
                icartt_fixture(merge_target, remove_marker="ULOD"), date
            )
            with self.assertRaisesRegex(AcquisitionError, "date-local ULOD sentinel"):
                audit_product_header(merge_target, without_ulod)

    def test_exact_decimal_identifiers_never_require_binary_float(self) -> None:
        self.assertEqual(canonical_identifier("10.20"), "10.2")
        self.assertNotEqual(canonical_identifier("10.199999999999999"), "10.2")
        self.assertEqual(canonical_identifier("13.100000000000000"), "13.1")
        self.assertEqual(canonical_identifier("10.234567890123"), "10.234567890123")
        with self.assertRaisesRegex(AcquisitionError, "non-finite"):
            canonical_identifier("NaN")

    def test_r9_smoke_intervals_require_a_date_local_unambiguous_codebook(self) -> None:
        target = next(
            item
            for item in TARGETS
            if item.date == "2019-08-02" and item.product == "R9"
        )
        exact = icartt_fixture(target)
        replacements = (
            (
                b"smoke classification flag; 1=smoke; 0=no smoke",
                b"smoke classification flag",
            ),
            (
                b"1=smoke; 0=no smoke",
                b"1=no smoke; 0=smoke",
            ),
            (
                b"1=smoke; 0=no smoke",
                b"1=smoke; 1=no smoke; 0=no smoke",
            ),
        )
        for old, new in replacements:
            parsed = parse_icartt(exact.replace(old, new), target.date)
            with self.assertRaisesRegex(
                AcquisitionError, "must unambiguously declare 1=smoke"
            ):
                audit_product_header(target, parsed)

        parsed = parse_icartt(exact, target.date)
        rows = [list(row) for row in parsed.rows]
        smoke_index = {
            field.casefold(): index for index, field in enumerate(parsed.fields)
        }["smoke_flag"]
        rows[0][smoke_index] = "2"
        undeclared = replace(parsed, rows=tuple(tuple(row) for row in rows))
        with self.assertRaisesRegex(AcquisitionError, "undeclared code '2'"):
            audit_r9(target, undeclared)

    def test_r12_formula_external_relationship_and_unsafe_path_fail(self) -> None:
        with self.assertRaisesRegex(AcquisitionError, "formulas"):
            audit_r12_workbook(workbook_fixture(formula=True), (214, 215))
        with self.assertRaisesRegex(AcquisitionError, "external relationships"):
            audit_r12_workbook(
                workbook_fixture(external_relationship=True), (214, 215)
            )
        with self.assertRaisesRegex(AcquisitionError, "unsafe OOXML"):
            audit_r12_workbook(workbook_fixture(unsafe_member=True), (214, 215))

    def test_documentary_seal_and_all_three_exact_bytes_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = documentary_fixture(Path(temporary))
            audit, paths = verify_documentary_authorities(spec)
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(set(paths), {"R12", "Holmes", "Zeng"})
            self.assertFalse(audit["August6_date_local_applicability_inherited"])
            paths["Holmes"].write_bytes(b"drift")
            with self.assertRaisesRegex(AcquisitionError, "Holmes"):
                verify_documentary_authorities(spec)

    def test_every_frozen_parent_is_recomputed_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "parent.txt"
            parent.write_bytes(b"immutable-parent\n")
            expected = sha256_bytes(parent.read_bytes())
            records, aggregate = verify_frozen_parent_files(
                (("synthetic-parent", parent, expected),)
            )
            self.assertEqual(records[0]["sha256"], expected)
            self.assertEqual(len(aggregate), 64)
            parent.write_bytes(b"drifted-parent\n")
            with self.assertRaisesRegex(AcquisitionError, "frozen parent SHA-256"):
                verify_frozen_parent_files(
                    (("synthetic-parent", parent, expected),)
                )

    def test_atomic_publication_seals_last_and_never_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            destination = parent / "authority-root"
            destination.mkdir()
            (destination / "payload").write_bytes(b"complete")
            seal = b'{"status":"SEALED"}\n'
            inventory = _seal_attempt_noreplace(destination, seal, {"payload"})
            self.assertEqual((destination / FINAL_SEAL_NAME).read_bytes(), seal)
            self.assertEqual((destination / "payload").read_bytes(), b"complete")
            self.assertEqual(inventory["final"]["regular_file_count"], 2)
            with self.assertRaisesRegex(AcquisitionError, "extra_files"):
                _seal_attempt_noreplace(destination, seal, {"payload"})
            self.assertEqual((destination / "payload").read_bytes(), b"complete")

    def test_inventory_rejects_dangling_symlink_extra_directory_and_special_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            dangling = parent / "dangling"
            dangling.mkdir()
            (dangling / "payload").write_bytes(b"complete")
            (dangling / FINAL_SEAL_NAME).symlink_to(parent / "absent")
            with self.assertRaisesRegex(AcquisitionError, "symlink"):
                _audit_exact_inventory(dangling, {"payload"})

            extra_directory = parent / "extra-directory"
            extra_directory.mkdir()
            (extra_directory / "payload").write_bytes(b"complete")
            (extra_directory / "unexpected").mkdir()
            with self.assertRaisesRegex(AcquisitionError, "extra_directories"):
                _audit_exact_inventory(extra_directory, {"payload"})

            special = parent / "special"
            special.mkdir()
            (special / "payload").write_bytes(b"complete")
            os.mkfifo(special / "unexpected-fifo")
            with self.assertRaisesRegex(AcquisitionError, "special file"):
                _audit_exact_inventory(special, {"payload"})

    def test_failed_seal_retains_unsealed_attempt_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "authority-root"
            destination.mkdir()
            (destination / "payload").write_bytes(b"complete")
            with patch(
                "fetch_firex_aq_phase1_authorities_20190802_20190803.os.link",
                side_effect=OSError("simulated seal failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    _seal_attempt_noreplace(destination, b"seal", {"payload"})
            self.assertTrue(destination.is_dir())
            self.assertEqual((destination / "payload").read_bytes(), b"complete")
            self.assertFalse((destination / FINAL_SEAL_NAME).exists())
            self.assertFalse(any(path.name.endswith(".partial") for path in destination.iterdir()))

    def test_every_late_publication_failure_removes_only_the_owned_seal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)

            unlink_root = parent / "unlink-failure"
            unlink_root.mkdir()
            (unlink_root / "payload").write_bytes(b"complete")
            original_unlink = Path.unlink

            def fail_temporary_unlink(path: Path, *args: object, **kwargs: object) -> None:
                if path.name.startswith(f".{FINAL_SEAL_NAME}."):
                    raise OSError("synthetic temporary unlink failure")
                original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", new=fail_temporary_unlink):
                with self.assertRaisesRegex(OSError, "temporary unlink failure"):
                    _seal_attempt_noreplace(
                        unlink_root, b"seal", {"payload"}
                    )
            self.assertFalse((unlink_root / FINAL_SEAL_NAME).exists())

            fsync_root = parent / "fsync-failure"
            fsync_root.mkdir()
            (fsync_root / "payload").write_bytes(b"complete")
            with patch(
                "fetch_firex_aq_phase1_authorities_20190802_20190803._fsync_directory",
                side_effect=OSError("synthetic fsync failure"),
            ):
                with self.assertRaisesRegex(OSError, "fsync failure"):
                    _seal_attempt_noreplace(fsync_root, b"seal", {"payload"})
            self.assertFalse((fsync_root / FINAL_SEAL_NAME).exists())

            injected_root = parent / "post-link-injection"
            injected_root.mkdir()
            (injected_root / "payload").write_bytes(b"complete")
            original_audit = _audit_exact_inventory
            audit_calls = 0

            def inject_before_final(root: Path, expected: set[str]) -> dict[str, object]:
                nonlocal audit_calls
                audit_calls += 1
                if audit_calls == 2:
                    (root / "injected-extra").write_bytes(b"race")
                return original_audit(root, expected)

            with patch(
                "fetch_firex_aq_phase1_authorities_20190802_20190803._audit_exact_inventory",
                side_effect=inject_before_final,
            ):
                with self.assertRaisesRegex(AcquisitionError, "extra_files"):
                    _seal_attempt_noreplace(
                        injected_root, b"seal", {"payload"}
                    )
            self.assertFalse((injected_root / FINAL_SEAL_NAME).exists())
            self.assertEqual((injected_root / "injected-extra").read_bytes(), b"race")

    def test_contract_or_root_failure_precedes_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"authorized: false\n")
            destination = parent / "authority"
            source = Path(__file__).with_name(
                "fetch_firex_aq_phase1_authorities_20190802_20190803.py"
            )
            common = {
                "contract_path": contract,
                "expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "expected_test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "expected_interpreter_sha256": "0" * 64,
                "preflight_evidence_path": parent / "absent-preflight.json",
                "expected_preflight_evidence_sha256": "0" * 64,
                "execution_authority_path": parent / "absent-authority.json",
                "expected_execution_authority_sha256": "0" * 64,
                "expected_destination": destination,
                "expected_contract_path": contract,
                "parent_files": (),
                "enforce_runtime": False,
                "fetcher": lambda _: self.fail("network must not be called"),
            }
            with self.assertRaisesRegex(AcquisitionError, "contract SHA-256"):
                acquire(destination, expected_contract_sha256="1" * 64, **common)
            destination.mkdir()
            with self.assertRaises(FileExistsError):
                acquire(
                    destination,
                    expected_contract_sha256=sha256_bytes(contract.read_bytes()),
                    **common,
                )
            destination.rmdir()
            dangling = parent / "dangling-authority"
            dangling.symlink_to(parent / "never-created")
            with self.assertRaises(FileExistsError):
                acquire(
                    dangling,
                    expected_contract_sha256=sha256_bytes(contract.read_bytes()),
                    **(common | {"expected_destination": dangling}),
                )
            with self.assertRaisesRegex(AcquisitionError, "source SHA-256"):
                acquire(
                    destination,
                    expected_contract_sha256=sha256_bytes(contract.read_bytes()),
                    **(common | {"expected_source_sha256": "2" * 64}),
                )
            with self.assertRaisesRegex(AcquisitionError, "test SHA-256"):
                acquire(
                    destination,
                    expected_contract_sha256=sha256_bytes(contract.read_bytes()),
                    **(common | {"expected_test_sha256": "3" * 64}),
                )

    def test_released_preflight_and_execution_authority_are_hash_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"synthetic_contract: true\n")
            source = Path(__file__).with_name(
                "fetch_firex_aq_phase1_authorities_20190802_20190803.py"
            )
            destination = parent / "authority"
            common = {
                "contract_path": contract,
                "expected_contract_sha256": sha256_bytes(contract.read_bytes()),
                "expected_source_sha256": sha256_bytes(source.read_bytes()),
                "expected_test_sha256": sha256_bytes(Path(__file__).read_bytes()),
                "expected_interpreter_sha256": "0" * 64,
                "clock": lambda: "2026-08-11T00:00:00+00:00",
                "expected_destination": destination,
                "expected_contract_path": contract,
                "parent_files": (),
                "enforce_runtime": False,
                "fetcher": lambda _: self.fail("network must not be called"),
            }
            failed = synthetic_release_evidence(
                parent,
                contract=contract,
                source=source,
                test=Path(__file__),
                destination=destination,
                status="FAIL",
                prefix="failed-preflight",
            )
            with self.assertRaisesRegex(AcquisitionError, "preflight evidence mismatch"):
                acquire(
                    destination,
                    preflight_evidence_path=failed[0],
                    expected_preflight_evidence_sha256=failed[1],
                    execution_authority_path=failed[2],
                    expected_execution_authority_sha256=failed[3],
                    **common,
                )
            denied = synthetic_release_evidence(
                parent,
                contract=contract,
                source=source,
                test=Path(__file__),
                destination=destination,
                authority_status="DENIED",
                prefix="denied-authority",
            )
            with self.assertRaisesRegex(AcquisitionError, "execution-authority evidence mismatch"):
                acquire(
                    destination,
                    preflight_evidence_path=denied[0],
                    expected_preflight_evidence_sha256=denied[1],
                    execution_authority_path=denied[2],
                    expected_execution_authority_sha256=denied[3],
                    **common,
                )
            denied[0].write_bytes(b"drift")
            with self.assertRaisesRegex(AcquisitionError, "preflight evidence SHA-256 mismatch"):
                acquire(
                    destination,
                    preflight_evidence_path=denied[0],
                    expected_preflight_evidence_sha256=denied[1],
                    execution_authority_path=denied[2],
                    expected_execution_authority_sha256=denied[3],
                    **common,
                )

    def test_full_synthetic_two_date_acquisition_is_all_or_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"synthetic_contract: true\n")
            destination = parent / "authority"
            documentary = documentary_fixture(parent)
            fetch_map = synthetic_fetch_map()
            source = Path(__file__).with_name(
                "fetch_firex_aq_phase1_authorities_20190802_20190803.py"
            )
            evidence = synthetic_release_evidence(
                parent,
                contract=contract,
                source=source,
                test=Path(__file__),
                destination=destination,
                prefix="successful",
            )
            manifest = acquire(
                destination,
                contract_path=contract,
                expected_contract_sha256=sha256_bytes(contract.read_bytes()),
                expected_source_sha256=sha256_bytes(source.read_bytes()),
                expected_test_sha256=sha256_bytes(Path(__file__).read_bytes()),
                expected_interpreter_sha256="0" * 64,
                preflight_evidence_path=evidence[0],
                expected_preflight_evidence_sha256=evidence[1],
                execution_authority_path=evidence[2],
                expected_execution_authority_sha256=evidence[3],
                fetcher=lambda url: fetch_map[url],
                clock=lambda: "2026-08-11T00:00:00+00:00",
                expected_destination=destination,
                expected_contract_path=contract,
                documentary_spec=documentary,
                parent_files=(),
                enforce_runtime=False,
            )
            self.assertEqual(manifest["acceptance"]["payload_identities"], "12/12-PASS")
            self.assertEqual(len(manifest["payloads"]), 12)
            self.assertFalse(manifest["acceptance"]["phase2_released"])
            self.assertEqual(
                manifest["acceptance"]["prospective_support"],
                {
                    "independent_clusters": 0,
                    "rows": 0,
                    "model_states": 0,
                    "passing_age_bins": 0,
                },
            )
            seal = json.loads((destination / FINAL_SEAL_NAME).read_text())
            self.assertEqual(seal["status"], "SEALED")
            self.assertEqual(seal["payload_count"], 12)
            self.assertEqual(seal["exact_successful_regular_file_count"], 33)
            self.assertEqual(
                sha256_bytes((destination / "phase1_authority_acquisition_manifest.json").read_bytes()),
                seal["manifest_sha256"],
            )
            inventory = _audit_exact_inventory(
                destination, set(manifest["publication_inventory"]["relative_files"])
            )
            self.assertEqual(inventory["regular_file_count"], 33)
            self.assertFalse(any(path.name.endswith(".partial") for path in destination.rglob("*")))

    def test_second_date_failure_retains_stop_and_retry_uses_fresh_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            contract = parent / "contract.yml"
            contract.write_bytes(b"synthetic_contract: true\n")
            base = parent / "authority"
            retry = Path(f"{base}-retry1")
            documentary = documentary_fixture(parent)
            fetch_map = synthetic_fetch_map()
            source = Path(__file__).with_name(
                "fetch_firex_aq_phase1_authorities_20190802_20190803.py"
            )
            failing_target = next(
                target
                for target in TARGETS
                if target.date == "2019-08-03" and target.product == "AOP"
            )
            pages = archive_pages()
            failing_url = discover_payload_urls(pages)[
                (failing_target.date, failing_target.product)
            ][1]
            base_evidence = synthetic_release_evidence(
                parent,
                contract=contract,
                source=source,
                test=Path(__file__),
                destination=base,
                prefix="failed-base",
            )

            def fail_on_second_date(url: str) -> FetchResult:
                if url == failing_url:
                    raise OSError("synthetic second-date retrieval failure")
                return fetch_map[url]

            common = {
                "contract_path": contract,
                "expected_contract_sha256": sha256_bytes(contract.read_bytes()),
                "expected_source_sha256": sha256_bytes(source.read_bytes()),
                "expected_test_sha256": sha256_bytes(Path(__file__).read_bytes()),
                "expected_interpreter_sha256": "0" * 64,
                "clock": lambda: "2026-08-11T00:00:00+00:00",
                "expected_destination": base,
                "expected_contract_path": contract,
                "documentary_spec": documentary,
                "parent_files": (),
                "enforce_runtime": False,
            }
            with self.assertRaisesRegex(OSError, "second-date retrieval failure"):
                acquire(
                    base,
                    preflight_evidence_path=base_evidence[0],
                    expected_preflight_evidence_sha256=base_evidence[1],
                    execution_authority_path=base_evidence[2],
                    expected_execution_authority_sha256=base_evidence[3],
                    fetcher=fail_on_second_date,
                    **common,
                )
            stop = json.loads((base / STOP_RECORD_NAME).read_text())
            self.assertEqual(stop["status"], "FAILED-UNSEALED-DO-NOT-REUSE")
            self.assertFalse((base / FINAL_SEAL_NAME).exists())
            self.assertTrue(any((base / "raw" / "20190802").iterdir()))

            retry_evidence = synthetic_release_evidence(
                parent,
                contract=contract,
                source=source,
                test=Path(__file__),
                destination=retry,
                prefix="successful-retry1",
            )
            manifest = acquire(
                retry,
                preflight_evidence_path=retry_evidence[0],
                expected_preflight_evidence_sha256=retry_evidence[1],
                execution_authority_path=retry_evidence[2],
                expected_execution_authority_sha256=retry_evidence[3],
                fetcher=lambda url: fetch_map[url],
                **common,
            )
            self.assertEqual(manifest["retry_number"], 1)
            self.assertTrue((retry / FINAL_SEAL_NAME).is_file())
            self.assertTrue((base / STOP_RECORD_NAME).is_file())


if __name__ == "__main__":
    unittest.main()
