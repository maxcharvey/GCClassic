#!/usr/bin/env python3
"""Acquire and seal the frozen FIREX-AQ Tier-F ancillary authorities.

This program implements only the bounded v2 authority-acquisition contract.
It resolves two exact NASA archive anchors, downloads four byte-pinned
artifacts and four official page snapshots, validates the R9 ICARTT and R12
OOXML structures without transforming either payload, audits protected R9
mirrors against the already sealed mrg01 carrier, and publishes a completion
seal last into a fresh destination.

It does not create a science join, interpolate, aggregate, match model output,
construct cohorts, calculate statistics, or modify model inputs or source.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from email.message import Message
import hashlib
from html.parser import HTMLParser
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import secrets
import shutil
import stat
import sys
import tempfile
from typing import Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib


CONTRACT_PATH = Path(
    "/cluster/home/mharvey/CharvBrain/project-vaults/gc-plume-transport/"
    "manifests/stage1-firex-aq-tier-f-authority-acquisition-20190806-v2.yml"
)
CONTRACT_SHA256 = (
    "4c92f52681b60d1e01bae91f414114118d320731df22f12a7b4b28907e7bce9e"
)
DESTINATION = Path(
    "/cluster/work/climate/mharvey/Data/FIREX-AQ/"
    "tier-f-20190806-authorities-v2"
)
SEALED_V1_ROOT = Path(
    "/cluster/work/climate/mharvey/Data/FIREX-AQ/tier-f-20190806-v1"
)
FROZEN_PYTHON = Path(
    "/cluster/software/stacks/2024-06/spack/opt/spack/"
    "linux-ubuntu22.04-x86_64_v3/gcc-12.2.0/"
    "python-3.11.6-ukhwpjnwzzzizek3pgr75zkbhxros5fq/bin/python3.11"
)

NASA_ORIGIN = "https://www-air.larc.nasa.gov"
ALLOWED_ORIGINS = {
    "www-air.larc.nasa.gov",
    "essd.copernicus.org",
    "acp.copernicus.org",
}
AUTHORITY_SEAL = "AUTHORITY_ACQUISITION_SEAL.json"
MANIFEST_NAME = "tier_f_authority_acquisition_manifest.json"
V1_SEAL_SHA256 = (
    "fab2ea935a03dcf911782d2b410a84dbe7330b33ba7ff7be41919d446f883371"
)
V1_MANIFEST_SHA256 = (
    "5687ca23d0cb8845a6544b82fe4ea1508fb43d0c28588026aaf37b77f8c88ee7"
)


class AcquisitionError(RuntimeError):
    """Raised when an acceptance condition cannot be proved."""


@dataclass(frozen=True)
class PageTarget:
    key: str
    url: str
    relative_path: str
    required_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class NasaTarget:
    key: str
    filename: str
    revision: str
    page_key: str
    relative_path: str
    expected_bytes: int
    expected_sha256: str


@dataclass(frozen=True)
class PdfTarget:
    key: str
    filename: str
    url: str
    relative_path: str
    title: str
    doi: str
    publication_state: str
    identity_date: str
    expected_bytes: int
    expected_sha256: str
    expected_pages: int
    expected_last_modified: str | None = None


@dataclass(frozen=True)
class FetchResult:
    payload: bytes
    final_url: str
    http_status: int | None
    headers: Mapping[str, str]


@dataclass(frozen=True)
class R9Expectations:
    header_lines: int = 66
    header_bytes: int = 4587
    header_sha256: str = (
        "1466696826c369881e7b492c613ec9f129cc6bd42989b9947768236b988c4344"
    )
    records: int = 27097
    columns: int = 16
    first_time: int = 64994
    last_time: int = 92090
    smoke_intervals: int = 25
    smoke_records: int = 5253


@dataclass(frozen=True)
class WorkbookExpectations:
    sheet_name: str = "30_June_2022"
    dimension: str = "A1:AF718"
    header_row: int = 164
    first_data_row: int = 165
    last_data_row: int = 718
    data_row_count: int = 554
    august6_first_row: int = 324
    august6_last_row: int = 348
    august6_count: int = 25


PAGES = (
    PageTarget(
        "NASA_DC8_index",
        f"{NASA_ORIGIN}/cgi-bin/ArcView/firexaq?DC8=1",
        "pages/NASA_FIREXAQ_DC8_index.html",
    ),
    PageTarget(
        "NASA_ANALYSIS_index",
        f"{NASA_ORIGIN}/cgi-bin/ArcView/firexaq?ANALYSIS=1",
        "pages/NASA_FIREXAQ_ANALYSIS_index.html",
    ),
    PageTarget(
        "Holmes_landing",
        "https://essd.copernicus.org/preprints/essd-2025-307/",
        "pages/Holmes_ESSD_preprint_landing.html",
        (
            "10.5194/essd-2025-307",
            "Age of smoke sampled by aircraft during FIREX-AQ: "
            "methods and critical evaluation",
        ),
    ),
    PageTarget(
        "Zeng_landing",
        "https://acp.copernicus.org/articles/22/8009/2022/",
        "pages/Zeng_ACP_article_landing.html",
        (
            "10.5194/acp-22-8009-2022",
            "Characteristics and evolution of brown carbon in western "
            "United States wildfires",
        ),
    ),
)
PAGE_BY_KEY = {target.key: target for target in PAGES}

NASA_TARGETS = (
    NasaTarget(
        "fire_flags_R9",
        "firexaq-fire-Flags-1HZ_DC8_20190806_R9.ict",
        "R9",
        "NASA_DC8_index",
        "raw/firexaq-fire-Flags-1HZ_DC8_20190806_R9.ict",
        2_957_841,
        "6f65a48c88f94336e31db114803fa81587a3789504e20fea72e1ea21b23a40f9",
    ),
    NasaTarget(
        "fire_glossary_R12",
        "FIREXAQ-FIREFLAG-TABULARDATA_Analysis_20190724_R12_thru20190905.xlsx",
        "R12",
        "NASA_ANALYSIS_index",
        (
            "raw/FIREXAQ-FIREFLAG-TABULARDATA_Analysis_"
            "20190724_R12_thru20190905.xlsx"
        ),
        156_981,
        "4ab01547551d6ba9dc22feed3bbea4ffec58727c50f6ee92774320149c87815b",
    ),
)

PDF_TARGETS = (
    PdfTarget(
        "Holmes_original_discussion_PDF",
        "essd-2025-307.pdf",
        "https://essd.copernicus.org/preprints/essd-2025-307/essd-2025-307.pdf",
        "raw/essd-2025-307.pdf",
        "Age of smoke sampled by aircraft during FIREX-AQ: methods and "
        "critical evaluation",
        "10.5194/essd-2025-307",
        "under-review-original-discussion-preprint",
        "discussion-started-2025-06-24",
        9_104_533,
        "1af731b89846ca3b79110883ece9e29382252c07b9153d7fba911c19c10a29c3",
        29,
        "Tue, 05 May 2026 07:42:15 GMT",
    ),
    PdfTarget(
        "Zeng_final_PDF",
        "acp-22-8009-2022.pdf",
        "https://acp.copernicus.org/articles/22/8009/2022/acp-22-8009-2022.pdf",
        "raw/acp-22-8009-2022.pdf",
        "Characteristics and evolution of brown carbon in western United "
        "States wildfires",
        "10.5194/acp-22-8009-2022",
        "final-peer-reviewed",
        "published-2022-06-21",
        6_860_818,
        "f505d6dab97e768c23d157e8ccfdb2100b7ffc639efc1c9d88315ada7ed8f4c5",
        28,
    ),
)

R9_FIELDS = (
    "TIME_START",
    "smoke_flag",
    "transect_type",
    "Julian_date",
    "fire_id",
    "background_flag",
    "transect_smoke_age",
    "transect_smoke_mce",
    "transect_number",
    "transect_plume_number",
    "transect_mce_ODR",
    "transect_mce_ODR_chisq",
    "fire_distance_estimate",
    "transect_major_fuel",
    "transect_constituent_fuel",
    "transect_smoke_fuel_conf",
)
MIRROR_FIELDS = tuple(field for field in R9_FIELDS[1:] if field != "Julian_date")

R12_HEADERS = (
    "Comments",
    "Specific Change from R11",
    "transec_source_fire_namestr",
    "transect_source_fire_ID",
    "transect_start_time (UTC s from midnight)",
    "transect_end_time (UTC s from midnight)",
    "transect_source_fire_type",
    "transect_type",
    "transect_altitude (MSL, m)",
    "transect_MCE",
    "transect_BG_CO (ppb)",
    "transect_BG_CO2(ppm)",
    "transect_emis_time (UTC s from midnight)",
    "transect_fuel",
    "transect_major_fuel",
    "transect_constituent_fuel",
    "transect_smoke_fuel_conf",
    "transect_ignition",
    "transect_julian_date",
    "transect_number",
    "transect_plume_number",
    "transect_source_fire_alt",
    "transect_source_fire_lat",
    "transect_source_fire_long",
    "transect_s_distance (m)",
    "transect_windspeed (m/s)",
    "transect_smoke_age (s)",
    "transect_structures_boolean",
    "transect_suppresion_boolean",
    "transect_MCE_ODR",
    "transect_mce_odr_chisq",
)

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href is not None:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> urllib.request.Request | None:
        raise AcquisitionError(
            f"HTTP redirect prohibited for exact URL {request.full_url!r}: "
            f"{code} -> {new_url!r}"
        )


def fetch_resource(url: str) -> FetchResult:
    _origin(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "gc-plume-transport-authority-acquisition/2",
            "Accept": "*/*",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=180) as response:
        return FetchResult(
            payload=response.read(),
            final_url=response.geturl(),
            http_status=response.getcode(),
            headers={key.lower(): value for key, value in response.headers.items()},
        )


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise AcquisitionError(f"URL is not an uncredentialed HTTPS URL: {url!r}")
    if parsed.hostname not in ALLOWED_ORIGINS:
        raise AcquisitionError(f"prohibited network origin in URL: {url!r}")
    if parsed.port not in (None, 443):
        raise AcquisitionError(f"prohibited non-default port in URL: {url!r}")
    return parsed.hostname


def _normalize_response(
    result: bytes | FetchResult,
    requested_url: str,
    *,
    exact_final_url: bool,
) -> FetchResult:
    _origin(requested_url)
    if isinstance(result, bytes):
        response = FetchResult(result, requested_url, None, {})
    elif isinstance(result, FetchResult):
        response = result
    else:
        raise TypeError(
            "fetcher must return bytes or FetchResult, got "
            f"{type(result).__name__}"
        )
    if _origin(response.final_url) != _origin(requested_url):
        raise AcquisitionError(
            f"final response origin mismatch for {requested_url!r}: "
            f"{response.final_url!r}"
        )
    if exact_final_url and response.final_url != requested_url:
        raise AcquisitionError(
            f"final response URL mismatch: expected {requested_url!r}, "
            f"got {response.final_url!r}"
        )
    if response.http_status is not None and response.http_status != 200:
        raise AcquisitionError(
            f"unexpected HTTP status {response.http_status} for {requested_url!r}"
        )
    return response


def _served_filename(response: FetchResult, expected: str) -> str | None:
    value = response.headers.get("content-disposition")
    if response.http_status is None and value is None:
        return None
    if value is None:
        raise AcquisitionError(f"missing Content-Disposition for {expected}")
    message = Message()
    message["Content-Disposition"] = value
    observed = message.get_filename()
    if observed != expected:
        raise AcquisitionError(
            f"served filename mismatch: expected {expected!r}, got {observed!r}"
        )
    return observed


def _parse_anchors(page: bytes) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    try:
        parser.feed(page.decode("latin1"))
        parser.close()
    except Exception as error:
        raise AcquisitionError(f"could not parse archive page: {error}") from error
    return parser.anchors


def discover_nasa_urls(
    page_payloads: Mapping[str, bytes],
    targets: tuple[NasaTarget, ...] = NASA_TARGETS,
) -> dict[str, tuple[str, str]]:
    """Return exact, single live archive anchors for all NASA targets."""
    results: dict[str, tuple[str, str]] = {}
    for target in targets:
        page = PAGE_BY_KEY[target.page_key]
        candidates = [
            href
            for href, text in _parse_anchors(page_payloads[target.page_key])
            if text == target.filename
        ]
        if len(candidates) != 1:
            raise AcquisitionError(
                f"{target.filename}: expected exactly one exact archive anchor, "
                f"found {len(candidates)}"
            )
        href = candidates[0]
        resolved = urljoin(page.url, href)
        parsed = urlsplit(resolved)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www-air.larc.nasa.gov"
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
        ):
            raise AcquisitionError(
                f"unexpected NASA archive origin for {href!r}: {resolved!r}"
            )
        results[target.key] = (href, resolved)
    return results


def _validate_pin(payload: bytes, expected_bytes: int, expected_hash: str) -> None:
    observed_hash = sha256_bytes(payload)
    if len(payload) != expected_bytes or observed_hash != expected_hash:
        raise AcquisitionError(
            "payload identity mismatch: expected "
            f"{expected_bytes} bytes/{expected_hash}, got "
            f"{len(payload)} bytes/{observed_hash}"
        )


def extract_icartt_header(payload: bytes) -> tuple[bytes, int, list[list[str]]]:
    lines = payload.splitlines(keepends=True)
    if not lines:
        raise AcquisitionError("empty ICARTT payload")
    try:
        count = int(lines[0].decode("latin1").split(",", 1)[0].strip())
    except (UnicodeError, ValueError) as error:
        raise AcquisitionError("invalid ICARTT header-line count") from error
    if count < 1 or count > len(lines):
        raise AcquisitionError(
            f"invalid ICARTT header length {count} for {len(lines)} lines"
        )
    header = b"".join(lines[:count])
    data_text = b"".join(lines[count:]).decode("latin1")
    rows = [
        row
        for row in csv.reader(StringIO(data_text), skipinitialspace=True)
        if row and any(value.strip() for value in row)
    ]
    return header, count, rows


def _decimal(value: str, label: str) -> Decimal:
    try:
        result = Decimal(value.strip())
    except InvalidOperation as error:
        raise AcquisitionError(f"{label} is not an exact decimal: {value!r}") from error
    if not result.is_finite():
        raise AcquisitionError(f"{label} is non-finite: {value!r}")
    return result


def _integer(value: str, label: str) -> int:
    number = _decimal(value, label)
    if number != number.to_integral_value():
        raise AcquisitionError(f"{label} is not integral: {value!r}")
    return int(number)


def canonical_identifier(value: str) -> str:
    """Preserve exact decimal input while normalizing audited Excel noise.

    Relevant FIRE-FLAGS identifiers are integers or tenths. Normalization uses
    Decimal only. A value within exactly 1e-12 of a tenth is mapped to that
    tenth; all other finite decimal lexemes retain their exact normalized
    decimal value. The raw source lexeme is always recorded separately.
    """
    number = _decimal(value, "identifier")
    scaled = number * Decimal(10)
    nearest = scaled.to_integral_value(rounding=ROUND_HALF_EVEN)
    if abs(scaled - nearest) <= Decimal("1e-12"):
        number = nearest / Decimal(10)
    rendered = format(number.normalize(), "f")
    return "0" if rendered in ("-0", "") else rendered


def audit_r9(
    payload: bytes,
    expectations: R9Expectations = R9Expectations(),
) -> tuple[dict[str, object], dict[int, tuple[str, ...]], list[dict[str, object]]]:
    header, header_count, rows = extract_icartt_header(payload)
    if header_count != expectations.header_lines:
        raise AcquisitionError(f"R9 header line count mismatch: {header_count}")
    if len(header) != expectations.header_bytes:
        raise AcquisitionError(f"R9 header byte count mismatch: {len(header)}")
    if sha256_bytes(header) != expectations.header_sha256:
        raise AcquisitionError("R9 complete-header SHA-256 mismatch")
    header_lines = header.decode("latin1").splitlines()
    observed_fields = tuple(
        value.strip() for value in next(csv.reader([header_lines[-1]]))
    )
    if tuple(value.casefold() for value in observed_fields) != tuple(
        value.casefold() for value in R9_FIELDS
    ):
        raise AcquisitionError(f"R9 field schema mismatch: {observed_fields!r}")
    if len(rows) != expectations.records:
        raise AcquisitionError(f"R9 record count mismatch: {len(rows)}")
    if any(len(row) != expectations.columns for row in rows):
        raise AcquisitionError("R9 contains a row with the wrong column count")

    header_lower = header.lower()
    for marker in (b"-9999", b"-7777", b"-8888"):
        if marker not in header_lower:
            raise AcquisitionError(f"R9 header is missing sentinel {marker!r}")
    scale_line = tuple(
        value.strip() for value in header_lines[10].split(",")
    )
    if len(scale_line) != 15 or any(value != "1" for value in scale_line):
        raise AcquisitionError("R9 dependent-variable scale factors are not all 1")

    records: dict[int, tuple[str, ...]] = {}
    smoke_count = 0
    smoke_intervals: list[dict[str, object]] = []
    background_count = 0
    background_intervals = 0
    prior_smoke = False
    prior_background = False
    current: dict[str, object] | None = None
    for ordinal, row in enumerate(rows):
        time = _integer(row[0], f"R9 TIME_START row {ordinal}")
        expected_time = expectations.first_time + ordinal
        if time != expected_time:
            raise AcquisitionError(
                f"R9 cadence discontinuity at ordinal {ordinal}: "
                f"expected {expected_time}, got {time}"
            )
        records[time] = tuple(value.strip() for value in row)
        smoke = _decimal(row[1], "R9 smoke_flag") == 1
        background = _decimal(row[5], "R9 background_flag") == 1
        if smoke:
            smoke_count += 1
            if not prior_smoke:
                current = {
                    "start": time,
                    "end": time,
                    "record_count": 1,
                    "fire_id_raw": row[4].strip(),
                    "fire_id": canonical_identifier(row[4]),
                    "transect_number_raw": row[8].strip(),
                    "transect_number": canonical_identifier(row[8]),
                    "plume_id_raw": row[9].strip(),
                    "plume_id": canonical_identifier(row[9]),
                }
                smoke_intervals.append(current)
            else:
                assert current is not None
                current["end"] = time
                current["record_count"] = int(current["record_count"]) + 1
                for index, key in (
                    (4, "fire_id"),
                    (8, "transect_number"),
                    (9, "plume_id"),
                ):
                    if canonical_identifier(row[index]) != current[key]:
                        raise AcquisitionError(
                            f"R9 {key} changes within smoke interval at {time}"
                        )
        if background:
            background_count += 1
            if not prior_background:
                background_intervals += 1
        prior_smoke = smoke
        prior_background = background

    if rows and _integer(rows[-1][0], "R9 final TIME_START") != expectations.last_time:
        raise AcquisitionError("R9 final TIME_START mismatch")
    if smoke_count != expectations.smoke_records:
        raise AcquisitionError(f"R9 smoke-record count mismatch: {smoke_count}")
    if len(smoke_intervals) != expectations.smoke_intervals:
        raise AcquisitionError(
            f"R9 smoke-interval count mismatch: {len(smoke_intervals)}"
        )
    fire_ids = sorted({item["fire_id"] for item in smoke_intervals})
    plume_ids = sorted({item["plume_id"] for item in smoke_intervals})
    if set(fire_ids) != {"10", "10.1", "10.2", "11"}:
        raise AcquisitionError(f"R9 August 6 fire identifiers mismatch: {fire_ids}")
    if set(plume_ids) != {"13.1", "13.2", "14", "15"}:
        raise AcquisitionError(f"R9 August 6 plume identifiers mismatch: {plume_ids}")
    audit = {
        "status": "PASS",
        "header_line_count": header_count,
        "header_bytes": len(header),
        "header_sha256": sha256_bytes(header),
        "field_count": len(observed_fields),
        "fields": list(observed_fields),
        "record_count": len(rows),
        "TIME_START_first": expectations.first_time,
        "TIME_START_last": expectations.last_time,
        "cadence_seconds": 1,
        "continuous": True,
        "scale_factors_all_one": True,
        "sentinels": {"missing": "-9999", "ULOD": "-7777", "LLOD": "-8888"},
        "smoke_record_count": smoke_count,
        "smoke_interval_count": len(smoke_intervals),
        "background_record_count": background_count,
        "background_interval_count": background_intervals,
        "fire_identifiers": fire_ids,
        "plume_identifiers": plume_ids,
        "source_record_identifier": {
            "scheme": "payload-sha256:data-record-ordinal-zero-based",
            "namespace": sha256_bytes(payload),
        },
        "science_transformation_or_join_performed": False,
    }
    return audit, records, smoke_intervals


def _safe_zip_name(name: str) -> None:
    pure = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or pure.is_absolute()
        or any(part in ("", ".", "..") for part in pure.parts)
    ):
        raise AcquisitionError(f"unsafe OOXML member path: {name!r}")


def _xml(payload: bytes, label: str) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as error:
        raise AcquisitionError(f"malformed OOXML XML in {label}: {error}") from error


def _cell_column(reference: str) -> int:
    match = re.fullmatch(r"([A-Z]+)[1-9][0-9]*", reference)
    if not match:
        raise AcquisitionError(f"invalid OOXML cell reference {reference!r}")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _shared_strings(root: ET.Element) -> list[str]:
    return [
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _cell_value(cell: ET.Element, shared: list[str]) -> tuple[str, str]:
    cell_type = cell.get("t")
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    raw = "" if value_node is None or value_node.text is None else value_node.text
    if cell_type == "s":
        try:
            return "shared-string", shared[int(raw)]
        except (ValueError, IndexError) as error:
            raise AcquisitionError(f"invalid shared-string index {raw!r}") from error
    if cell_type == "inlineStr":
        return (
            "inline-string",
            "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t")),
        )
    if cell_type == "str":
        return "string", raw
    if cell_type == "b":
        return "boolean", raw
    if cell_type == "e":
        return "error", raw
    if cell_type in (None, "n"):
        return "numeric", raw
    return f"other:{cell_type}", raw


def audit_r12(
    payload: bytes,
    expectations: WorkbookExpectations = WorkbookExpectations(),
) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as error:
        raise AcquisitionError(f"R12 is not a valid OOXML ZIP: {error}") from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise AcquisitionError("R12 OOXML contains duplicate member names")
        for info in infos:
            _safe_zip_name(info.filename)
            if info.flag_bits & 0x1:
                raise AcquisitionError(f"encrypted OOXML member: {info.filename}")
        if archive.testzip() is not None:
            raise AcquisitionError("R12 OOXML CRC validation failed")
        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > 50_000_000:
            raise AcquisitionError("R12 OOXML uncompressed size exceeds bound")
        lower_names = {name.casefold() for name in names}
        if any(
            "vbaproject" in name
            or name.endswith(".bin")
            or name.startswith("xl/externallinks/")
            for name in lower_names
        ):
            raise AcquisitionError("R12 contains a macro or external-link part")
        required = {
            "[Content_Types].xml",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "xl/worksheets/sheet1.xml",
        }
        missing = required - set(names)
        if missing:
            raise AcquisitionError(f"R12 OOXML is missing parts: {sorted(missing)}")

        external_relationships: list[dict[str, str]] = []
        for name in names:
            if not name.endswith(".rels"):
                continue
            rel_root = _xml(archive.read(name), name)
            for rel in rel_root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
                if rel.get("TargetMode", "").casefold() == "external":
                    external_relationships.append(
                        {
                            "part": name,
                            "type": rel.get("Type", ""),
                            "target": rel.get("Target", ""),
                        }
                    )
        if external_relationships:
            raise AcquisitionError(
                f"R12 contains external relationships: {external_relationships}"
            )

        workbook = _xml(archive.read("xl/workbook.xml"), "xl/workbook.xml")
        sheets = workbook.findall(f".//{{{_MAIN_NS}}}sheet")
        sheet_names = [sheet.get("name", "") for sheet in sheets]
        if sheet_names != [expectations.sheet_name]:
            raise AcquisitionError(f"R12 worksheet names mismatch: {sheet_names}")
        relationship_id = sheets[0].get(f"{{{_OFFICE_REL_NS}}}id")
        rel_root = _xml(
            archive.read("xl/_rels/workbook.xml.rels"),
            "xl/_rels/workbook.xml.rels",
        )
        rel_targets = {
            rel.get("Id"): rel.get("Target", "")
            for rel in rel_root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
        }
        if relationship_id not in rel_targets:
            raise AcquisitionError("R12 worksheet relationship is unresolved")
        sheet_path = posixpath.normpath(
            posixpath.join("xl", rel_targets[relationship_id])
        )
        if sheet_path != "xl/worksheets/sheet1.xml":
            raise AcquisitionError(f"unexpected R12 worksheet part: {sheet_path}")

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared = _shared_strings(
                _xml(archive.read("xl/sharedStrings.xml"), "xl/sharedStrings.xml")
            )
        sheet = _xml(archive.read(sheet_path), sheet_path)
        dimension = sheet.find(f"{{{_MAIN_NS}}}dimension")
        observed_dimension = None if dimension is None else dimension.get("ref")
        if observed_dimension != expectations.dimension:
            raise AcquisitionError(
                f"R12 declared range mismatch: {observed_dimension!r}"
            )
        formulas = sheet.findall(f".//{{{_MAIN_NS}}}f")
        if formulas:
            raise AcquisitionError(f"R12 contains {len(formulas)} formulas")

        parsed_rows: dict[int, dict[int, tuple[str, str]]] = {}
        type_inventory: dict[str, dict[str, int]] = {}
        for row in sheet.findall(f".//{{{_MAIN_NS}}}row"):
            row_number = int(row.get("r", "0"))
            cells: dict[int, tuple[str, str]] = {}
            for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                reference = cell.get("r", "")
                column = _cell_column(reference)
                value_type, lexeme = _cell_value(cell, shared)
                cells[column] = (value_type, lexeme)
                letter = re.match(r"[A-Z]+", reference)
                assert letter is not None
                inventory = type_inventory.setdefault(letter.group(0), {})
                inventory[value_type] = inventory.get(value_type, 0) + 1
            parsed_rows[row_number] = cells

        header_cells = parsed_rows.get(expectations.header_row)
        if header_cells is None:
            raise AcquisitionError("R12 main table header row is absent")
        observed_headers = tuple(
            header_cells.get(column, ("missing", ""))[1]
            for column in range(1, len(R12_HEADERS) + 1)
        )
        if observed_headers != R12_HEADERS:
            raise AcquisitionError(
                f"R12 main table header mismatch: {observed_headers!r}"
            )
        if header_cells.get(32, ("missing", ""))[1] != "":
            raise AcquisitionError("R12 column AF unexpectedly contains a header")

        expected_rows = set(
            range(expectations.first_data_row, expectations.last_data_row + 1)
        )
        present_data_rows = expected_rows & set(parsed_rows)
        if len(present_data_rows) != expectations.data_row_count:
            raise AcquisitionError(
                f"R12 main table row count mismatch: {len(present_data_rows)}"
            )
        for row_number in sorted(present_data_rows):
            cells = parsed_rows[row_number]
            for column, label in ((7, "G"), (14, "N")):
                value_type, lexeme = cells.get(column, ("missing", ""))
                if "string" not in value_type or lexeme != "NaN":
                    raise AcquisitionError(
                        f"R12 {label}{row_number} is not literal string NaN"
                    )

        august_rows: list[dict[str, object]] = []
        lexical_examples: list[dict[str, str]] = []
        for row_number in sorted(present_data_rows):
            cells = parsed_rows[row_number]
            julian = cells.get(19, ("missing", ""))[1]
            if not julian or _decimal(julian, f"R12 S{row_number}") != 218:
                continue
            def value(column: int) -> str:
                return cells.get(column, ("missing", ""))[1]

            fire_raw = value(4)
            plume_raw = value(21)
            transect_raw = value(20)
            item = {
                "worksheet_row": row_number,
                "fire_name": value(3),
                "fire_id_raw": fire_raw,
                "fire_id": canonical_identifier(fire_raw),
                "start_raw": value(5),
                "start": _integer(value(5), f"R12 E{row_number}"),
                "end_raw": value(6),
                "end": _integer(value(6), f"R12 F{row_number}"),
                "transect_type_raw": value(8),
                "transect_number_raw": transect_raw,
                "transect_number": canonical_identifier(transect_raw),
                "plume_id_raw": plume_raw,
                "plume_id": canonical_identifier(plume_raw),
                "mean_wind_age_raw": value(27) or None,
            }
            item["record_count"] = int(item["end"]) - int(item["start"]) + 1
            if int(item["record_count"]) <= 0:
                raise AcquisitionError(f"R12 invalid interval at row {row_number}")
            august_rows.append(item)
            for field, raw, canonical in (
                ("fire_id", fire_raw, str(item["fire_id"])),
                ("transect_number", transect_raw, str(item["transect_number"])),
                ("plume_id", plume_raw, str(item["plume_id"])),
            ):
                if raw != canonical:
                    lexical_examples.append(
                        {
                            "worksheet_cell": (
                                f"D{row_number}"
                                if field == "fire_id"
                                else f"T{row_number}"
                                if field == "transect_number"
                                else f"U{row_number}"
                            ),
                            "field": field,
                            "raw_lexeme": raw,
                            "exact_decimal_canonical": canonical,
                        }
                    )

        expected_august_numbers = list(
            range(expectations.august6_first_row, expectations.august6_last_row + 1)
        )
        if [int(row["worksheet_row"]) for row in august_rows] != expected_august_numbers:
            raise AcquisitionError(
                "R12 Julian-day-218 worksheet rows do not match the frozen range"
            )
        if len(august_rows) != expectations.august6_count:
            raise AcquisitionError(f"R12 August 6 row count mismatch: {len(august_rows)}")
        fire_ids = sorted({str(row["fire_id"]) for row in august_rows})
        if set(fire_ids) != {"10", "10.1", "10.2", "11"}:
            raise AcquisitionError(f"R12 August 6 fire identifiers mismatch: {fire_ids}")
        mapping: dict[str, set[str]] = {}
        for row in august_rows:
            mapping.setdefault(str(row["fire_id"]), set()).add(str(row["fire_name"]))
        if any(len(names_for_id) != 1 for names_for_id in mapping.values()):
            raise AcquisitionError(f"R12 fire-name mapping is not unique: {mapping}")
        if not any(
            item["raw_lexeme"] == "10.199999999999999"
            and item["exact_decimal_canonical"] == "10.2"
            for item in lexical_examples
        ):
            raise AcquisitionError("R12 known 10.2 lexical representation was not proved")

        audit = {
            "status": "PASS",
            "file_type": "OOXML-XLSX",
            "zip_member_count": len(names),
            "zip_total_uncompressed_bytes": total_uncompressed,
            "unsafe_member_count": 0,
            "encrypted_member_count": 0,
            "macro_part_count": 0,
            "external_relationship_count": 0,
            "sheet_names": sheet_names,
            "declared_range": observed_dimension,
            "table_header_row": expectations.header_row,
            "table_headers": list(observed_headers),
            "data_row_first": expectations.first_data_row,
            "data_row_last": expectations.last_data_row,
            "data_row_count": len(present_data_rows),
            "formula_count": 0,
            "column_type_inventory": type_inventory,
            "columns_G_and_N": {
                "status": "PASS",
                "all_main_table_cells_literal_string_NaN": True,
                "use": "PROHIBITED",
            },
            "identifier_contract": {
                "raw_lexemes_preserved": True,
                "binary_float_used": False,
                "normalization": (
                    "exact Decimal; within 1e-12 of a tenth maps to that tenth"
                ),
                "lexical_examples": lexical_examples,
            },
            "August6": {
                "worksheet_rows": [
                    expectations.august6_first_row,
                    expectations.august6_last_row,
                ],
                "row_count": len(august_rows),
                "fire_identifiers": fire_ids,
                "fire_name_mapping": {
                    key: sorted(value) for key, value in sorted(mapping.items())
                },
                "interval_semantics": "inclusive",
                "half_open_equivalent": "[start, end + 1 second)",
                "nearest_fill": False,
                "interpolation": False,
                "rows": august_rows,
            },
            "science_transformation_or_join_performed": False,
        }
        return audit, august_rows


def compare_r9_r12_intervals(
    r9_intervals: list[dict[str, object]],
    r12_rows: list[dict[str, object]],
) -> dict[str, object]:
    keys = (
        "start",
        "end",
        "record_count",
        "fire_id",
        "transect_number",
        "plume_id",
    )
    left = sorted(tuple(item[key] for key in keys) for item in r9_intervals)
    right = sorted(tuple(item[key] for key in keys) for item in r12_rows)
    if left != right:
        differences = [
            {"R9": a, "R12": b}
            for a, b in zip(left, right)
            if a != b
        ]
        raise AcquisitionError(
            f"R9/R12 August 6 interval mapping mismatch: {differences[:5]}"
        )
    return {
        "status": "PASS",
        "interval_count": len(left),
        "comparison_fields": list(keys),
        "interval_semantics": "R9 and R12 inclusive endpoints",
        "source_record_mapping": "[start, end + 1 second), no nearest/interpolation",
        "one_to_one": True,
    }


def _read_icartt_header_from_path(path: Path) -> tuple[list[str], bytes]:
    with path.open("rb") as handle:
        first = handle.readline()
        try:
            count = int(first.decode("latin1").split(",", 1)[0].strip())
        except (UnicodeError, ValueError) as error:
            raise AcquisitionError(f"invalid ICARTT header in {path}") from error
        lines = [first]
        for _ in range(count - 1):
            line = handle.readline()
            if not line:
                raise AcquisitionError(f"truncated ICARTT header in {path}")
            lines.append(line)
    raw = b"".join(lines)
    return raw.decode("latin1").splitlines(), raw


def verify_v1_seal(root: Path = SEALED_V1_ROOT) -> dict[str, object]:
    seal_path = root / "ACQUISITION_SEAL.json"
    manifest_path = root / "tier_f_acquisition_manifest.json"
    if not seal_path.is_file() or not manifest_path.is_file():
        raise AcquisitionError("sealed v1 root is missing its seal or manifest")
    if sha256_file(seal_path) != V1_SEAL_SHA256:
        raise AcquisitionError("sealed v1 root seal SHA-256 mismatch")
    if sha256_file(manifest_path) != V1_MANIFEST_SHA256:
        raise AcquisitionError("sealed v1 acquisition manifest SHA-256 mismatch")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("status") != "SEALED":
        raise AcquisitionError("v1 acquisition seal is not SEALED")
    if seal.get("manifest_sha256") != V1_MANIFEST_SHA256:
        raise AcquisitionError("v1 seal does not pin the expected manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "status": "PASS",
        "root": str(root),
        "seal_sha256": V1_SEAL_SHA256,
        "manifest_sha256": V1_MANIFEST_SHA256,
        "manifest": manifest,
    }


def _v1_record(manifest: Mapping[str, object], filename: str) -> Mapping[str, object]:
    payloads = manifest.get("payloads")
    if not isinstance(payloads, list):
        raise AcquisitionError("v1 manifest payload inventory is malformed")
    matches = [
        item
        for item in payloads
        if isinstance(item, dict) and item.get("archive_filename") == filename
    ]
    if len(matches) != 1:
        raise AcquisitionError(f"v1 manifest record lookup failed for {filename}")
    return matches[0]


def _verify_v1_payload(
    root: Path, manifest: Mapping[str, object], filename: str
) -> tuple[Path, bytes]:
    record = _v1_record(manifest, filename)
    raw_path = root / str(record["raw_relative_path"])
    header_path = root / str(record["header_relative_path"])
    if not raw_path.is_file() or not header_path.is_file():
        raise AcquisitionError(f"v1 sealed payload paths are missing for {filename}")
    if sha256_file(raw_path) != record.get("sha256"):
        raise AcquisitionError(f"v1 raw payload hash mismatch for {filename}")
    header = header_path.read_bytes()
    if sha256_bytes(header) != record.get("header_sha256"):
        raise AcquisitionError(f"v1 header hash mismatch for {filename}")
    return raw_path, header


def _sentinel_kind(value: str, direct: bool) -> str | None:
    mapping = (
        {
            Decimal("-9999"): "missing",
            Decimal("-7777"): "ULOD",
            Decimal("-8888"): "LLOD",
        }
        if direct
        else {
            Decimal("-999999"): "missing",
            Decimal("-777777"): "ULOD",
            Decimal("-888888"): "LLOD",
        }
    )
    try:
        normalized = Decimal(value.strip())
    except InvalidOperation:
        return None
    return mapping.get(normalized)


def _equivalent_value(direct_value: str, merge_value: str) -> str | None:
    direct_sentinel = _sentinel_kind(direct_value, True)
    merge_sentinel = _sentinel_kind(merge_value, False)
    if direct_sentinel or merge_sentinel:
        return "declared-sentinel-translation" if direct_sentinel == merge_sentinel else None
    try:
        if Decimal(direct_value.strip()) == Decimal(merge_value.strip()):
            return (
                "lexically-exact"
                if direct_value.strip() == merge_value.strip()
                else "exact-decimal-formatting"
            )
    except InvalidOperation:
        if direct_value.strip() == merge_value.strip():
            return "lexically-exact"
    return None


_MRG01_SERIALIZATION_FIELDS = {
    "transect_smoke_mce",
    "transect_mce_odr",
    "transect_mce_odr_chisq",
}
_LEXICAL_IDENTIFIER_FIELDS = {
    "fire_id",
    "transect_number",
    "transect_plume_number",
}
_EXPECTED_DECIMAL_UNEQUAL_COUNTS = {
    "transect_smoke_mce": 4166,
    "transect_mce_ODR": 4813,
    "transect_mce_ODR_chisq": 2083,
}


def _serialize_mrg01_continuous(
    field: str, source_token: str
) -> tuple[str, str]:
    """Reproduce the merge's audited binary64 fixed-point serialization."""
    if sys.float_info.radix != 2 or sys.float_info.mant_dig != 53:
        raise AcquisitionError("runtime float is not IEEE-754 binary64")
    try:
        value = float(source_token)
    except ValueError as error:
        raise AcquisitionError(
            f"{field} cannot be parsed as IEEE-754 binary64: {source_token!r}"
        ) from error
    if not math.isfinite(value):
        raise AcquisitionError(f"{field} binary64 value is non-finite")
    folded = field.casefold()
    if folded in {"transect_smoke_mce", "transect_mce_odr"}:
        places = 5
        specification = ".5f"
    elif folded == "transect_mce_odr_chisq":
        magnitude = abs(value)
        if magnitude < 0.1:
            places = 6
        elif magnitude < 10:
            places = 5
        elif magnitude < 100:
            places = 4
        else:
            raise AcquisitionError(
                "transect_mce_ODR_chisq is outside the audited format bands"
            )
        specification = f".{places}f by |x| band"
    else:
        raise AcquisitionError(f"no mrg01 serialization rule for {field}")
    return format(value, f".{places}f"), specification


def audit_r9_mrg01_mirrors(
    r9_records: Mapping[int, tuple[str, ...]],
    *,
    v1_root: Path,
    v1_manifest: Mapping[str, object],
) -> dict[str, object]:
    filename = "FIREXAQ-mrg01-DC8_merge_20190806_R3.ict"
    raw_path, header = _verify_v1_payload(v1_root, v1_manifest, filename)
    header_lines = header.decode("latin1").splitlines()
    merge_fields = tuple(
        value.strip() for value in next(csv.reader([header_lines[-1]]))
    )
    merge_index = {name.casefold(): index for index, name in enumerate(merge_fields)}
    missing_fields = [
        field for field in MIRROR_FIELDS if field.casefold() not in merge_index
    ]
    if missing_fields:
        raise AcquisitionError(f"mrg01 is missing R9 mirror fields: {missing_fields}")
    direct_index = {name.casefold(): index for index, name in enumerate(R9_FIELDS)}
    comparison_counts = {
        field: {
            "lexically-exact": 0,
            "exact-decimal-formatting": 0,
            "declared-sentinel-translation": 0,
            "decimal-unequal-exactly-reproduced": 0,
        }
        for field in MIRROR_FIELDS
    }
    serialization_audit = {
        field: {
            "format_specifications": set(),
            "finite_pair_count": 0,
            "exact_reproduced_token_count": 0,
            "decimal_unequal_count": 0,
            "maximum_absolute_decimal_difference": Decimal(0),
            "exceptions": 0,
        }
        for field in MIRROR_FIELDS
        if field.casefold() in _MRG01_SERIALIZATION_FIELDS
    }
    observed_times: set[int] = set()
    carrier_times: list[int] = []
    carrier_time_set: set[int] = set()
    carrier_stop_times: list[int] = []
    mismatches: list[dict[str, object]] = []
    with raw_path.open("r", encoding="latin1", newline="") as handle:
        header_count = int(handle.readline().split(",", 1)[0].strip())
        for _ in range(header_count - 1):
            next(handle)
        reader = csv.reader(handle, skipinitialspace=True)
        for row in reader:
            if not row or not any(value.strip() for value in row):
                continue
            time = _integer(row[0], "mrg01 Time_Start")
            stop = _integer(row[merge_index["time_stop"]], "mrg01 Time_Stop")
            if time in carrier_time_set:
                raise AcquisitionError(f"duplicate mrg01 Time_Start {time}")
            if stop != time + 1:
                raise AcquisitionError(
                    f"mrg01 Time_Stop is not Time_Start + 1 at {time}"
                )
            carrier_times.append(time)
            carrier_time_set.add(time)
            carrier_stop_times.append(stop)
            direct_row = r9_records.get(time)
            if direct_row is None:
                continue
            observed_times.add(time)
            for field in MIRROR_FIELDS:
                direct_value = direct_row[direct_index[field.casefold()]]
                merge_value = row[merge_index[field.casefold()]]
                explanation = _equivalent_value(direct_value, merge_value)
                direct_sentinel = _sentinel_kind(direct_value, True)
                merge_sentinel = _sentinel_kind(merge_value, False)
                if direct_sentinel or merge_sentinel:
                    if direct_sentinel == merge_sentinel:
                        comparison_counts[field][
                            "declared-sentinel-translation"
                        ] += 1
                        continue
                    if len(mismatches) < 20:
                        mismatches.append(
                            {
                                "TIME_START": time,
                                "field": field,
                                "R9": direct_value.strip(),
                                "mrg01": merge_value.strip(),
                            }
                        )
                    continue

                if field.casefold() in _MRG01_SERIALIZATION_FIELDS:
                    serialized, specification = _serialize_mrg01_continuous(
                        field, direct_value.strip()
                    )
                    field_audit = serialization_audit[field]
                    field_audit["format_specifications"].add(specification)
                    field_audit["finite_pair_count"] += 1
                    if serialized != merge_value.strip():
                        field_audit["exceptions"] += 1
                        if len(mismatches) < 20:
                            mismatches.append(
                                {
                                    "TIME_START": time,
                                    "field": field,
                                    "R9": direct_value.strip(),
                                    "mrg01": merge_value.strip(),
                                    "serialized_R9": serialized,
                                }
                            )
                        continue
                    field_audit["exact_reproduced_token_count"] += 1
                    if explanation is None:
                        comparison_counts[field][
                            "decimal-unequal-exactly-reproduced"
                        ] += 1
                        field_audit["decimal_unequal_count"] += 1
                        difference = abs(
                            Decimal(direct_value.strip())
                            - Decimal(merge_value.strip())
                        )
                        field_audit["maximum_absolute_decimal_difference"] = max(
                            field_audit["maximum_absolute_decimal_difference"],
                            difference,
                        )
                    else:
                        comparison_counts[field][explanation] += 1
                    continue

                if field.casefold() in _LEXICAL_IDENTIFIER_FIELDS:
                    try:
                        identifiers_equal = (
                            canonical_identifier(direct_value)
                            == canonical_identifier(merge_value)
                        )
                    except AcquisitionError:
                        identifiers_equal = False
                    if not identifiers_equal:
                        explanation = None
                if explanation is not None:
                    comparison_counts[field][explanation] += 1
                    continue
                if len(mismatches) < 20:
                    mismatches.append(
                        {
                            "TIME_START": time,
                            "field": field,
                            "R9": direct_value.strip(),
                            "mrg01": merge_value.strip(),
                        }
                    )

    if not carrier_times:
        raise AcquisitionError("mrg01 carrier has no data records")
    if carrier_times != list(range(carrier_times[0], carrier_times[-1] + 1)):
        raise AcquisitionError("mrg01 Time_Start contains an interior gap or reordering")
    r9_time_set = set(r9_records)
    r9_only_times = sorted(r9_time_set - carrier_time_set)
    mrg01_only_times = sorted(carrier_time_set - r9_time_set)
    expected_terminal = carrier_times[-1] + 1
    if (
        mrg01_only_times
        or r9_only_times != [expected_terminal]
        or expected_terminal != max(r9_time_set)
        or carrier_times[0] != min(r9_time_set)
        or carrier_stop_times[-1] != expected_terminal
    ):
        raise AcquisitionError(
            "R9/mrg01 time coverage is not the expected terminal-boundary "
            f"relation: R9-only={r9_only_times}, mrg01-only={mrg01_only_times}"
        )
    terminal_row = r9_records[expected_terminal]
    if any(
        _sentinel_kind(terminal_row[direct_index[field.casefold()]], True)
        != "missing"
        for field in MIRROR_FIELDS
    ):
        raise AcquisitionError(
            "R9-only terminal record is not all declared missing sentinels"
        )
    if observed_times != carrier_time_set:
        raise AcquisitionError("not every mrg01 carrier time has an exact R9 record")
    if mismatches:
        raise AcquisitionError(
            f"R9/mrg01 mirror audit has unexplained exceptions: {mismatches}"
        )
    for field, counts in comparison_counts.items():
        if sum(counts.values()) != len(carrier_times):
            raise AcquisitionError(f"incomplete mirror comparison for {field}")
    for field, expected_count in _EXPECTED_DECIMAL_UNEQUAL_COUNTS.items():
        observed_count = comparison_counts[field][
            "decimal-unequal-exactly-reproduced"
        ]
        if observed_count != expected_count:
            raise AcquisitionError(
                f"{field} unexplained-count ledger changed: "
                f"expected {expected_count}, got {observed_count}"
            )
    rendered_serialization_audit: dict[str, object] = {}
    for field, values in serialization_audit.items():
        if (
            values["finite_pair_count"] != 5253
            or values["exact_reproduced_token_count"] != 5253
            or values["exceptions"] != 0
        ):
            raise AcquisitionError(f"incomplete mrg01 serialization proof for {field}")
        rendered_serialization_audit[field] = {
            **values,
            "format_specifications": sorted(values["format_specifications"]),
            "maximum_absolute_decimal_difference": format(
                values["maximum_absolute_decimal_difference"], "f"
            ),
        }
    return {
        "status": "PASS",
        "authority_subgate": "PASS",
        "carrier": str(raw_path),
        "carrier_sha256": _v1_record(v1_manifest, filename)["sha256"],
        "matched_one_second_times": len(observed_times),
        "first_TIME_START": min(observed_times),
        "last_TIME_START": max(observed_times),
        "overlap_fields": list(MIRROR_FIELDS),
        "overlap_pair_count": len(observed_times) * len(MIRROR_FIELDS),
        "comparison_counts_by_field": comparison_counts,
        "continuous_mirror": {
            "status": (
                "PASS_WITH_EXPLAINED_IEEE754_FIXED_FORMAT_SERIALIZATION"
            ),
            "algorithm": (
                "decimal source token -> IEEE-754 binary64 "
                "(round-to-nearest, ties-to-even) -> field-specific fixed format"
            ),
            "runtime_binary64": {
                "radix": sys.float_info.radix,
                "mantissa_bits": sys.float_info.mant_dig,
            },
            "field_specific_format_rules": {
                "transect_smoke_mce": ".5f",
                "transect_mce_odr": ".5f",
                "transect_mce_odr_chisq": [
                    {"absolute_value_range": "[0, 0.1)", "format": ".6f"},
                    {"absolute_value_range": "[0.1, 10)", "format": ".5f"},
                    {"absolute_value_range": "[10, 100)", "format": ".4f"},
                ],
            },
            "scope": sorted(_MRG01_SERIALIZATION_FIELDS),
            "fields": rendered_serialization_audit,
            "exact_reproducer_exception_count": 0,
            "R9_values_remain_authoritative": True,
            "mrg01_values_role": "protected-QA-mirrors-only",
        },
        "time_coverage": {
            "status": "PASS_WITH_EXPECTED_TERMINAL_SENTINEL_RECORD",
            "mrg01_Time_Start_first": carrier_times[0],
            "mrg01_Time_Start_last": carrier_times[-1],
            "mrg01_final_Time_Stop": carrier_stop_times[-1],
            "mrg01_half_open_domain": (
                f"[{carrier_times[0]}, {carrier_stop_times[-1]})"
            ),
            "R9_only_times": r9_only_times,
            "mrg01_only_times": mrg01_only_times,
            "R9_only_terminal_all_14_missing": True,
            "interior_gap_count": 0,
            "duplicate_count": 0,
            "clock_offset_evidence": "none",
            "nearest_fill_interpolation_or_row_synthesis": False,
        },
        "unexplained_mismatch_count": 0,
        "explanations": {
            "exact-decimal-formatting": (
                "numeric tokens are identical after exact Decimal normalization; "
                "identifiers never use binary floating point"
            ),
            "declared-sentinel-translation": (
                "direct -9999/-7777/-8888 maps to merge "
                "-999999/-777777/-888888"
            ),
            "decimal-unequal-exactly-reproduced": (
                "continuous MCE token is reproduced exactly by the frozen "
                "binary64 field-specific fixed-format rule"
            ),
        },
        "join_published": False,
    }


_PDF_OBJECT_START = re.compile(rb"(?m)(?<!\S)\d+\s+\d+\s+obj\b")
_PDF_PAGE_TYPE = re.compile(rb"/Type\s*/Page\b")
_PDF_OBJECT_STREAM_TYPE = re.compile(rb"/Type\s*/ObjStm\b")


def _skip_pdf_whitespace(payload: bytes, offset: int) -> int:
    while offset < len(payload) and payload[offset] in b"\x00\t\n\x0c\r ":
        offset += 1
    return offset


def _pdf_dictionary_end(payload: bytes, offset: int) -> int:
    """Return the end of one balanced PDF dictionary beginning at ``<<``."""
    if payload[offset:offset + 2] != b"<<":
        raise AcquisitionError("PDF dictionary parser was called off-boundary")
    depth = 0
    index = offset
    limit = min(len(payload), offset + 1_000_000)
    while index < limit:
        pair = payload[index:index + 2]
        if pair == b"<<":
            depth += 1
            index += 2
            continue
        if pair == b">>":
            depth -= 1
            index += 2
            if depth == 0:
                return index
            if depth < 0:
                break
            continue
        if payload[index:index + 1] == b"%":
            newline = payload.find(b"\n", index + 1, limit)
            index = limit if newline < 0 else newline + 1
            continue
        if payload[index:index + 1] == b"(":
            string_depth = 1
            index += 1
            while index < limit and string_depth:
                character = payload[index:index + 1]
                if character == b"\\":
                    index += 2
                    continue
                if character == b"(":
                    string_depth += 1
                elif character == b")":
                    string_depth -= 1
                index += 1
            if string_depth:
                raise AcquisitionError("unterminated PDF literal string")
            continue
        index += 1
    raise AcquisitionError("unterminated or overlarge PDF dictionary")


def _direct_pdf_objects(
    payload: bytes,
) -> Iterable[tuple[bytes, bytes | None]]:
    """Yield direct-object dictionaries and exact stream bytes, skipping bodies."""
    cursor = 0
    while True:
        match = _PDF_OBJECT_START.search(payload, cursor)
        if match is None:
            return
        body_start = _skip_pdf_whitespace(payload, match.end())
        if payload[body_start:body_start + 2] != b"<<":
            end_object = payload.find(b"endobj", body_start)
            if end_object < 0:
                raise AcquisitionError("PDF indirect object has no endobj marker")
            cursor = end_object + len(b"endobj")
            continue
        dictionary_end = _pdf_dictionary_end(payload, body_start)
        dictionary = payload[body_start:dictionary_end]
        stream_keyword = _skip_pdf_whitespace(payload, dictionary_end)
        stream_payload: bytes | None = None
        after_object_content = dictionary_end
        if (
            payload[stream_keyword:stream_keyword + len(b"stream")] == b"stream"
            and payload[
                stream_keyword + len(b"stream"):
                stream_keyword + len(b"stream") + 1
            ] in (b"\r", b"\n")
        ):
            stream_start = stream_keyword + len(b"stream")
            if payload[stream_start:stream_start + 2] == b"\r\n":
                stream_start += 2
            else:
                stream_start += 1
            length_match = re.search(rb"/Length\s+([0-9]+)\b", dictionary)
            if length_match is not None:
                stream_end = stream_start + int(length_match.group(1))
                if stream_end > len(payload):
                    raise AcquisitionError("PDF stream length exceeds file bounds")
                marker = _skip_pdf_whitespace(payload, stream_end)
                if payload[marker:marker + len(b"endstream")] != b"endstream":
                    raise AcquisitionError("PDF direct stream length is inconsistent")
            else:
                marker = payload.find(b"endstream", stream_start)
                if marker < 0:
                    raise AcquisitionError("PDF stream has no endstream marker")
                stream_end = marker
                while (
                    stream_end > stream_start
                    and payload[stream_end - 1:stream_end] in (b"\r", b"\n")
                ):
                    stream_end -= 1
            stream_payload = payload[stream_start:stream_end]
            after_object_content = marker + len(b"endstream")
        end_object = payload.find(b"endobj", after_object_content)
        if end_object < 0:
            raise AcquisitionError("PDF dictionary object has no endobj marker")
        yield dictionary, stream_payload
        cursor = end_object + len(b"endobj")


def _bounded_flate_decode(payload: bytes, maximum_output: int) -> bytes:
    if maximum_output < 0:
        raise AcquisitionError("PDF object-stream expansion exceeds bound")
    decompressor = zlib.decompressobj()
    try:
        decoded = decompressor.decompress(payload, maximum_output + 1)
    except zlib.error as error:
        raise AcquisitionError(
            f"could not decompress PDF object stream: {error}"
        ) from error
    if len(decoded) > maximum_output or decompressor.unconsumed_tail:
        raise AcquisitionError("PDF object-stream expansion exceeds bound")
    if not decompressor.eof:
        raise AcquisitionError("PDF object stream is truncated or invalid")
    try:
        tail = decompressor.flush(maximum_output - len(decoded) + 1)
    except zlib.error as error:
        raise AcquisitionError(
            f"could not finish PDF object-stream decompression: {error}"
        ) from error
    decoded += tail
    if len(decoded) > maximum_output:
        raise AcquisitionError("PDF object-stream expansion exceeds bound")
    return decoded


def _pdf_page_count(
    payload: bytes,
    *,
    maximum_object_stream_bytes: int = 100_000_000,
) -> tuple[int, int, int]:
    """Count page dictionaries in direct objects and PDF object streams.

    PDF 1.5 permits page dictionaries to live inside ``/ObjStm`` streams.
    Direct object dictionaries are parsed sequentially, and stream bodies are
    skipped. Only Flate-compressed object streams are expanded, with a true
    cumulative output bound; content and image streams are never searched.
    """
    direct_pages = 0
    compressed_pages = 0
    object_streams = 0
    total_decompressed = 0
    for dictionary, stream_payload in _direct_pdf_objects(payload):
        if _PDF_PAGE_TYPE.search(dictionary) is not None:
            direct_pages += 1
        if _PDF_OBJECT_STREAM_TYPE.search(dictionary) is None:
            continue
        object_streams += 1
        if stream_payload is None:
            raise AcquisitionError("PDF object stream has no stream body")
        if b"/FlateDecode" not in dictionary:
            raise AcquisitionError("PDF object stream uses an unsupported filter")
        remaining = maximum_object_stream_bytes - total_decompressed
        decoded = _bounded_flate_decode(stream_payload, remaining)
        total_decompressed += len(decoded)
        compressed_pages += len(_PDF_PAGE_TYPE.findall(decoded))
    return direct_pages + compressed_pages, direct_pages, object_streams


def audit_pdf(payload: bytes, target: PdfTarget) -> dict[str, object]:
    _validate_pin(payload, target.expected_bytes, target.expected_sha256)
    if not payload.startswith(b"%PDF-") or b"%%EOF" not in payload[-4096:]:
        raise AcquisitionError(f"{target.filename} is not a complete PDF")
    pages, direct_page_objects, object_stream_count = _pdf_page_count(payload)
    if pages != target.expected_pages:
        raise AcquisitionError(
            f"{target.filename} page count mismatch: {pages} "
            f"(expected {target.expected_pages})"
        )
    return {
        "key": target.key,
        "filename": target.filename,
        "url": target.url,
        "title": target.title,
        "doi": target.doi,
        "publication_state": target.publication_state,
        "identity_date": target.identity_date,
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "PDF_magic": "PASS",
        "EOF_marker": "PASS",
        "page_count": pages,
        "direct_page_dictionary_count": direct_page_objects,
        "parsed_object_stream_count": object_stream_count,
        "identity_basis": (
            "exact URL, byte count, SHA-256, PDF structure, official landing page, "
            "and independently reviewed pinned-document semantics"
        ),
    }


def audit_semantic_authorities(
    *,
    v1_root: Path,
    v1_manifest: Mapping[str, object],
    pdf_audits: Mapping[str, Mapping[str, object]],
    page_records: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    fsu_filename = "firexaq-FSU-smokeage_dc8_20190806_R1.ict"
    _, fsu_header = _verify_v1_payload(v1_root, v1_manifest, fsu_filename)
    fsu_text = fsu_header.decode("latin1")
    required_fsu = (
        "smoke_age, s, none, age of smoke at time of aircraft measurement",
        "smoke_age_unc, s, none, uncertainty in age of smoke",
        "smoke_age_corr, s, none, age of smoke at time of aircraft measurement "
        "with correction to match observed wind speed",
        "UNCERTAINTY: Reported uncertainties reflect the range of ages derived "
        "from three meteorological datasets",
        'OTHER_COMMENTS: Key to "smoke_agemethod"',
    )
    missing_fsu = [marker for marker in required_fsu if marker not in fsu_text]
    if missing_fsu:
        raise AcquisitionError(f"FSU semantic header markers missing: {missing_fsu}")
    method_match = re.search(
        r'Key to "smoke_agemethod".*?:\s*'
        r"1=HRRR,NAM,GFS \(default\); 2=HRRR,NAM; 3=HRRR,GFS; "
        r"4=NAM,GFS; 5=HRRR; 6=NAM; 7=GFS",
        fsu_text,
    )
    if method_match is None:
        raise AcquisitionError("FSU method codes 1 through 7 were not proved")

    aop_filename = "firexaq-AOP-optical_DC8_20190806_R2.ict"
    _, aop_header = _verify_v1_payload(v1_root, v1_manifest, aop_filename)
    aop_text = aop_header.decode("latin1")
    for marker in (
        "abs_dry_664",
        "abs_dry_532",
        "abs_dry_405",
        "PM2.5_STP",
        "high signal accuracy of 20%",
        "low signal precision varies with altitude and flight to flight",
        "AOP_Dilution_ratio",
    ):
        if marker not in aop_text:
            raise AcquisitionError(f"AOP semantic header marker missing: {marker}")

    if pdf_audits["Holmes_original_discussion_PDF"]["sha256"] != PDF_TARGETS[0].expected_sha256:
        raise AcquisitionError("Holmes semantic audit is not tied to the frozen PDF")
    if pdf_audits["Zeng_final_PDF"]["sha256"] != PDF_TARGETS[1].expected_sha256:
        raise AcquisitionError("Zeng semantic audit is not tied to the frozen PDF")
    for key in ("Holmes_landing", "Zeng_landing"):
        if page_records[key]["marker_status"] != "PASS":
            raise AcquisitionError(f"official semantic landing-page marker failed: {key}")

    return {
        "status": "PASS",
        "FSU_to_Holmes": {
            "status": "PASS",
            "FSU_product": fsu_filename,
            "FSU_payload_sha256": _v1_record(v1_manifest, fsu_filename)["sha256"],
            "Holmes_PDF_sha256": PDF_TARGETS[0].expected_sha256,
            "archived_field": "smoke_agemethod",
            "paper_field": "smoke_age_method",
            "spelling_difference_explicit": True,
            "code_values": [1, 2, 3, 4, 5, 6, 7],
            "FSU_abbreviated_range_wording": (
                "range of ages derived from three meteorological datasets"
            ),
            "crosswalk_interpretation": (
                "exact pinned Holmes document supplies trajectory ensemble, "
                "method, and combined uncertainty semantics; FSU supplies values"
            ),
            "nominal_field": "smoke_age",
            "corrected_field": "smoke_age_corr",
            "corrected_is_sensitivity_not_fallback": True,
            "uncertainty_use": (
                "deterministic closed untruncated boundary envelope only; "
                "not Gaussian, CI, probability, coverage, or weight"
            ),
        },
        "AOP_to_Zeng": {
            "status": "PASS",
            "AOP_product": aop_filename,
            "AOP_payload_sha256": _v1_record(v1_manifest, aop_filename)["sha256"],
            "Zeng_PDF_sha256": PDF_TARGETS[1].expected_sha256,
            "same_family": "high-resolution dry PM2.5 PAS",
            "wavelengths_nm": [405, 532, 664],
            "temperature_K": 273.0,
            "pressure_mbar": 1013.0,
            "AOP_R2_retains_value_flag_wording_authority": True,
            "Zeng_role": "dataset-level numeric standard state only",
            "per_record_low_signal_precision_inferred": False,
        },
        "collision_checks": {
            "R9_transect_smoke_age_vs_FSU_smoke_age": "NO_COLLISION",
            "R9_fire_distance_estimate_vs_FSU_fire_distance": "NO_COLLISION",
            "AOP_Dilution_ratio_vs_SP2_BC_Dilution_Flag": "NO_COLLISION",
            "R9_mean_wind_fields_role": "context-only",
            "FSU_trajectory_fields_role": "values-only",
            "AOP_dilution_used_as_SP2_magnitude": False,
        },
        "replacement_values_created": False,
        "science_join_created": False,
    }


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


def _publish_noreplace(staging: Path, destination: Path, seal_payload: bytes) -> None:
    nonce = secrets.token_hex(16)
    owner_path = destination / ".authority_acquisition_owner"
    seal_path = destination / AUTHORITY_SEAL
    temporary_seal = destination / f".{AUTHORITY_SEAL}.{nonce}.partial"
    destination_created = False

    def committed() -> bool:
        try:
            metadata = seal_path.lstat()
            return stat.S_ISREG(metadata.st_mode) and seal_path.read_bytes() == seal_payload
        except OSError:
            return False

    def cleanup_metadata() -> None:
        for path in (temporary_seal, owner_path):
            try:
                path.unlink()
            except OSError:
                pass

    try:
        destination.mkdir()
        destination_created = True
        _write_new(owner_path, (nonce + "\n").encode("ascii"))
        for entry in sorted(
            staging.iterdir(),
            key=lambda item: (item.name == MANIFEST_NAME, item.name),
        ):
            target = destination / entry.name
            if target.exists():
                raise FileExistsError(f"publication target appeared: {target}")
            entry.rename(target)
        staging.rmdir()
        _fsync_directory(destination)
        _write_new(temporary_seal, seal_payload)
        os.link(temporary_seal, seal_path)
        cleanup_metadata()
        try:
            _fsync_directory(destination)
            _fsync_directory(destination.parent)
        except OSError:
            pass
    except BaseException:
        if destination_created and committed():
            cleanup_metadata()
            return
        if destination_created:
            try:
                owned = owner_path.read_text(encoding="ascii").strip() == nonce
            except OSError:
                owned = False
            if owned:
                shutil.rmtree(destination)
        raise


def _page_record(
    target: PageTarget,
    response: FetchResult,
    retrieved_utc: str,
) -> dict[str, object]:
    decoded = response.payload.decode("latin1").casefold()
    missing = [marker for marker in target.required_markers if marker.casefold() not in decoded]
    if missing:
        raise AcquisitionError(f"{target.key} is missing markers: {missing}")
    return {
        "key": target.key,
        "requested_url": target.url,
        "http_final_url": response.final_url,
        "http_status": response.http_status,
        "retrieved_utc": retrieved_utc,
        "bytes": len(response.payload),
        "sha256": sha256_bytes(response.payload),
        "relative_path": target.relative_path,
        "marker_status": "PASS",
        "required_markers": list(target.required_markers),
    }


def acquire(
    destination: Path,
    *,
    contract_path: Path,
    expected_contract_sha256: str,
    expected_source_sha256: str,
    expected_test_sha256: str,
    focused_tests_verdict: str,
    independent_code_audit_verdict: str,
    independent_code_auditor: str,
    fetcher: Callable[[str], bytes | FetchResult] = fetch_resource,
    clock: Callable[[], str] = _utc_now,
    expected_destination: Path = DESTINATION,
    expected_contract_path: Path = CONTRACT_PATH,
    v1_root: Path = SEALED_V1_ROOT,
    enforce_runtime: bool = True,
) -> dict[str, object]:
    destination = destination.resolve()
    contract_path = contract_path.resolve()
    if destination != expected_destination.resolve():
        raise AcquisitionError(
            f"destination differs from frozen contract: {destination}"
        )
    if contract_path != expected_contract_path.resolve():
        raise AcquisitionError(
            f"contract path differs from frozen contract: {contract_path}"
        )
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite acquisition {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(
            f"acquisition parent must already exist: {destination.parent}"
        )
    if not contract_path.is_file():
        raise FileNotFoundError(f"acquisition contract does not exist: {contract_path}")
    contract_bytes = contract_path.read_bytes()
    contract_hash = sha256_bytes(contract_bytes)
    if contract_hash != expected_contract_sha256:
        raise AcquisitionError(
            f"contract SHA-256 mismatch: expected {expected_contract_sha256}, "
            f"got {contract_hash}"
        )
    if expected_contract_sha256 != CONTRACT_SHA256 and expected_contract_path == CONTRACT_PATH:
        raise AcquisitionError("caller did not supply the compiled frozen contract hash")
    if focused_tests_verdict != "PASS" or independent_code_audit_verdict != "PASS":
        raise AcquisitionError("focused tests and independent code audit must both PASS")
    if not independent_code_auditor.strip():
        raise AcquisitionError("independent code auditor identity is required")
    tool_path = Path(__file__).resolve()
    test_path = tool_path.with_name("test_fetch_firex_aq_tier_f_authorities.py")
    if sha256_file(tool_path) != expected_source_sha256:
        raise AcquisitionError("source SHA-256 differs from pre-acquisition evidence")
    if not test_path.is_file() or sha256_file(test_path) != expected_test_sha256:
        raise AcquisitionError("test SHA-256 differs from pre-acquisition evidence")
    if enforce_runtime:
        if Path(sys.executable).resolve() != FROZEN_PYTHON.resolve():
            raise AcquisitionError(f"wrong Python runtime: {sys.executable}")
        if sys.version_info[:3] != (3, 11, 6):
            raise AcquisitionError(f"wrong Python version: {sys.version}")

    v1 = verify_v1_seal(v1_root)
    v1_manifest = v1.pop("manifest")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            suffix=".partial",
            dir=destination.parent,
        )
    )
    try:
        _write_new(staging / "acquisition_contract.yml", contract_bytes)
        page_payloads: dict[str, bytes] = {}
        page_records: dict[str, dict[str, object]] = {}
        for target in PAGES:
            response = _normalize_response(
                fetcher(target.url), target.url, exact_final_url=True
            )
            if response.http_status is None:
                raise AcquisitionError(f"formal HTTP status absent for {target.key}")
            retrieved = clock()
            page_payloads[target.key] = response.payload
            page_records[target.key] = _page_record(target, response, retrieved)
            _write_new(staging / target.relative_path, response.payload)

        nasa_urls = discover_nasa_urls(page_payloads)
        nasa_records: dict[str, dict[str, object]] = {}
        raw_payloads: dict[str, bytes] = {}
        for target in NASA_TARGETS:
            href, url = nasa_urls[target.key]
            response = _normalize_response(fetcher(url), url, exact_final_url=True)
            if response.http_status is None:
                raise AcquisitionError(f"formal HTTP status absent for {target.key}")
            served = _served_filename(response, target.filename)
            _validate_pin(response.payload, target.expected_bytes, target.expected_sha256)
            retrieved = clock()
            raw_payloads[target.key] = response.payload
            _write_new(staging / target.relative_path, response.payload)
            nasa_records[target.key] = {
                "key": target.key,
                "filename": target.filename,
                "revision": target.revision,
                "archive_page_key": target.page_key,
                "archive_page_sha256": page_records[target.page_key]["sha256"],
                "archive_href": href,
                "requested_url": url,
                "http_final_url": response.final_url,
                "http_status": response.http_status,
                "content_disposition": response.headers.get("content-disposition"),
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "served_filename": served,
                "retrieved_utc": retrieved,
                "bytes": len(response.payload),
                "sha256": sha256_bytes(response.payload),
                "relative_path": target.relative_path,
            }

        pdf_records: dict[str, dict[str, object]] = {}
        pdf_audits: dict[str, dict[str, object]] = {}
        for target in PDF_TARGETS:
            response = _normalize_response(
                fetcher(target.url), target.url, exact_final_url=True
            )
            if response.http_status is None:
                raise AcquisitionError(f"formal HTTP status absent for {target.key}")
            audit = audit_pdf(response.payload, target)
            last_modified = response.headers.get("last-modified")
            if (
                target.expected_last_modified is not None
                and last_modified != target.expected_last_modified
            ):
                raise AcquisitionError(
                    f"{target.filename} Last-Modified mismatch: {last_modified!r}"
                )
            retrieved = clock()
            _write_new(staging / target.relative_path, response.payload)
            pdf_audits[target.key] = audit
            pdf_records[target.key] = {
                **audit,
                "requested_url": target.url,
                "http_final_url": response.final_url,
                "http_status": response.http_status,
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "last_modified": last_modified,
                "etag": response.headers.get("etag"),
                "retrieved_utc": retrieved,
                "relative_path": target.relative_path,
            }

        r9_audit, r9_records, r9_intervals = audit_r9(
            raw_payloads["fire_flags_R9"]
        )
        r9_header, _, _ = extract_icartt_header(raw_payloads["fire_flags_R9"])
        _write_new(
            staging
            / "headers/firexaq-fire-Flags-1HZ_DC8_20190806_R9.ict.header",
            r9_header,
        )
        r12_audit, r12_rows = audit_r12(raw_payloads["fire_glossary_R12"])
        interval_audit = compare_r9_r12_intervals(r9_intervals, r12_rows)
        mirror_audit = audit_r9_mrg01_mirrors(
            r9_records,
            v1_root=v1_root,
            v1_manifest=v1_manifest,
        )
        semantic_audit = audit_semantic_authorities(
            v1_root=v1_root,
            v1_manifest=v1_manifest,
            pdf_audits=pdf_audits,
            page_records=page_records,
        )
        semantic_audit["R9_structure"] = r9_audit
        semantic_audit["R9_to_R12"] = interval_audit
        semantic_audit["R9_to_mrg01"] = mirror_audit

        rendered_r12 = (
            json.dumps(r12_audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        rendered_pdf = (
            json.dumps(pdf_audits, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        rendered_semantic = (
            json.dumps(semantic_audit, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        _write_new(staging / "audits/r12_ooxml_audit.json", rendered_r12)
        _write_new(staging / "audits/pdf_identity_audit.json", rendered_pdf)
        _write_new(staging / "audits/authority_semantic_audit.json", rendered_semantic)

        manifest: dict[str, object] = {
            "schema_version": 2,
            "manifest_id": (
                "stage1-firex-aq-tier-f-authority-acquisition-20190806-v2"
            ),
            "status": "byte-schema-and-semantic-evidence-sealed-independent-audit-pending",
            "campaign": "FIREX-AQ",
            "platform": "DC-8",
            "flight_date": "2019-08-06",
            "created_utc": clock(),
            "contract": {
                "source_path": str(contract_path),
                "sha256": contract_hash,
                "snapshot_relative_path": "acquisition_contract.yml",
            },
            "tooling": {
                "source_path": str(tool_path),
                "source_sha256": expected_source_sha256,
                "test_path": str(test_path),
                "test_sha256": expected_test_sha256,
                "focused_tests_verdict": focused_tests_verdict,
                "independent_code_audit_verdict": independent_code_audit_verdict,
                "independent_code_auditor": independent_code_auditor,
            },
            "runtime": {
                "python_executable": sys.executable,
                "python_version": sys.version,
                "dependency_scope": "Python-standard-library-only",
            },
            "sealed_v1_dependency": v1,
            "official_pages": [page_records[target.key] for target in PAGES],
            "payloads": [
                nasa_records[target.key] for target in NASA_TARGETS
            ]
            + [pdf_records[target.key] for target in PDF_TARGETS],
            "audit_artifacts": {
                "r12_ooxml": {
                    "relative_path": "audits/r12_ooxml_audit.json",
                    "sha256": sha256_bytes(rendered_r12),
                    "status": "PASS",
                },
                "PDF_identity": {
                    "relative_path": "audits/pdf_identity_audit.json",
                    "sha256": sha256_bytes(rendered_pdf),
                    "status": "PASS",
                },
                "authority_semantic": {
                    "relative_path": "audits/authority_semantic_audit.json",
                    "sha256": sha256_bytes(rendered_semantic),
                    "status": "PASS",
                },
            },
            "acquisition_gate": {
                "expected_payload_count": 4,
                "observed_payload_count": 4,
                "expected_official_page_count": 4,
                "observed_official_page_count": 4,
                "exact_anchor_response_and_byte_identity": "PASS",
                "R9_complete_header_and_structure": "PASS",
                "R12_lossless_OOXML_and_lexical_schema": "PASS",
                "R9_R12_interval_mapping": "PASS",
                "R9_mrg01_protected_mirrors": "PASS",
                "FSU_Holmes_crosswalk_evidence": "PASS",
                "AOP_Zeng_state_evidence": "PASS",
                "authority_collision_checks": "PASS",
                "publication_protocol": (
                    "exclusive-root-reservation-and-atomic-seal-last"
                ),
                "fresh_destination_no_overwrite": True,
                "independent_results_audit": "PENDING",
                "phase2_released": False,
                "transformation_join_reaggregation_match_statistics": False,
                "model_build_Slurm_day8": False,
            },
        }
        rendered_manifest = (
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        _write_new(staging / MANIFEST_NAME, rendered_manifest)
        seal_payload = (
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "SEALED",
                    "manifest_relative_path": MANIFEST_NAME,
                    "manifest_sha256": sha256_bytes(rendered_manifest),
                    "contract_sha256": contract_hash,
                    "payload_count": 4,
                    "official_page_snapshot_count": 4,
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
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--test-sha256", required=True)
    parser.add_argument("--focused-tests-verdict", choices=("PASS",), required=True)
    parser.add_argument("--code-audit-verdict", choices=("PASS",), required=True)
    parser.add_argument("--code-auditor", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = acquire(
        args.output_dir,
        contract_path=args.contract,
        expected_contract_sha256=args.contract_sha256,
        expected_source_sha256=args.source_sha256,
        expected_test_sha256=args.test_sha256,
        focused_tests_verdict=args.focused_tests_verdict,
        independent_code_audit_verdict=args.code_audit_verdict,
        independent_code_auditor=args.code_auditor,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
