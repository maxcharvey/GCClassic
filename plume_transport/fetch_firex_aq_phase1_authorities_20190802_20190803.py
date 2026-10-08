#!/usr/bin/env python3
"""Acquire and seal the frozen FIREX-AQ 2019-08-02/03 Phase-1 authorities.

This program implements the independently accepted *future* acquisition
contract.  Importing it has no side effects.  A later explicit invocation is
fail-closed on the frozen contract, source, test, interpreter, documentary
authority, destination, archive identity, complete-header, and date-local
semantic gates.

The tool deliberately does not inherit August-6 record counts, workbook row
ranges, identifiers, protected-mirror formatting exceptions, or terminal-time
exceptions.  It never transforms observations, joins science records, matches
model output, computes support/statistics, or edits/runs the model.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.message import Message
import hashlib
from html.parser import HTMLParser
from io import BytesIO, StringIO
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import secrets
import stat
import sys
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


CONTRACT_PATH = Path(
    "/cluster/home/mharvey/CharvBrain/project-vaults/gc-plume-transport/"
    "manifests/stage1-firex-aq-evidence-expansion-phase1-authority-"
    "20190802-20190803-v1.yml"
)
CONTRACT_SHA256 = (
    "d616e2ce232a573095d6e9b4021a87bda772d6fe4e9e2978f2db8691bb02425f"
)
DESTINATION = Path(
    "/cluster/work/climate/mharvey/Data/FIREX-AQ/"
    "stage1-firex-aq-evidence-expansion-phase1-authority-acquisition-"
    "20190802-20190803-v1"
)
FROZEN_PYTHON = Path(
    "/usr/local/Miniconda3-envs/envs/2024/envs/iacpy3_2024/bin/python"
)

NASA_ORIGIN = "https://www-air.larc.nasa.gov"
ALLOWED_ORIGINS = {"www-air.larc.nasa.gov"}
MANIFEST_NAME = "phase1_authority_acquisition_manifest.json"
FINAL_SEAL_NAME = "PHASE1_AUTHORITY_ACQUISITION_SEAL.json"
STOP_RECORD_NAME = "ACQUISITION_STOP.json"
R12_ARCHIVE_FILENAME = (
    "FIREXAQ-FIREFLAG-TABULARDATA_Analysis_20190724_R12_thru20190905.xlsx"
)

VAULT_ROOT = Path(
    "/cluster/home/mharvey/CharvBrain/project-vaults/gc-plume-transport"
)
FROZEN_PARENT_FILES = (
    (
        "contract-design",
        VAULT_ROOT
        / "designs/stage1-firex-aq-evidence-expansion-phase1-authority-20190802-20190803-v1.md",
        "88f2143be2251be4ba9c4435b938096dcbcce8e4a1639d878312584132c81253",
    ),
    (
        "resume-handoff",
        VAULT_ROOT
        / "reports/handoff-2026-08-11-parallel-phase0-qck-validation-release-closeout.md",
        "a12cfeae0a83b6ab8f8a147ec00236e562caec00044cee62e835166344d06f39",
    ),
    (
        "resume-state",
        VAULT_ROOT
        / "manifests/handoff-2026-08-11-parallel-phase0-qck-validation-release-closeout-v1.yml",
        "89383c884ac47c83f21d2296a1595c3a4aa165f1abb7f8660b8145d33b6e5602",
    ),
    (
        "resume-external-audit",
        VAULT_ROOT
        / "reports/handoff-2026-08-11-parallel-phase0-qck-validation-release-closeout-independent-audit.md",
        "f93c5acb54388782ab86fef1105e0d773739bf6a84f3c15038c2636b4536ef5d",
    ),
    (
        "evidence-expansion-design",
        VAULT_ROOT / "designs/stage1-firex-aq-evidence-expansion-v1.md",
        "8ab8a56e35eda081eb26ebf9391ca33ff371100e439bd089e0f6adbdbd5eeb9e",
    ),
    (
        "evidence-expansion-manifest",
        VAULT_ROOT / "manifests/stage1-firex-aq-evidence-expansion-v1.yml",
        "c6dacf6b2869b4c3ff0d1df4bda1cdc60a0512edd1c58ac34c47ed3fe7a8c7f3",
    ),
    (
        "phase0-report",
        VAULT_ROOT
        / "reports/stage1-firex-aq-evidence-expansion-phase0-inventory-2026-08-11.md",
        "83502395ceeae2572f9e21b5b391994352b1785bf617ff98f9db3c6323846fb8",
    ),
    (
        "phase0-contract",
        VAULT_ROOT
        / "manifests/stage1-firex-aq-evidence-expansion-phase0-inventory-v1.yml",
        "87cd87808ca5a928b96a1c967b3b1e5d7344810de4d05e4671a982d67441545c",
    ),
    (
        "phase0-results",
        VAULT_ROOT
        / "manifests/stage1-firex-aq-evidence-expansion-phase0-inventory-v1-results.yml",
        "1fc08e1806b09b2d089e83f2e24815df63438698556842244b348a39820b20b4",
    ),
    (
        "phase0-release-audit",
        VAULT_ROOT
        / "reports/stage1-parallel-phase0-qck-validation-independent-audit-2026-08-11.md",
        "fa010126704085d0ed2342d4ff6f2515a3ade33d45e98bd73898d27d9affabad",
    ),
    (
        "observation-inventory-design",
        VAULT_ROOT / "designs/stage1-firex-aq-observation-inventory-v2.md",
        "f5d043305244eb51bb9927f221a5a0f984087a588bc7674ebad9bd0b99c3e3b8",
    ),
    (
        "observation-inventory-manifest",
        VAULT_ROOT / "manifests/stage1-firex-aq-observation-inventory-v2.yml",
        "42694fb63e10f5d2d7afd8b266fd7abe6a4d1ed1af61d92ff6e8b760987e30d1",
    ),
    (
        "evaluation-design",
        VAULT_ROOT / "designs/stage1-firex-aq-uncertainty-evaluation-v2.md",
        "e22d7eecc6f586297085923685f70df3661b4105b69c4a6a864cfd23cb23da12",
    ),
    (
        "evaluation-manifest",
        VAULT_ROOT / "manifests/stage1-firex-aq-uncertainty-evaluation-v2.yml",
        "b82a01c9d1d5d255e911c95ca86a3d430cf12f428c676ea3c0cddc416c820bcb",
    ),
    (
        "August6-authority-contract",
        VAULT_ROOT
        / "manifests/stage1-firex-aq-tier-f-authority-acquisition-20190806-v2.yml",
        "4c92f52681b60d1e01bae91f414114118d320731df22f12a7b4b28907e7bce9e",
    ),
    (
        "August6-authority-results",
        VAULT_ROOT
        / "manifests/stage1-firex-aq-tier-f-authority-acquisition-20190806-v2-results.yml",
        "98c4f0f03b3b98873ef6346b9d0686317b53d6a4167f30e1e954a7dc7b16552e",
    ),
    (
        "August6-authority-report",
        VAULT_ROOT
        / "reports/stage1-firex-aq-tier-f-authority-acquisition-and-semantic-audit-20190806-v2.md",
        "9e5177c7ea76f0a93396082548dba3183b7b566b0a7ff2b8437f90043554e259",
    ),
    (
        "August2-model-coverage",
        VAULT_ROOT / "manifests/stage1-firex-exact-band-20190802-daily-v1.yml",
        "4dda6c29cd20df4c2a1d7a23f17630583c36ba6153b17a559782974bf4df9db2",
    ),
    (
        "August3-model-coverage",
        VAULT_ROOT
        / "manifests/stage1-firex-exact-band-20190803-daily-retry1.yml",
        "c13e743a454ea95ec17fb5789b326c68a25fa7900d091cf932c63602d6c8fccc",
    ),
    (
        "August4-model-coverage",
        VAULT_ROOT / "manifests/stage1-firex-exact-band-20190804-daily-v1.yml",
        "6bb6b0e851af4ab7ac8a695f34e38f80d194a0112c872e12618611032a7eb6dd",
    ),
)


class AcquisitionError(RuntimeError):
    """Raised when a frozen acceptance condition cannot be proved."""


@dataclass(frozen=True)
class PageTarget:
    key: str
    url: str
    relative_path: str


@dataclass(frozen=True)
class PayloadTarget:
    date: str
    julian_day: int
    product: str
    revision: str
    filename: str
    page_key: str
    candidate_role: str


@dataclass(frozen=True)
class FetchResult:
    payload: bytes
    final_url: str
    http_status: int | None
    headers: Mapping[str, str]


@dataclass(frozen=True)
class IcarttPayload:
    header: bytes
    header_line_count: int
    file_format_index: int
    header_lines: tuple[str, ...]
    fields: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    dependent_variable_count: int
    scale_factors: tuple[str, ...]
    missing_values: tuple[str, ...]
    variable_descriptions: tuple[str, ...]
    independent_variable_description: str
    file_date: str


@dataclass(frozen=True)
class DocumentaryFile:
    key: str
    relative_path: str
    sha256: str
    role: str


@dataclass(frozen=True)
class DocumentarySpec:
    root: Path
    seal_name: str
    seal_sha256: str
    manifest_name: str
    manifest_sha256: str
    files: tuple[DocumentaryFile, ...]


PAGES = (
    PageTarget(
        "NASA_MERGE",
        f"{NASA_ORIGIN}/cgi-bin/ArcView/firexaq?MERGE=1",
        "pages/NASA_FIREXAQ_MERGE_index.html",
    ),
    PageTarget(
        "NASA_DC8",
        f"{NASA_ORIGIN}/cgi-bin/ArcView/firexaq?DC8=1",
        "pages/NASA_FIREXAQ_DC8_index.html",
    ),
    PageTarget(
        "NASA_ANALYSIS",
        f"{NASA_ORIGIN}/cgi-bin/ArcView/firexaq?ANALYSIS=1",
        "pages/NASA_FIREXAQ_ANALYSIS_index.html",
    ),
)
PAGE_BY_KEY = {page.key: page for page in PAGES}


def _targets_for_date(
    date: str,
    julian_day: int,
    *,
    sp2_revision: str,
    ams_revision: str,
) -> tuple[PayloadTarget, ...]:
    compact = date.replace("-", "")
    return (
        PayloadTarget(
            date,
            julian_day,
            "mrg01",
            "R3",
            f"FIREXAQ-mrg01-DC8_merge_{compact}_R3.ict",
            "NASA_MERGE",
            "time-navigation-coregistration-carrier-fire-fields-mirror-only",
        ),
        PayloadTarget(
            date,
            julian_day,
            "AOP",
            "R2",
            f"firexaq-AOP-optical_DC8_{compact}_R2.ict",
            "NASA_DC8",
            "dry-405-532-664-values-flags-RH-header-wording",
        ),
        PayloadTarget(
            date,
            julian_day,
            "FSU",
            "R1",
            f"firexaq-FSU-smokeage_dc8_{compact}_R1.ict",
            "NASA_DC8",
            "trajectory-age-values-only",
        ),
        PayloadTarget(
            date,
            julian_day,
            "R9",
            "R9",
            f"firexaq-fire-Flags-1HZ_DC8_{compact}_R9.ict",
            "NASA_DC8",
            "direct-smoke-fire-transect-plume-fuel-authority",
        ),
        PayloadTarget(
            date,
            julian_day,
            "SP2",
            sp2_revision,
            f"FIREXAQ-SP2-BC-1HZ_DC8_{compact}_{sp2_revision}.ict",
            "NASA_DC8",
            "revision-local-rBC-QC-dilution-state-to-establish",
        ),
        PayloadTarget(
            date,
            julian_day,
            "AMS",
            ams_revision,
            f"FIREXAQ-AMS_DC8_{compact}_{ams_revision}.ict",
            "NASA_DC8",
            "revision-local-OA-precision-detection-limit-cloud-to-establish",
        ),
    )


TARGETS = _targets_for_date(
    "2019-08-02", 214, sp2_revision="R2", ams_revision="R3"
) + _targets_for_date(
    "2019-08-03", 215, sp2_revision="R3", ams_revision="R2"
)

DOCUMENTARY_SPEC = DocumentarySpec(
    root=Path(
        "/cluster/work/climate/mharvey/Data/FIREX-AQ/"
        "tier-f-20190806-authorities-v2"
    ),
    seal_name="AUTHORITY_ACQUISITION_SEAL.json",
    seal_sha256=(
        "6858e99aaa5d749694ffc3270a908f76f45a281715e1c285483c9b3c1785db15"
    ),
    manifest_name="tier_f_authority_acquisition_manifest.json",
    manifest_sha256=(
        "287f2a52b21dec61f1e4ae7accd761ac64532df4d677f8e468365d6dfead69be"
    ),
    files=(
        DocumentaryFile(
            "R12",
            "raw/FIREXAQ-FIREFLAG-TABULARDATA_Analysis_"
            "20190724_R12_thru20190905.xlsx",
            "4ab01547551d6ba9dc22feed3bbea4ffec58727c50f6ee92774320149c87815b",
            "glossary-codebook-exact-lexical-identifier-authority",
        ),
        DocumentaryFile(
            "Holmes",
            "raw/essd-2025-307.pdf",
            "1af731b89846ca3b79110883ece9e29382252c07b9153d7fba911c19c10a29c3",
            "provisional-FSU-trajectory-age-semantics-only",
        ),
        DocumentaryFile(
            "Zeng",
            "raw/acp-22-8009-2022.pdf",
            "f505d6dab97e768c23d157e8ccfdb2100b7ffc639efc1c9d88315ada7ed8f4c5",
            "dataset-level-273K-1013mbar-state-only",
        ),
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
LEXICAL_IDENTIFIER_FIELDS = {
    "fire_id",
    "transect_number",
    "transect_plume_number",
}

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


def _valid_sha256(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    """Render a finite identifier as the same exact decimal value.

    No tolerance, rounding, binary floating point, or August-6 formatter
    exception is applied.  Lexemes that differ only by exact decimal notation
    (for example ``10.20`` and ``10.2``) share a rendering; unequal decimals
    remain unequal.
    """
    number = _decimal(value, "identifier")
    rendered = format(number.normalize(), "f")
    return "0" if rendered in ("", "-0") else rendered


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_ORIGINS
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise AcquisitionError(f"prohibited URL: {url!r}")
    return parsed.hostname or ""


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
            f"HTTP redirect prohibited for {request.full_url!r}: "
            f"{code} -> {new_url!r}"
        )


def fetch_resource(url: str) -> FetchResult:
    _origin(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "gc-plume-transport-phase1-authority-acquisition/1",
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


def _normalize_response(
    result: bytes | FetchResult,
    requested_url: str,
    *,
    require_exact_final_url: bool = True,
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
        raise AcquisitionError("response origin differs from requested origin")
    if require_exact_final_url and response.final_url != requested_url:
        raise AcquisitionError(
            f"final response URL mismatch: {response.final_url!r}"
        )
    if response.http_status is not None and response.http_status != 200:
        raise AcquisitionError(
            f"unexpected HTTP status {response.http_status} for {requested_url!r}"
        )
    return response


def _served_filename(response: FetchResult, expected: str) -> str | None:
    disposition = response.headers.get("content-disposition")
    if response.http_status is None and disposition is None:
        return None
    if disposition is None:
        raise AcquisitionError(f"missing Content-Disposition for {expected}")
    message = Message()
    message["Content-Disposition"] = disposition
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
        raise AcquisitionError(f"could not parse NASA archive page: {error}") from error
    return parser.anchors


def discover_payload_urls(
    page_payloads: Mapping[str, bytes],
    *,
    targets: Sequence[PayloadTarget] = TARGETS,
    pages: Sequence[PageTarget] = PAGES,
) -> dict[tuple[str, str], tuple[str, str]]:
    page_map = {page.key: page for page in pages}
    if set(page_payloads) != set(page_map):
        raise AcquisitionError("NASA archive page set differs from frozen page set")
    anchors = {key: _parse_anchors(value) for key, value in page_payloads.items()}
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for target in targets:
        matches = [
            href
            for href, text in anchors[target.page_key]
            if text == target.filename
        ]
        if len(matches) != 1:
            raise AcquisitionError(
                f"{target.filename}: expected exactly one exact archive anchor, "
                f"found {len(matches)}"
            )
        page = page_map[target.page_key]
        resolved = urljoin(page.url, matches[0])
        if _origin(resolved) != "www-air.larc.nasa.gov":
            raise AcquisitionError(f"unexpected NASA archive origin: {resolved!r}")
        key = (target.date, target.product)
        if key in result:
            raise AcquisitionError(f"duplicate target key {key!r}")
        result[key] = (matches[0], resolved)
    return result


def confirm_r12_archive_anchor(
    page_payloads: Mapping[str, bytes],
    *,
    pages: Sequence[PageTarget] = PAGES,
) -> dict[str, object]:
    """Confirm, but never retrieve, the sealed R12 workbook's live anchor."""
    page_map = {page.key: page for page in pages}
    if "NASA_ANALYSIS" not in page_map or "NASA_ANALYSIS" not in page_payloads:
        raise AcquisitionError("NASA ANALYSIS page is absent from the exact page set")
    anchors = _parse_anchors(page_payloads["NASA_ANALYSIS"])
    matches = [
        href for href, text in anchors if text == R12_ARCHIVE_FILENAME
    ]
    if len(matches) != 1:
        raise AcquisitionError(
            "sealed R12 workbook requires exactly one exact displayed ANALYSIS "
            f"anchor; found {len(matches)}"
        )
    resolved = urljoin(page_map["NASA_ANALYSIS"].url, matches[0])
    _origin(resolved)
    return {
        "status": "PASS",
        "filename": R12_ARCHIVE_FILENAME,
        "archive_page_key": "NASA_ANALYSIS",
        "archive_href": matches[0],
        "resolved_url": resolved,
        "retrieved_or_copied": False,
        "role": "read-only-confirmation-of-sealed-R12-global-documentary-authority",
    }


def _csv_values(line: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in next(csv.reader([line])))


def parse_icartt(payload: bytes, expected_date: str) -> IcarttPayload:
    lines = payload.splitlines(keepends=True)
    if not lines:
        raise AcquisitionError("empty ICARTT payload")
    try:
        first_record = _csv_values(lines[0].decode("latin1"))
        if len(first_record) != 2:
            raise AcquisitionError("ICARTT first record must contain NLHEAD and FFI")
        header_count = _integer(first_record[0], "ICARTT NLHEAD")
        file_format_index = _integer(first_record[1], "ICARTT FFI")
    except UnicodeError as error:
        raise AcquisitionError("invalid ICARTT first record") from error
    if file_format_index != 1001:
        raise AcquisitionError(
            f"unsupported ICARTT FFI {file_format_index}; exact FFI 1001 required"
        )
    if header_count < 13 or header_count > len(lines):
        raise AcquisitionError(
            f"invalid ICARTT header length {header_count} for {len(lines)} lines"
        )
    header = b"".join(lines[:header_count])
    header_lines = tuple(header.decode("latin1").splitlines())
    dependent_count = _integer(header_lines[9].split(",", 1)[0], "ICARTT NV")
    if dependent_count < 1:
        raise AcquisitionError("ICARTT dependent-variable count must be positive")
    scale_factors = _csv_values(header_lines[10])
    missing_values = _csv_values(header_lines[11])
    if len(scale_factors) != dependent_count:
        raise AcquisitionError("ICARTT scale-factor count differs from NV")
    if len(missing_values) != dependent_count:
        raise AcquisitionError("ICARTT missing-value count differs from NV")
    description_stop = 12 + dependent_count
    if description_stop >= len(header_lines):
        raise AcquisitionError("ICARTT variable descriptions are truncated")
    descriptions = tuple(header_lines[12:description_stop])
    volume_values = _csv_values(header_lines[5])
    if len(volume_values) != 2:
        raise AcquisitionError("ICARTT volume-number record must contain IVOL and NVOL")
    volume_number = _integer(volume_values[0], "ICARTT IVOL")
    volume_count = _integer(volume_values[1], "ICARTT NVOL")
    if volume_number < 1 or volume_count < 1 or volume_number > volume_count:
        raise AcquisitionError("ICARTT volume-number relation is invalid")
    if _decimal(header_lines[7].split(",", 1)[0], "ICARTT DX") <= 0:
        raise AcquisitionError("ICARTT independent-variable interval DX is not positive")
    special_count_values = _csv_values(header_lines[description_stop])
    if len(special_count_values) != 1:
        raise AcquisitionError("ICARTT special-comment count record is malformed")
    special_count = _integer(special_count_values[0], "ICARTT NSCOML")
    if special_count < 0:
        raise AcquisitionError("ICARTT special-comment count is negative")
    normal_count_index = description_stop + 1 + special_count
    if normal_count_index >= len(header_lines):
        raise AcquisitionError("ICARTT special-comment block is truncated")
    normal_count_values = _csv_values(header_lines[normal_count_index])
    if len(normal_count_values) != 1:
        raise AcquisitionError("ICARTT normal-comment count record is malformed")
    normal_count = _integer(normal_count_values[0], "ICARTT NNCOML")
    if normal_count < 0:
        raise AcquisitionError("ICARTT normal-comment count is negative")
    field_index = normal_count_index + 1 + normal_count
    if field_index != len(header_lines) - 1:
        raise AcquisitionError(
            "ICARTT comment counts do not locate exactly one final field record"
        )
    independent_description = header_lines[8]
    fields = _csv_values(header_lines[field_index])
    if len(fields) != dependent_count + 1:
        raise AcquisitionError(
            "ICARTT final field count differs from independent plus NV"
        )
    data_text = b"".join(lines[header_count:]).decode("latin1")
    rows = tuple(
        tuple(value.strip() for value in row)
        for row in csv.reader(StringIO(data_text), skipinitialspace=True)
        if row and any(value.strip() for value in row)
    )
    if not rows:
        raise AcquisitionError("ICARTT payload has no data records")
    if any(len(row) != len(fields) for row in rows):
        raise AcquisitionError("ICARTT data row has the wrong column count")
    folded_fields = [field.casefold() for field in fields]
    if len(folded_fields) != len(set(folded_fields)):
        raise AcquisitionError("ICARTT field names are not unique case-insensitively")
    independent_parts = _csv_values(independent_description)
    if len(independent_parts) < 2 or independent_parts[0].casefold() != fields[0].casefold():
        raise AcquisitionError(
            "ICARTT independent-variable description does not match the first field"
        )
    if "second" not in " ".join(independent_parts[1:]).casefold():
        raise AcquisitionError("ICARTT independent time variable is not in seconds")
    for index, description in enumerate(descriptions, start=1):
        parts = _csv_values(description)
        if len(parts) < 4:
            raise AcquisitionError(
                f"ICARTT variable description {index} has fewer than four fields"
            )
        if parts[0].casefold() != fields[index].casefold():
            raise AcquisitionError(
                f"ICARTT variable description {index} does not match {fields[index]!r}"
            )
        if not parts[1] or not " ".join(parts[3:]).strip():
            raise AcquisitionError(
                f"ICARTT variable description {fields[index]!r} lacks units or wording"
            )
    for index, value in enumerate(scale_factors, start=1):
        if _decimal(value, f"ICARTT scale factor for {fields[index]}") == 0:
            raise AcquisitionError(f"ICARTT scale factor for {fields[index]} is zero")
    for index, value in enumerate(missing_values, start=1):
        _decimal(value, f"ICARTT missing sentinel for {fields[index]}")
    for ordinal, row in enumerate(rows):
        for field, value in zip(fields, row):
            _decimal(value, f"ICARTT {field} row {ordinal}")
    date_values = _csv_values(header_lines[6])
    if len(date_values) < 3:
        raise AcquisitionError("ICARTT file-date record is incomplete")
    file_date = "-".join(
        (
            f"{_integer(date_values[0], 'ICARTT year'):04d}",
            f"{_integer(date_values[1], 'ICARTT month'):02d}",
            f"{_integer(date_values[2], 'ICARTT day'):02d}",
        )
    )
    if file_date != expected_date:
        raise AcquisitionError(
            f"ICARTT file date mismatch: expected {expected_date}, got {file_date}"
        )
    return IcarttPayload(
        header=header,
        header_line_count=header_count,
        file_format_index=file_format_index,
        header_lines=header_lines,
        fields=fields,
        rows=rows,
        dependent_variable_count=dependent_count,
        scale_factors=scale_factors,
        missing_values=missing_values,
        variable_descriptions=descriptions,
        independent_variable_description=independent_description,
        file_date=file_date,
    )


def _matching_header_lines(
    parsed: IcarttPayload, patterns: Iterable[str]
) -> list[dict[str, object]]:
    folded = tuple(pattern.casefold() for pattern in patterns)
    return [
        {"line_number": number, "text": line}
        for number, line in enumerate(parsed.header_lines, start=1)
        if any(pattern in line.casefold() for pattern in folded)
    ]


def _field_lookup(parsed: IcarttPayload) -> dict[str, int]:
    folded = [field.casefold() for field in parsed.fields]
    if len(folded) != len(set(folded)):
        raise AcquisitionError("ICARTT field names are not unique case-insensitively")
    return {field: index for index, field in enumerate(folded)}


def _render_decimal(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return "0" if rendered in ("", "-0") else rendered


def _dependent_field_contracts(
    parsed: IcarttPayload,
) -> dict[str, dict[str, object]]:
    """Return an exact, field-addressed ICARTT scale/sentinel ledger."""
    result: dict[str, dict[str, object]] = {}
    for index, field in enumerate(parsed.fields[1:], start=1):
        parts = _csv_values(parsed.variable_descriptions[index - 1])
        missing = _decimal(parsed.missing_values[index - 1], f"{field} sentinel")
        scale = _decimal(parsed.scale_factors[index - 1], f"{field} scale")
        values = [_decimal(row[index], f"{field} data") for row in parsed.rows]
        missing_count = sum(value == missing for value in values)
        key = field.casefold()
        result[key] = {
            "field": field,
            "units": parts[1],
            "qualifier": parts[2],
            "description": ",".join(parts[3:]).strip(),
            "raw_description": parsed.variable_descriptions[index - 1],
            "scale_factor_exact_decimal": _render_decimal(scale),
            "missing_sentinel_exact_decimal": _render_decimal(missing),
            "missing_sentinel_count": missing_count,
            "nonmissing_numeric_count": len(values) - missing_count,
        }
    return result


def _contract_for(
    contracts: Mapping[str, Mapping[str, object]], field: str, label: str
) -> Mapping[str, object]:
    try:
        return contracts[field.casefold()]
    except KeyError as error:
        raise AcquisitionError(f"{label} lacks exact field {field!r}") from error


def _description_text(contract: Mapping[str, object]) -> str:
    return str(contract["description"]).casefold()


def _require_description_words(
    contract: Mapping[str, object], words: Iterable[str], label: str
) -> None:
    text = _description_text(contract)
    missing = [word for word in words if word.casefold() not in text]
    if missing:
        raise AcquisitionError(f"{label} description lacks exact semantics: {missing}")


def _audit_time_domain(parsed: IcarttPayload, label: str) -> dict[str, object]:
    first_field = parsed.fields[0].casefold()
    if first_field not in {"time_start", "time_mid", "time"}:
        raise AcquisitionError(f"{label} first field is not an accepted explicit time")
    values = [_decimal(row[0], f"{label} time row {index}") for index, row in enumerate(parsed.rows)]
    if any(right <= left for left, right in zip(values, values[1:])):
        raise AcquisitionError(f"{label} time domain is duplicated, reversed, or unordered")
    deltas = [right - left for left, right in zip(values, values[1:])]
    unique_deltas = sorted(set(deltas))
    lookup = _field_lookup(parsed)
    stop_contract: dict[str, object] | None = None
    if "time_stop" in lookup:
        stop_index = lookup["time_stop"]
        stops = [
            _decimal(row[stop_index], f"{label} Time_Stop row {index}")
            for index, row in enumerate(parsed.rows)
        ]
        if any(stop <= start for start, stop in zip(values, stops)):
            raise AcquisitionError(f"{label} contains a nonpositive time interval")
        if any(right <= left for left, right in zip(stops, stops[1:])):
            raise AcquisitionError(f"{label} Time_Stop values are not strictly ordered")
        stop_contract = {
            "field": parsed.fields[stop_index],
            "first_exact_decimal": _render_decimal(stops[0]),
            "last_exact_decimal": _render_decimal(stops[-1]),
            "all_stops_after_corresponding_starts": True,
        }
    return {
        "status": "PASS",
        "independent_field": parsed.fields[0],
        "independent_description": parsed.independent_variable_description,
        "units": "seconds-from-midnight-UTC",
        "record_count": len(values),
        "first_exact_decimal": _render_decimal(values[0]),
        "last_exact_decimal": _render_decimal(values[-1]),
        "strictly_increasing": True,
        "cadence_constant": len(unique_deltas) <= 1,
        "cadence_seconds_exact_decimals": [
            _render_decimal(value) for value in unique_deltas
        ],
        "time_stop": stop_contract,
        "August6_time_domain_or_terminal_relation_inherited": False,
    }


_SENTINEL_PATTERNS = {
    "missing": re.compile(
        r"\bmissing(?:[\s_-]+value(?:s)?)?\b[^\-+0-9]{0,24}([+-]?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    "ULOD": re.compile(
        r"\bULOD(?:[\s_-]+value)?\b[^\-+0-9]{0,24}([+-]?\d+(?:\.\d+)?)", re.IGNORECASE
    ),
    "LLOD": re.compile(
        r"\bLLOD(?:[\s_-]+value)?\b[^\-+0-9]{0,24}([+-]?\d+(?:\.\d+)?)", re.IGNORECASE
    ),
}


def _sentinel_lexicon(parsed: IcarttPayload, label: str) -> dict[str, Decimal]:
    text = "\n".join(parsed.header_lines)
    result: dict[str, Decimal] = {}
    for kind, pattern in _SENTINEL_PATTERNS.items():
        values = {
            _decimal(match.group(1), f"{label} {kind} sentinel")
            for match in pattern.finditer(text)
        }
        if len(values) != 1:
            raise AcquisitionError(
                f"{label} must establish exactly one date-local {kind} sentinel; "
                f"found {sorted(_render_decimal(value) for value in values)}"
            )
        result[kind] = next(iter(values))
    return result


def _semantic_field_matches(
    contracts: Mapping[str, Mapping[str, object]],
    *,
    name_pattern: str,
    description_terms: Iterable[str],
) -> list[Mapping[str, object]]:
    expression = re.compile(name_pattern, re.IGNORECASE)
    result: list[Mapping[str, object]] = []
    for contract in contracts.values():
        if expression.fullmatch(str(contract["field"])) is None:
            continue
        text = _description_text(contract)
        if all(term.casefold() in text for term in description_terms):
            result.append(contract)
    return result


def _require_semantic_fields(
    contracts: Mapping[str, Mapping[str, object]],
    *,
    name_pattern: str,
    description_terms: Iterable[str],
    label: str,
) -> list[Mapping[str, object]]:
    matches = _semantic_field_matches(
        contracts,
        name_pattern=name_pattern,
        description_terms=description_terms,
    )
    if not matches:
        raise AcquisitionError(
            f"{label} has no structured field/description crosswalk matching "
            f"{name_pattern!r} and {list(description_terms)!r}"
        )
    return matches


def _audit_binary_flag_codebook(
    parsed: IcarttPayload,
    *,
    field: str,
    positive_term: str,
    label: str,
) -> dict[str, object]:
    """Prove an exact 0/1 flag meaning from this payload's own header."""
    contracts = _dependent_field_contracts(parsed)
    contract = _contract_for(contracts, field, label)
    field_pattern = re.compile(
        re.escape(field).replace("_", r"[ _-]+"), re.IGNORECASE
    )
    evidence_lines = [
        {"line_number": number, "text": line}
        for number, line in enumerate(parsed.header_lines, start=1)
        if field_pattern.search(line)
    ]
    if not evidence_lines:
        raise AcquisitionError(f"{label} has no date-local codebook evidence line")
    assignments: dict[int, set[str]] = {0: set(), 1: set()}
    for evidence in evidence_lines:
        for match in re.finditer(
            r"(?<![0-9.])([01])\s*=\s*([^;,\n]+)",
            str(evidence["text"]),
            re.IGNORECASE,
        ):
            assignments[int(match.group(1))].add(match.group(2).strip())
    normalized_term = positive_term.casefold()

    def meaning(value: str) -> bool | None:
        normalized = re.sub(r"[_-]+", " ", value.casefold())
        if re.search(
            rf"\b(?:no|non|not)\s+{re.escape(normalized_term)}\b",
            normalized,
        ):
            return False
        if re.search(rf"\b{re.escape(normalized_term)}\b", normalized):
            return True
        return None

    classified = {
        code: {meaning(value) for value in values}
        for code, values in assignments.items()
    }
    if (
        not assignments[0]
        or not assignments[1]
        or classified[0] != {False}
        or classified[1] != {True}
    ):
        raise AcquisitionError(
            f"{label} must unambiguously declare 1={positive_term} and "
            f"0=no/non-{positive_term}; assignments={assignments!r}"
        )
    sentinel_lexicon = _sentinel_lexicon(parsed, label)
    if any(value in {Decimal(0), Decimal(1)} for value in sentinel_lexicon.values()):
        raise AcquisitionError(f"{label} 0/1 codes collide with declared sentinels")
    return {
        "status": "PASS",
        "field": str(contract["field"]),
        "positive_code_exact_decimal": "1",
        "positive_meaning": positive_term,
        "negative_code_exact_decimal": "0",
        "negative_meaning": f"no/non-{positive_term}",
        "date_local_header_evidence": evidence_lines,
        "assignments": {
            str(code): sorted(values) for code, values in assignments.items()
        },
        "declared_sentinels_excluded": True,
        "August6_or_conventional_code_meaning_inherited": False,
    }


def _require_fields(
    parsed: IcarttPayload, required: Iterable[str], label: str
) -> None:
    available = set(_field_lookup(parsed))
    missing = [field for field in required if field.casefold() not in available]
    if missing:
        raise AcquisitionError(f"{label} header is missing fields: {missing}")


def _require_field_pattern(
    parsed: IcarttPayload, patterns: Iterable[str], label: str
) -> list[str]:
    folded_patterns = tuple(pattern.casefold() for pattern in patterns)
    matches = [
        field
        for field in parsed.fields
        if any(pattern in field.casefold() for pattern in folded_patterns)
    ]
    if not matches:
        raise AcquisitionError(f"{label} has no field matching {list(patterns)!r}")
    return matches


def audit_product_header(
    target: PayloadTarget, parsed: IcarttPayload
) -> dict[str, object]:
    contracts = _dependent_field_contracts(parsed)
    time_domain = _audit_time_domain(parsed, f"{target.date} {target.product}")
    text = "\n".join(parsed.header_lines)
    folded_text = text.casefold()

    role: dict[str, object]
    if target.product == "R9":
        if tuple(field.casefold() for field in parsed.fields) != tuple(
            field.casefold() for field in R9_FIELDS
        ):
            raise AcquisitionError("R9 field schema differs from the direct authority")
        sentinel_lexicon = _sentinel_lexicon(parsed, f"{target.date} R9")
        smoke_codebook = _audit_binary_flag_codebook(
            parsed,
            field="smoke_flag",
            positive_term="smoke",
            label=f"{target.date} R9 smoke_flag",
        )
        background_codebook = _audit_binary_flag_codebook(
            parsed,
            field="background_flag",
            positive_term="background",
            label=f"{target.date} R9 background_flag",
        )
        chisq = _contract_for(contracts, "transect_mce_ODR_chisq", "R9")
        _require_description_words(chisq, ("uncert",), "R9 ODR uncertainty")
        role = {
            "direct_fire_smoke_transect_plume_fuel_authority": True,
            "smoke_flag_codebook": smoke_codebook,
            "background_flag_codebook": background_codebook,
            "uncertainty_contract": chisq,
            "sentinel_lexicon": {
                key: _render_decimal(value) for key, value in sentinel_lexicon.items()
            },
        }
    elif target.product == "mrg01":
        _require_fields(parsed, ("Time_Start", "Time_Stop"), "mrg01")
        navigation = {
            "latitude": _require_semantic_fields(
                contracts,
                name_pattern=r"(?:gps_)?lat(?:itude)?",
                description_terms=("latitude",),
                label="mrg01 latitude",
            ),
            "longitude": _require_semantic_fields(
                contracts,
                name_pattern=r"(?:gps_)?lon(?:gitude)?",
                description_terms=("longitude",),
                label="mrg01 longitude",
            ),
            "altitude": _require_semantic_fields(
                contracts,
                name_pattern=r"(?:gps_)?alt(?:itude)?",
                description_terms=("altitude",),
                label="mrg01 altitude",
            ),
        }
        sentinel_lexicon = _sentinel_lexicon(parsed, f"{target.date} mrg01")
        role = {
            "time_navigation_coregistration_carrier": True,
            "fire_fields_are_QA_mirrors_only": True,
            "navigation_fields": navigation,
            "sentinel_lexicon": {
                key: _render_decimal(value) for key, value in sentinel_lexicon.items()
            },
        }
    elif target.product == "AOP":
        _require_fields(parsed, ("abs_dry_405", "abs_dry_532", "abs_dry_664"), "AOP")
        band_contracts = {
            wavelength: _contract_for(contracts, f"abs_dry_{wavelength}", "AOP")
            for wavelength in (405, 532, 664)
        }
        for wavelength, contract in band_contracts.items():
            _require_description_words(
                contract, ("dry", "absorp"), f"AOP {wavelength} nm"
            )
        band_units = {str(contract["units"]).casefold() for contract in band_contracts.values()}
        if len(band_units) != 1:
            raise AcquisitionError("AOP dry-band absorption units are inconsistent")
        dilution = _contract_for(contracts, "AOP_Dilution_ratio", "AOP")
        _require_description_words(dilution, ("dilution", "aop"), "AOP dilution")
        rh_fields = _require_semantic_fields(
            contracts,
            name_pattern=r"(?:rh|rh_cabin|relative_humidity)",
            description_terms=("relative humidity",),
            label="AOP relative humidity",
        )
        quality_fields = _require_semantic_fields(
            contracts,
            name_pattern=r".*(?:quality|qc).*flag.*|.*flag.*(?:quality|qc).*",
            description_terms=("flag",),
            label="AOP quality flag",
        )
        reference_lines = [
            {"line_number": number, "text": line}
            for number, line in enumerate(parsed.header_lines, start=1)
            if "pm2.5_stp" in line.casefold()
            and re.search(r"\b273(?:\.0+)?\s*K\b", line, re.IGNORECASE)
            and re.search(r"\b1013(?:\.0+)?\s*mbar\b", line, re.IGNORECASE)
        ]
        if len(reference_lines) != 1:
            raise AcquisitionError(
                "AOP must establish one exact PM2.5_STP 273 K/1013 mbar line"
            )
        required_precision_lines = (
            "high signal accuracy of 20%",
            "low signal precision varies with altitude and flight to flight",
        )
        precision_lines = {
            marker: _matching_header_lines(parsed, (marker,))
            for marker in required_precision_lines
        }
        if any(len(lines) != 1 for lines in precision_lines.values()):
            raise AcquisitionError("AOP accuracy/precision wording is not unique and exact")
        role = {
            "dry_PAS_family": True,
            "wavelengths_nm": [405, 532, 664],
            "band_field_contracts": band_contracts,
            "band_units_identical": True,
            "reference_state_evidence": reference_lines[0],
            "quality_field_contracts": quality_fields,
            "relative_humidity_field_contracts": rh_fields,
            "AOP_dilution_contract": dilution,
            "accuracy_precision_evidence": precision_lines,
            "Zeng_reference_state_applicability_candidate": "structured-date-local-PASS",
            "per_record_low_signal_precision_inferred": False,
        }
    elif target.product == "FSU":
        _require_fields(
            parsed,
            ("smoke_age", "smoke_age_unc", "smoke_age_corr", "smoke_agemethod"),
            "FSU",
        )
        fsu_contracts = {
            field: _contract_for(contracts, field, "FSU")
            for field in ("smoke_age", "smoke_age_unc", "smoke_age_corr", "smoke_agemethod")
        }
        for field in ("smoke_age", "smoke_age_unc", "smoke_age_corr"):
            if str(fsu_contracts[field]["units"]).strip().casefold() not in {"s", "sec", "second", "seconds"}:
                raise AcquisitionError(f"FSU {field} is not explicitly in seconds")
        _require_description_words(
            fsu_contracts["smoke_age"],
            ("age of smoke", "aircraft measurement"),
            "FSU smoke_age",
        )
        _require_description_words(
            fsu_contracts["smoke_age_unc"], ("uncertainty", "age of smoke"), "FSU smoke_age_unc"
        )
        _require_description_words(
            fsu_contracts["smoke_age_corr"], ("age of smoke", "correction"), "FSU smoke_age_corr"
        )
        method_match = re.search(
            r'Key to "smoke_agemethod".*?:\s*'
            r"1=HRRR,NAM,GFS \(default\); 2=HRRR,NAM; 3=HRRR,GFS; "
            r"4=NAM,GFS; 5=HRRR; 6=NAM; 7=GFS",
            text,
        )
        if method_match is None:
            raise AcquisitionError("FSU method-code crosswalk 1 through 7 is not exact")
        method_index = _field_lookup(parsed)["smoke_agemethod"]
        method_missing = _decimal(
            str(fsu_contracts["smoke_agemethod"]["missing_sentinel_exact_decimal"]),
            "FSU method sentinel",
        )
        observed_codes = {
            _integer(row[method_index], "FSU smoke_agemethod")
            for row in parsed.rows
            if _decimal(row[method_index], "FSU smoke_agemethod") != method_missing
        }
        if not observed_codes.issubset(set(range(1, 8))):
            raise AcquisitionError(f"FSU contains undeclared method codes: {sorted(observed_codes)}")
        role = {
            "trajectory_age_values_only": True,
            "mean_wind_R9_age_or_distance_substitution": False,
            "field_unit_scope_contracts": fsu_contracts,
            "method_code_map": {
                "1": "HRRR,NAM,GFS (default)",
                "2": "HRRR,NAM",
                "3": "HRRR,GFS",
                "4": "NAM,GFS",
                "5": "HRRR",
                "6": "NAM",
                "7": "GFS",
            },
            "observed_nonmissing_method_codes": sorted(observed_codes),
            "Holmes_method_crosswalk_candidate": "structured-date-local-PASS",
        }
    elif target.product == "SP2":
        rbc = _require_semantic_fields(
            contracts,
            name_pattern=r"rbc(?:_(?!.*(?:precision|uncertainty|flag|qc|dilution)).+)?",
            description_terms=("refractory black carbon",),
            label="SP2 rBC",
        )
        precision = _require_semantic_fields(
            contracts,
            name_pattern=r"rbc(?:_.*)?(?:precision|uncertainty).*|rbc_(?:precision|uncertainty)",
            description_terms=("precision",),
            label="SP2 precision",
        )
        dilution = _require_semantic_fields(
            contracts,
            name_pattern=r"(?:bc|sp2)_dilution_flag",
            description_terms=("dilution", "flag"),
            label="SP2 dilution state",
        )
        qc = _require_semantic_fields(
            contracts,
            name_pattern=r"(?:sp2_)?(?:qc|quality)_flag|(?:sp2_)?flag_(?:qc|quality)",
            description_terms=("flag",),
            label="SP2 QC",
        )
        role = {
            "rBC_field_contracts": rbc,
            "precision_field_contracts": precision,
            "dilution_state_field_contracts": dilution,
            "QC_field_contracts": qc,
            "revision_local_header_sha256": sha256_bytes(parsed.header),
            "revision_local_payload_role": f"{target.date}-{target.revision}",
            "AOP_dilution_used_as_SP2_magnitude": False,
        }
    elif target.product == "AMS":
        organic = _require_semantic_fields(
            contracts,
            name_pattern=r"org(?:anic)?(?:_(?!.*(?:precision|uncertainty|flag|qc)).+)?",
            description_terms=("organic", "aerosol"),
            label="AMS organic aerosol",
        )
        precision = _require_semantic_fields(
            contracts,
            name_pattern=r"org(?:anic)?_(?:precision|uncertainty)",
            description_terms=("precision",),
            label="AMS precision",
        )
        cloud = _require_semantic_fields(
            contracts,
            name_pattern=r"(?:ams_)?cloud_flag|cloud_(?:flag|screen)",
            description_terms=("cloud", "flag"),
            label="AMS cloud flag",
        )
        qc = _require_semantic_fields(
            contracts,
            name_pattern=r"(?:ams_)?(?:qc|quality)_flag|(?:ams_)?flag_(?:qc|quality)",
            description_terms=("flag",),
            label="AMS QC",
        )
        detection_lines = _matching_header_lines(parsed, ("detection limit",))
        if len(detection_lines) != 1:
            raise AcquisitionError("AMS detection-limit semantics are not unique and exact")
        role = {
            "organic_aerosol_field_contracts": organic,
            "precision_field_contracts": precision,
            "cloud_field_contracts": cloud,
            "QC_field_contracts": qc,
            "detection_limit_evidence": detection_lines[0],
            "revision_local_header_sha256": sha256_bytes(parsed.header),
            "revision_local_payload_role": f"{target.date}-{target.revision}",
            "revision_local_role_without_fallback": True,
        }
    else:
        raise AcquisitionError(f"unexpected product {target.product!r}")

    return {
        "status": "PASS",
        "date": target.date,
        "product": target.product,
        "revision": target.revision,
        "candidate_role": target.candidate_role,
        "header_line_count": parsed.header_line_count,
        "file_format_index": parsed.file_format_index,
        "header_bytes": len(parsed.header),
        "header_sha256": sha256_bytes(parsed.header),
        "dependent_variable_count": parsed.dependent_variable_count,
        "field_count": len(parsed.fields),
        "fields": list(parsed.fields),
        "scale_factors": list(parsed.scale_factors),
        "missing_values": list(parsed.missing_values),
        "data_record_count": len(parsed.rows),
        "file_date": parsed.file_date,
        "time_domain_and_cadence": time_domain,
        "dependent_field_contracts": list(contracts.values()),
        "admissible_role": role,
        "values_transformed": False,
        "silent_coercion_or_August6_exception": False,
    }


def audit_r9(
    target: PayloadTarget, parsed: IcarttPayload
) -> tuple[dict[str, object], dict[int, tuple[str, ...]], list[dict[str, object]]]:
    if target.product != "R9":
        raise AcquisitionError("audit_r9 received a non-R9 target")
    lookup = _field_lookup(parsed)
    sentinel_lexicon = _sentinel_lexicon(parsed, f"{target.date} R9")
    smoke_codebook = _audit_binary_flag_codebook(
        parsed,
        field="smoke_flag",
        positive_term="smoke",
        label=f"{target.date} R9 smoke_flag",
    )
    background_codebook = _audit_binary_flag_codebook(
        parsed,
        field="background_flag",
        positive_term="background",
        label=f"{target.date} R9 background_flag",
    )
    smoke_positive = _decimal(
        str(smoke_codebook["positive_code_exact_decimal"]),
        "R9 smoke positive code",
    )
    smoke_negative = _decimal(
        str(smoke_codebook["negative_code_exact_decimal"]),
        "R9 smoke negative code",
    )
    background_positive = _decimal(
        str(background_codebook["positive_code_exact_decimal"]),
        "R9 background positive code",
    )
    background_negative = _decimal(
        str(background_codebook["negative_code_exact_decimal"]),
        "R9 background negative code",
    )
    records: dict[int, tuple[str, ...]] = {}
    intervals: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    previous_time: int | None = None
    previous_smoke = False
    missing_smoke_flags = 0
    missing_background_flags = 0
    for ordinal, row in enumerate(parsed.rows):
        time = _integer(row[lookup["time_start"]], f"R9 time row {ordinal}")
        if time in records:
            raise AcquisitionError(f"R9 duplicate TIME_START {time}")
        if previous_time is not None and time != previous_time + 1:
            raise AcquisitionError(f"R9 one-second cadence breaks at {time}")
        julian = _integer(row[lookup["julian_date"]], f"R9 Julian row {ordinal}")
        if julian != target.julian_day:
            raise AcquisitionError(
                f"R9 Julian day mismatch: expected {target.julian_day}, got {julian}"
            )
        records[time] = row
        smoke_raw = row[lookup["smoke_flag"]]
        background_raw = row[lookup["background_flag"]]
        smoke_kind = _sentinel_kind(smoke_raw, sentinel_lexicon)
        background_kind = _sentinel_kind(background_raw, sentinel_lexicon)
        smoke_value = _decimal(smoke_raw, "R9 smoke_flag")
        background_value = _decimal(background_raw, "R9 background_flag")
        if smoke_kind is None and smoke_value not in {smoke_negative, smoke_positive}:
            raise AcquisitionError(f"R9 smoke_flag has undeclared code {smoke_raw!r}")
        if background_kind is None and background_value not in {
            background_negative,
            background_positive,
        }:
            raise AcquisitionError(
                f"R9 background_flag has undeclared code {background_raw!r}"
            )
        if smoke_kind is not None:
            missing_smoke_flags += 1
        if background_kind is not None:
            missing_background_flags += 1
        smoke = smoke_kind is None and smoke_value == smoke_positive
        if smoke and not previous_smoke:
            current = {
                "start": time,
                "end": time,
                "record_count": 1,
                "fire_id_raw": row[lookup["fire_id"]],
                "fire_id": canonical_identifier(row[lookup["fire_id"]]),
                "transect_number_raw": row[lookup["transect_number"]],
                "transect_number": canonical_identifier(
                    row[lookup["transect_number"]]
                ),
                "plume_id_raw": row[lookup["transect_plume_number"]],
                "plume_id": canonical_identifier(
                    row[lookup["transect_plume_number"]]
                ),
            }
            intervals.append(current)
        elif smoke:
            if current is None:
                raise AcquisitionError("R9 smoke interval state is inconsistent")
            current["end"] = time
            current["record_count"] = int(current["record_count"]) + 1
            for field, key in (
                ("fire_id", "fire_id"),
                ("transect_number", "transect_number"),
                ("transect_plume_number", "plume_id"),
            ):
                if canonical_identifier(row[lookup[field]]) != current[key]:
                    raise AcquisitionError(
                        f"R9 {key} changes inside smoke interval at {time}"
                    )
        previous_time = time
        previous_smoke = smoke
    if not intervals:
        raise AcquisitionError(f"R9 {target.date} has no smoke intervals")
    keys = [
        (
            item["start"],
            item["end"],
            item["fire_id"],
            item["transect_number"],
            item["plume_id"],
        )
        for item in intervals
    ]
    if len(keys) != len(set(keys)):
        raise AcquisitionError("R9 smoke interval keys are not unique")
    return (
        {
            "status": "PASS",
            "date": target.date,
            "record_count": len(records),
            "TIME_START_first": min(records),
            "TIME_START_last": max(records),
            "cadence_seconds": 1,
            "smoke_interval_count": len(intervals),
            "fire_identifiers": sorted({str(item["fire_id"]) for item in intervals}),
            "plume_identifiers": sorted({str(item["plume_id"]) for item in intervals}),
            "smoke_flag_sentinel_count": missing_smoke_flags,
            "background_flag_sentinel_count": missing_background_flags,
            "sentinel_lexicon": {
                key: _render_decimal(value) for key, value in sentinel_lexicon.items()
            },
            "smoke_flag_codebook": smoke_codebook,
            "background_flag_codebook": background_codebook,
            "counts_or_identifiers_inherited_from_August6": False,
        },
        records,
        intervals,
    )


def _sentinel_kind(value: str, lexicon: Mapping[str, Decimal]) -> str | None:
    try:
        exact = _decimal(value, "protected-mirror sentinel candidate")
    except AcquisitionError:
        return None
    for kind, sentinel in lexicon.items():
        if exact == sentinel:
            return kind
    return None


def _mirror_values_equal(
    field: str,
    direct: str,
    merge: str,
    direct_lexicon: Mapping[str, Decimal],
    merge_lexicon: Mapping[str, Decimal],
) -> str | None:
    direct_sentinel = _sentinel_kind(direct, direct_lexicon)
    merge_sentinel = _sentinel_kind(merge, merge_lexicon)
    if direct_sentinel or merge_sentinel:
        return (
            "date-local-header-declared-sentinel-equivalence"
            if direct_sentinel == merge_sentinel
            else None
        )
    if field.casefold() in LEXICAL_IDENTIFIER_FIELDS:
        try:
            return (
                "exact-decimal-identifier"
                if canonical_identifier(direct) == canonical_identifier(merge)
                else None
            )
        except AcquisitionError:
            return None
    try:
        return "exact-decimal" if _decimal(direct, field) == _decimal(merge, field) else None
    except AcquisitionError:
        return "lexically-exact" if direct.strip() == merge.strip() else None


def audit_r9_mrg01(
    date: str,
    r9_parsed: IcarttPayload,
    r9_records: Mapping[int, tuple[str, ...]],
    merge_parsed: IcarttPayload,
) -> dict[str, object]:
    direct_lookup = _field_lookup(r9_parsed)
    merge_lookup = _field_lookup(merge_parsed)
    direct_lexicon = _sentinel_lexicon(r9_parsed, f"{date} R9")
    merge_lexicon = _sentinel_lexicon(merge_parsed, f"{date} mrg01")
    missing = [field for field in MIRROR_FIELDS if field.casefold() not in merge_lookup]
    if missing:
        raise AcquisitionError(f"{date} mrg01 lacks R9 mirror fields: {missing}")
    if "time_start" not in merge_lookup or "time_stop" not in merge_lookup:
        raise AcquisitionError(f"{date} mrg01 lacks time bounds")
    merge_records: dict[int, tuple[str, ...]] = {}
    for ordinal, row in enumerate(merge_parsed.rows):
        start = _integer(row[merge_lookup["time_start"]], "mrg01 Time_Start")
        stop = _integer(row[merge_lookup["time_stop"]], "mrg01 Time_Stop")
        if stop != start + 1:
            raise AcquisitionError(f"{date} mrg01 Time_Stop differs from start+1")
        if start in merge_records:
            raise AcquisitionError(f"{date} duplicate mrg01 Time_Start {start}")
        if ordinal and start != max(merge_records) + 1:
            raise AcquisitionError(f"{date} mrg01 one-second cadence is discontinuous")
        merge_records[start] = row
    if set(merge_records) != set(r9_records):
        raise AcquisitionError(
            f"{date} R9/mrg01 time domains are not exactly equal; "
            "no August6 terminal exception is inherited"
        )
    counts = {
        field: {
            "lexically-exact": 0,
            "exact-decimal": 0,
            "exact-decimal-identifier": 0,
            "date-local-header-declared-sentinel-equivalence": 0,
        }
        for field in MIRROR_FIELDS
    }
    mismatches: list[dict[str, object]] = []
    for time in sorted(r9_records):
        direct_row = r9_records[time]
        merge_row = merge_records[time]
        for field in MIRROR_FIELDS:
            direct = direct_row[direct_lookup[field.casefold()]]
            merge = merge_row[merge_lookup[field.casefold()]]
            explanation = _mirror_values_equal(
                field, direct, merge, direct_lexicon, merge_lexicon
            )
            if explanation is None:
                if len(mismatches) < 20:
                    mismatches.append(
                        {"TIME_START": time, "field": field, "R9": direct, "mrg01": merge}
                    )
            else:
                counts[field][explanation] += 1
    if mismatches:
        raise AcquisitionError(
            f"{date} R9/mrg01 has unexplained date-local mismatches: {mismatches}"
        )
    expected = len(r9_records)
    if any(sum(values.values()) != expected for values in counts.values()):
        raise AcquisitionError(f"{date} R9/mrg01 comparison ledger is incomplete")
    return {
        "status": "PASS",
        "date": date,
        "time_domain_relation": "exactly-equal",
        "compared_times": expected,
        "compared_fields": list(MIRROR_FIELDS),
        "comparison_counts_by_field": counts,
        "unexplained_mismatch_count": 0,
        "R9_sentinel_lexicon": {
            key: _render_decimal(value) for key, value in direct_lexicon.items()
        },
        "mrg01_sentinel_lexicon": {
            key: _render_decimal(value) for key, value in merge_lexicon.items()
        },
        "August6_fixed_format_or_terminal_exception_inherited": False,
        "R9_values_are_authoritative": True,
        "mrg01_fire_fields_role": "protected-QA-mirrors-only",
    }


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


def _cell_value(cell: ET.Element, shared: Sequence[str]) -> tuple[str, str]:
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


def audit_r12_workbook(
    payload: bytes, julian_days: Iterable[int]
) -> tuple[dict[str, object], dict[int, list[dict[str, object]]]]:
    requested_days = tuple(sorted(set(julian_days)))
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as error:
        raise AcquisitionError(f"R12 is not a valid OOXML ZIP: {error}") from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise AcquisitionError("R12 contains duplicate OOXML member names")
        for info in infos:
            _safe_zip_name(info.filename)
            if info.flag_bits & 0x1:
                raise AcquisitionError(f"R12 encrypted OOXML member: {info.filename}")
        if archive.testzip() is not None:
            raise AcquisitionError("R12 OOXML CRC validation failed")
        if sum(info.file_size for info in infos) > 50_000_000:
            raise AcquisitionError("R12 OOXML uncompressed size exceeds bound")
        lowered = {name.casefold() for name in names}
        if any(
            "vbaproject" in name
            or name.endswith(".bin")
            or name.startswith("xl/externallinks/")
            for name in lowered
        ):
            raise AcquisitionError("R12 contains a macro or external-link part")
        required = {
            "[Content_Types].xml",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
        }
        missing = required - set(names)
        if missing:
            raise AcquisitionError(f"R12 is missing OOXML parts: {sorted(missing)}")
        for name in names:
            if not name.endswith(".rels"):
                continue
            relationships = _xml(archive.read(name), name)
            if any(
                rel.get("TargetMode", "").casefold() == "external"
                for rel in relationships.findall(
                    f"{{{_PACKAGE_REL_NS}}}Relationship"
                )
            ):
                raise AcquisitionError("R12 contains external relationships")

        workbook = _xml(archive.read("xl/workbook.xml"), "xl/workbook.xml")
        sheets = workbook.findall(f".//{{{_MAIN_NS}}}sheet")
        if len(sheets) != 1:
            raise AcquisitionError("R12 must contain exactly one worksheet")
        relationship_id = sheets[0].get(f"{{{_OFFICE_REL_NS}}}id")
        relationships = _xml(
            archive.read("xl/_rels/workbook.xml.rels"),
            "xl/_rels/workbook.xml.rels",
        )
        relationship_targets = {
            rel.get("Id"): rel.get("Target", "")
            for rel in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
        }
        if relationship_id not in relationship_targets:
            raise AcquisitionError("R12 worksheet relationship is unresolved")
        sheet_path = posixpath.normpath(
            posixpath.join("xl", relationship_targets[relationship_id])
        )
        _safe_zip_name(sheet_path)
        if sheet_path not in names:
            raise AcquisitionError(f"R12 worksheet part is absent: {sheet_path}")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared = _shared_strings(
                _xml(archive.read("xl/sharedStrings.xml"), "xl/sharedStrings.xml")
            )
        sheet = _xml(archive.read(sheet_path), sheet_path)
        if sheet.findall(f".//{{{_MAIN_NS}}}f"):
            raise AcquisitionError("R12 contains formulas")
        parsed_rows: dict[int, dict[int, tuple[str, str]]] = {}
        for row in sheet.findall(f".//{{{_MAIN_NS}}}row"):
            number = int(row.get("r", "0"))
            cells: dict[int, tuple[str, str]] = {}
            for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                cells[_cell_column(cell.get("r", ""))] = _cell_value(cell, shared)
            parsed_rows[number] = cells

        header_matches = []
        for number, cells in parsed_rows.items():
            values = tuple(
                cells.get(column, ("missing", ""))[1]
                for column in range(1, len(R12_HEADERS) + 1)
            )
            if values == R12_HEADERS:
                header_matches.append(number)
        if len(header_matches) != 1:
            raise AcquisitionError(
                f"R12 expected one exact main-table header, found {len(header_matches)}"
            )
        header_row = header_matches[0]
        rows_by_day: dict[int, list[dict[str, object]]] = {
            day: [] for day in requested_days
        }
        for number in sorted(parsed_rows):
            if number <= header_row:
                continue
            cells = parsed_rows[number]

            def value(column: int) -> str:
                return cells.get(column, ("missing", ""))[1]

            raw_julian = value(19)
            if not raw_julian:
                continue
            try:
                julian = _integer(raw_julian, f"R12 S{number}")
            except AcquisitionError:
                continue
            if julian not in rows_by_day:
                continue
            fire_raw = value(4)
            transect_raw = value(20)
            plume_raw = value(21)
            start = _integer(value(5), f"R12 E{number}")
            end = _integer(value(6), f"R12 F{number}")
            if end < start:
                raise AcquisitionError(f"R12 row {number} has end before start")
            rows_by_day[julian].append(
                {
                    "worksheet_row": number,
                    "julian_day": julian,
                    "fire_name": value(3),
                    "fire_id_raw": fire_raw,
                    "fire_id": canonical_identifier(fire_raw),
                    "start_raw": value(5),
                    "start": start,
                    "end_raw": value(6),
                    "end": end,
                    "record_count": end - start + 1,
                    "transect_type_raw": value(8),
                    "transect_number_raw": transect_raw,
                    "transect_number": canonical_identifier(transect_raw),
                    "plume_id_raw": plume_raw,
                    "plume_id": canonical_identifier(plume_raw),
                    "mean_wind_age_raw": value(27) or None,
                }
            )
        for day, rows in rows_by_day.items():
            if not rows:
                raise AcquisitionError(f"R12 has no rows for Julian day {day}")
            keys = [
                (
                    row["start"],
                    row["end"],
                    row["fire_id"],
                    row["transect_number"],
                    row["plume_id"],
                )
                for row in rows
            ]
            if len(keys) != len(set(keys)):
                raise AcquisitionError(f"R12 Julian day {day} has duplicate interval keys")
        return (
            {
                "status": "PASS",
                "file_type": "OOXML-XLSX",
                "worksheet_name": sheets[0].get("name", ""),
                "table_header_row": header_row,
                "formula_count": 0,
                "external_relationship_count": 0,
                "requested_julian_days": list(requested_days),
                "rows_by_julian_day": {
                    str(day): [int(row["worksheet_row"]) for row in rows]
                    for day, rows in rows_by_day.items()
                },
                "counts_row_ranges_or_identifiers_inherited_from_August6": False,
                "raw_lexemes_preserved": True,
                "binary_float_identifier_keying": False,
            },
            rows_by_day,
        )


def compare_r9_r12_intervals(
    date: str,
    r9_intervals: Sequence[Mapping[str, object]],
    r12_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    keys = ("start", "end", "record_count", "fire_id", "transect_number", "plume_id")
    left = sorted(tuple(item[key] for key in keys) for item in r9_intervals)
    right = sorted(tuple(item[key] for key in keys) for item in r12_rows)
    if left != right:
        raise AcquisitionError(
            f"{date} R9/R12 exact interval mapping differs: "
            f"R9={left[:5]!r}, R12={right[:5]!r}"
        )
    return {
        "status": "PASS",
        "date": date,
        "interval_count": len(left),
        "comparison_fields": list(keys),
        "interval_semantics": "inclusive",
        "one_to_one": True,
        "nearest_fill_interpolation_or_binary_float_keying": False,
    }


def verify_documentary_authorities(
    spec: DocumentarySpec = DOCUMENTARY_SPEC,
) -> tuple[dict[str, object], dict[str, Path]]:
    root = _lexical_absolute(spec.root)
    root_metadata = _lstat_or_none(root)
    if root_metadata is None or not stat.S_ISDIR(root_metadata.st_mode):
        raise AcquisitionError(f"documentary authority root is absent: {root}")
    seal = root / spec.seal_name
    manifest = root / spec.manifest_name
    _require_regular_file(seal, "documentary authority seal")
    _require_regular_file(manifest, "documentary authority manifest")
    if sha256_file(seal) != spec.seal_sha256:
        raise AcquisitionError("documentary seal SHA-256 mismatch")
    if sha256_file(manifest) != spec.manifest_sha256:
        raise AcquisitionError("documentary manifest SHA-256 mismatch")
    try:
        seal_record = json.loads(seal.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AcquisitionError(f"documentary seal is not valid JSON: {error}") from error
    if seal_record.get("status") != "SEALED":
        raise AcquisitionError("documentary authority seal is not SEALED")
    if seal_record.get("manifest_sha256") != spec.manifest_sha256:
        raise AcquisitionError("documentary seal does not pin the manifest")
    paths: dict[str, Path] = {}
    records: list[dict[str, object]] = []
    for item in spec.files:
        path = root / item.relative_path
        if not path.is_file() or path.is_symlink():
            raise AcquisitionError(f"documentary file is absent or non-regular: {path}")
        if sha256_file(path) != item.sha256:
            raise AcquisitionError(f"documentary file SHA-256 mismatch: {item.key}")
        paths[item.key] = path
        records.append(
            {
                "key": item.key,
                "path": str(path),
                "sha256": item.sha256,
                "role": item.role,
                "mode": "read-only-exact-byte-reuse",
                "copied_or_resealed": False,
            }
        )
    return (
        {
            "status": "PASS",
            "root": str(root),
            "seal_sha256": spec.seal_sha256,
            "manifest_sha256": spec.manifest_sha256,
            "files": records,
            "August6_date_local_applicability_inherited": False,
        },
        paths,
    )


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _require_regular_file(path: Path, label: str) -> None:
    metadata = _lstat_or_none(path)
    if metadata is None or not stat.S_ISREG(metadata.st_mode):
        raise AcquisitionError(f"{label} is absent, a symlink, or non-regular: {path}")


def _write_new(path: Path, payload: bytes) -> None:
    missing: list[Path] = []
    cursor = path.parent
    while _lstat_or_none(cursor) is None:
        missing.append(cursor)
        if cursor.parent == cursor:
            raise AcquisitionError(f"cannot establish parent directory for {path}")
        cursor = cursor.parent
    cursor_metadata = cursor.lstat()
    if not stat.S_ISDIR(cursor_metadata.st_mode):
        raise AcquisitionError(f"publication parent is a symlink or non-directory: {cursor}")
    for directory in reversed(missing):
        directory.mkdir()
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise AcquisitionError(f"created publication component is not a directory: {directory}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AcquisitionError(f"publication entry is not regular: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _tree_inventory(root: Path) -> tuple[set[str], set[str]]:
    root_metadata = _lstat_or_none(root)
    if root_metadata is None or not stat.S_ISDIR(root_metadata.st_mode):
        raise AcquisitionError(f"attempt root is absent, a symlink, or non-directory: {root}")
    files: set[str] = set()
    directories: set[str] = set()

    def visit(directory: Path, relative: PurePosixPath) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            raise AcquisitionError(f"cannot inventory {directory}: {error}") from error
        for entry in entries:
            child_relative = relative / entry.name
            if any(part.startswith(".") for part in child_relative.parts):
                raise AcquisitionError(
                    f"hidden or partial publication entry is prohibited: {child_relative}"
                )
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise AcquisitionError(f"publication symlink is prohibited: {child_relative}")
            if stat.S_ISDIR(metadata.st_mode):
                directories.add(child_relative.as_posix())
                visit(Path(entry.path), child_relative)
            elif stat.S_ISREG(metadata.st_mode):
                files.add(child_relative.as_posix())
            else:
                raise AcquisitionError(
                    f"publication special file is prohibited: {child_relative}"
                )

    visit(root, PurePosixPath())
    return files, directories


def _audit_exact_inventory(root: Path, expected_files: set[str]) -> dict[str, object]:
    files, directories = _tree_inventory(root)
    expected_directories: set[str] = set()
    for relative_file in expected_files:
        parent = PurePosixPath(relative_file).parent
        while parent != PurePosixPath("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    missing = sorted(expected_files - files)
    extras = sorted(files - expected_files)
    missing_directories = sorted(expected_directories - directories)
    extra_directories = sorted(directories - expected_directories)
    if missing or extras or missing_directories or extra_directories:
        raise AcquisitionError(
            "exact publication inventory differs: "
            f"missing_files={missing}, extra_files={extras}, "
            f"missing_directories={missing_directories}, "
            f"extra_directories={extra_directories}"
        )
    return {
        "status": "PASS",
        "regular_file_count": len(files),
        "directory_count": len(directories),
        "relative_files": sorted(files),
        "relative_directories": sorted(directories),
        "symlink_special_hidden_partial_or_extra_count": 0,
    }


def _seal_attempt_noreplace(
    destination: Path,
    seal_payload: bytes,
    expected_preseal_files: set[str],
) -> dict[str, object]:
    """Atomically add the final seal after an exact regular-file inventory."""
    preseal = _audit_exact_inventory(destination, expected_preseal_files)
    nonce = secrets.token_hex(16)
    seal = destination / FINAL_SEAL_NAME
    temporary_seal = destination / f".{FINAL_SEAL_NAME}.{nonce}.partial"
    owned_seal_identity: tuple[int, int] | None = None

    def remove_owned_seal() -> None:
        metadata = _lstat_or_none(seal)
        if (
            owned_seal_identity is not None
            and metadata is not None
            and stat.S_ISREG(metadata.st_mode)
            and (metadata.st_dev, metadata.st_ino) == owned_seal_identity
        ):
            seal.unlink()

    try:
        _write_new(temporary_seal, seal_payload)
        os.link(temporary_seal, seal, follow_symlinks=False)
        seal_metadata = seal.lstat()
        temporary_metadata = temporary_seal.lstat()
        if (
            not stat.S_ISREG(seal_metadata.st_mode)
            or (seal_metadata.st_dev, seal_metadata.st_ino)
            != (temporary_metadata.st_dev, temporary_metadata.st_ino)
            or seal.read_bytes() != seal_payload
        ):
            raise AcquisitionError("final seal no-replace publication is not exact")
        owned_seal_identity = (seal_metadata.st_dev, seal_metadata.st_ino)
    except BaseException:
        seal_metadata = _lstat_or_none(seal)
        temporary_metadata = _lstat_or_none(temporary_seal)
        if (
            seal_metadata is not None
            and temporary_metadata is not None
            and stat.S_ISREG(seal_metadata.st_mode)
            and seal_metadata.st_dev == temporary_metadata.st_dev
            and seal_metadata.st_ino == temporary_metadata.st_ino
        ):
            seal.unlink()
        try:
            temporary_seal.unlink()
        except FileNotFoundError:
            pass
        raise
    try:
        temporary_seal.unlink()
    except BaseException:
        remove_owned_seal()
        raise
    try:
        final = _audit_exact_inventory(
            destination, expected_preseal_files | {FINAL_SEAL_NAME}
        )
    except BaseException:
        remove_owned_seal()
        raise
    try:
        _fsync_directory(destination)
        _fsync_directory(destination.parent)
    except BaseException:
        remove_owned_seal()
        raise
    return {"preseal": preseal, "final": final}


def _validate_attempt_destination(
    destination: Path, expected_base: Path
) -> tuple[Path, int]:
    destination = _lexical_absolute(destination)
    expected_base = _lexical_absolute(expected_base)
    if destination.parent != expected_base.parent:
        raise AcquisitionError("attempt root parent differs from the frozen contract")
    expression = re.compile(re.escape(expected_base.name) + r"(?:-retry([1-9]\d*))?")
    match = expression.fullmatch(destination.name)
    if match is None:
        raise AcquisitionError("attempt root is neither frozen v1 nor fresh -retryN")
    retry_number = int(match.group(1)) if match.group(1) is not None else 0
    parent_metadata = _lstat_or_none(destination.parent)
    if parent_metadata is None or not stat.S_ISDIR(parent_metadata.st_mode):
        raise FileNotFoundError(f"acquisition parent is absent or unsafe: {destination.parent}")
    if _lstat_or_none(destination) is not None:
        raise FileExistsError(f"refusing to overwrite or follow acquisition {destination}")
    if retry_number:
        for number in range(retry_number):
            prior = expected_base if number == 0 else Path(f"{expected_base}-retry{number}")
            metadata = _lstat_or_none(prior)
            if metadata is None or not stat.S_ISDIR(metadata.st_mode):
                raise AcquisitionError(f"retry sequence lacks retained failed root: {prior}")
            stop = prior / STOP_RECORD_NAME
            _require_regular_file(stop, "retained failed-attempt STOP record")
            if _lstat_or_none(prior / FINAL_SEAL_NAME) is not None:
                raise AcquisitionError(f"retry prohibited after a sealed successful attempt: {prior}")
    return destination, retry_number


def verify_frozen_parent_files(
    parent_files: Sequence[tuple[str, Path, str]] = FROZEN_PARENT_FILES,
) -> tuple[list[dict[str, str]], str]:
    keys = [item[0] for item in parent_files]
    lexical_paths = [str(_lexical_absolute(item[1])) for item in parent_files]
    if len(keys) != len(set(keys)) or len(lexical_paths) != len(set(lexical_paths)):
        raise AcquisitionError("frozen parent inventory contains a duplicate key or path")
    records: list[dict[str, str]] = []
    for key, path, expected_hash in parent_files:
        if not _valid_sha256(expected_hash):
            raise AcquisitionError(f"frozen parent digest is malformed: {key}")
        lexical = _lexical_absolute(path)
        _require_regular_file(lexical, f"frozen parent {key}")
        observed = sha256_file(lexical)
        if observed != expected_hash:
            raise AcquisitionError(f"frozen parent SHA-256 mismatch: {key}")
        records.append({"key": key, "path": str(lexical), "sha256": observed})
    aggregate_payload = "".join(
        f"{record['key']}\0{record['path']}\0{record['sha256']}\n"
        for record in records
    ).encode("utf-8")
    return records, sha256_bytes(aggregate_payload)


def _load_json_evidence(
    path: Path, expected_sha256: str, label: str
) -> tuple[dict[str, object], str]:
    if not _valid_sha256(expected_sha256):
        raise AcquisitionError(f"{label} SHA-256 is not an exact lowercase digest")
    lexical = _lexical_absolute(path)
    _require_regular_file(lexical, label)
    payload = lexical.read_bytes()
    if sha256_bytes(payload) != expected_sha256:
        raise AcquisitionError(f"{label} SHA-256 mismatch")
    try:
        parsed = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AcquisitionError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise AcquisitionError(f"{label} must be a JSON object")
    return parsed, str(lexical)


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise AcquisitionError(f"{label} is not an ISO UTC string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AcquisitionError(f"{label} is not valid ISO time") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AcquisitionError(f"{label} is not explicitly UTC")
    return parsed


def _verify_preflight_evidence(
    record: Mapping[str, object],
    *,
    contract_sha256: str,
    source_path: Path,
    source_sha256: str,
    test_path: Path,
    test_sha256: str,
    interpreter_sha256: str,
    attempt_root: Path,
    parent_aggregate_sha256: str,
) -> dict[str, object]:
    required = {
        "schema_version": 1,
        "evidence_kind": "phase1-authority-tooling-preflight",
        "status": "PASS",
        "contract_sha256": contract_sha256,
        "source_path": str(_lexical_absolute(source_path)),
        "source_sha256": source_sha256,
        "test_path": str(_lexical_absolute(test_path)),
        "test_sha256": test_sha256,
        "interpreter_path": str(FROZEN_PYTHON),
        "interpreter_sha256": interpreter_sha256,
        "attempt_root": str(attempt_root),
        "frozen_parent_inventory_sha256": parent_aggregate_sha256,
        "focused_tests_verdict": "PASS",
        "independent_code_audit_verdict": "PASS",
        "contract_audit_verdict": "PASS",
    }
    mismatches = {
        key: {"expected": expected, "observed": record.get(key)}
        for key, expected in required.items()
        if record.get(key) != expected
    }
    auditor = record.get("independent_code_auditor")
    if not isinstance(auditor, str) or not auditor.strip():
        mismatches["independent_code_auditor"] = {
            "expected": "nonempty-string",
            "observed": auditor,
        }
    if mismatches:
        raise AcquisitionError(f"tooling/preflight evidence mismatch: {mismatches}")
    return {key: record[key] for key in required} | {
        "independent_code_auditor": auditor
    }


def _verify_execution_authority(
    record: Mapping[str, object],
    *,
    now: datetime,
    contract_sha256: str,
    source_sha256: str,
    test_sha256: str,
    interpreter_sha256: str,
    attempt_root: Path,
    preflight_evidence_sha256: str,
) -> dict[str, object]:
    required = {
        "schema_version": 1,
        "evidence_kind": "explicit-same-turn-execution-authority",
        "status": "AUTHORIZED",
        "action": "retrieve-audit-and-seal-exact-twelve-payload-phase1-bundle-only",
        "contract_sha256": contract_sha256,
        "source_sha256": source_sha256,
        "test_sha256": test_sha256,
        "interpreter_path": str(FROZEN_PYTHON),
        "interpreter_sha256": interpreter_sha256,
        "attempt_root": str(attempt_root),
        "preflight_evidence_sha256": preflight_evidence_sha256,
        "same_turn": True,
    }
    mismatches = {
        key: {"expected": expected, "observed": record.get(key)}
        for key, expected in required.items()
        if record.get(key) != expected
    }
    authority_id = record.get("authority_id")
    authorized_by = record.get("authorized_by")
    if not isinstance(authority_id, str) or not authority_id.strip():
        mismatches["authority_id"] = {"expected": "nonempty-string", "observed": authority_id}
    if not isinstance(authorized_by, str) or not authorized_by.strip():
        mismatches["authorized_by"] = {"expected": "nonempty-string", "observed": authorized_by}
    issued = _parse_utc(record.get("issued_utc"), "authority issued_utc")
    expires = _parse_utc(record.get("expires_utc"), "authority expires_utc")
    if expires <= issued or (expires - issued).total_seconds() > 21600:
        mismatches["authority_window"] = {
            "expected": "positive and no longer than 21600 seconds",
            "observed": [record.get("issued_utc"), record.get("expires_utc")],
        }
    if now < issued or now > expires:
        mismatches["authority_current_time"] = {
            "expected": "within authority window",
            "observed": now.isoformat(),
        }
    if mismatches:
        raise AcquisitionError(f"explicit execution-authority evidence mismatch: {mismatches}")
    return {key: record[key] for key in required} | {
        "authority_id": authority_id,
        "authorized_by": authorized_by,
        "issued_utc": record["issued_utc"],
        "expires_utc": record["expires_utc"],
    }


def _record_failed_attempt(
    destination: Path,
    *,
    error: BaseException,
    phase: str,
    clock: Callable[[], str],
) -> None:
    retained_hidden_partials = sorted(
        entry.name
        for entry in destination.iterdir()
        if entry.name.startswith(f".{FINAL_SEAL_NAME}.")
        and entry.name.endswith(".partial")
    )
    stop_payload = _render_json(
        {
            "schema_version": 1,
            "status": "FAILED-UNSEALED-DO-NOT-REUSE",
            "attempt_root": str(destination),
            "failed_phase": phase,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "stopped_utc": clock(),
            "retry_policy": "retain-this-root-and-use-fresh-retryN",
            "final_seal_present": _lstat_or_none(destination / FINAL_SEAL_NAME) is not None,
            "retained_hidden_partial_names": retained_hidden_partials,
            "failure_recorder_deleted_attempt_entries": False,
        }
    )
    _write_new(destination / STOP_RECORD_NAME, stop_payload)


def _render_json(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _documentary_record(
    documentary_audit: Mapping[str, object], key: str
) -> Mapping[str, object]:
    files = documentary_audit.get("files")
    if not isinstance(files, list):
        raise AcquisitionError("documentary audit lacks its exact file ledger")
    matches = [item for item in files if isinstance(item, dict) and item.get("key") == key]
    if len(matches) != 1:
        raise AcquisitionError(f"documentary audit does not contain one exact {key} record")
    return matches[0]


def audit_fsu_holmes_crosswalk(
    date: str,
    header_audit: Mapping[str, object],
    documentary_audit: Mapping[str, object],
    *,
    expected_sha256: str,
    expected_role: str,
) -> dict[str, object]:
    if header_audit.get("date") != date or header_audit.get("product") != "FSU":
        raise AcquisitionError("FSU/Holmes crosswalk received the wrong local header audit")
    holmes = _documentary_record(documentary_audit, "Holmes")
    if (
        holmes.get("sha256") != expected_sha256
        or holmes.get("role") != expected_role
    ):
        raise AcquisitionError("Holmes documentary role or byte identity changed")
    role = header_audit.get("admissible_role")
    if not isinstance(role, dict) or role.get("Holmes_method_crosswalk_candidate") != "structured-date-local-PASS":
        raise AcquisitionError("FSU local field/unit/method/scope proof is incomplete")
    return {
        "status": "PASS",
        "date": date,
        "FSU_header_sha256": header_audit["header_sha256"],
        "Holmes_sha256": holmes["sha256"],
        "Holmes_reused_role": holmes["role"],
        "field_unit_scope_contracts": role["field_unit_scope_contracts"],
        "method_code_map": role["method_code_map"],
        "observed_nonmissing_method_codes": role["observed_nonmissing_method_codes"],
        "archived_field": "smoke_agemethod",
        "document_field": "smoke_age_method",
        "spelling_difference_explicit": True,
        "values_authority": "date-local-FSU-bytes-only",
        "documentary_scope": "trajectory-ensemble-method-and-provisional-uncertainty-semantics-only",
        "mean_wind_age_or_distance_substitution": False,
        "August6_crosswalk_conclusion_inherited": False,
    }


def audit_aop_zeng_crosswalk(
    date: str,
    header_audit: Mapping[str, object],
    documentary_audit: Mapping[str, object],
    *,
    expected_sha256: str,
    expected_role: str,
) -> dict[str, object]:
    if header_audit.get("date") != date or header_audit.get("product") != "AOP":
        raise AcquisitionError("AOP/Zeng crosswalk received the wrong local header audit")
    zeng = _documentary_record(documentary_audit, "Zeng")
    if (
        zeng.get("sha256") != expected_sha256
        or zeng.get("role") != expected_role
    ):
        raise AcquisitionError("Zeng documentary role or byte identity changed")
    role = header_audit.get("admissible_role")
    if not isinstance(role, dict) or role.get("Zeng_reference_state_applicability_candidate") != "structured-date-local-PASS":
        raise AcquisitionError("AOP local family/wavelength/reference-state proof is incomplete")
    if role.get("wavelengths_nm") != [405, 532, 664] or not role.get("band_units_identical"):
        raise AcquisitionError("AOP dry-band structured crosswalk is incomplete")
    return {
        "status": "PASS",
        "date": date,
        "AOP_header_sha256": header_audit["header_sha256"],
        "Zeng_sha256": zeng["sha256"],
        "Zeng_reused_role": zeng["role"],
        "same_family": "date-local-header-proved-dry-PM2.5-PAS-family",
        "wavelengths_nm": role["wavelengths_nm"],
        "band_field_contracts": role["band_field_contracts"],
        "reference_state_evidence": role["reference_state_evidence"],
        "reference_state": {"temperature_K": 273, "pressure_mbar": 1013},
        "AOP_quality_and_RH_contracts": {
            "quality": role["quality_field_contracts"],
            "relative_humidity": role["relative_humidity_field_contracts"],
        },
        "AOP_dilution_contract": role["AOP_dilution_contract"],
        "AOP_dilution_used_as_SP2_magnitude": False,
        "per_record_low_signal_precision_inferred": False,
        "August6_applicability_conclusion_inherited": False,
    }


def acquire(
    destination: Path,
    *,
    contract_path: Path,
    expected_contract_sha256: str,
    expected_source_sha256: str,
    expected_test_sha256: str,
    expected_interpreter_sha256: str,
    preflight_evidence_path: Path,
    expected_preflight_evidence_sha256: str,
    execution_authority_path: Path,
    expected_execution_authority_sha256: str,
    fetcher: Callable[[str], bytes | FetchResult] = fetch_resource,
    clock: Callable[[], str] = _utc_now,
    expected_destination: Path = DESTINATION,
    expected_contract_path: Path = CONTRACT_PATH,
    documentary_spec: DocumentarySpec = DOCUMENTARY_SPEC,
    targets: Sequence[PayloadTarget] = TARGETS,
    pages: Sequence[PageTarget] = PAGES,
    parent_files: Sequence[tuple[str, Path, str]] = FROZEN_PARENT_FILES,
    enforce_runtime: bool = True,
) -> dict[str, object]:
    """Execute the frozen acquisition only after every preflight gate passes."""
    contract_path = _lexical_absolute(contract_path)
    expected_contract_path = _lexical_absolute(expected_contract_path)
    production_contract = contract_path == _lexical_absolute(CONTRACT_PATH)
    if production_contract and (
        expected_contract_path != _lexical_absolute(CONTRACT_PATH)
        or _lexical_absolute(expected_destination) != _lexical_absolute(DESTINATION)
        or documentary_spec != DOCUMENTARY_SPEC
        or tuple(parent_files) != FROZEN_PARENT_FILES
        or tuple(targets) != TARGETS
        or tuple(pages) != PAGES
        or fetcher is not fetch_resource
        or clock is not _utc_now
        or not enforce_runtime
    ):
        raise AcquisitionError(
            "production frozen contract prohibits synthetic/test dependency injection"
        )
    destination, retry_number = _validate_attempt_destination(
        destination, expected_destination
    )
    if contract_path != expected_contract_path:
        raise AcquisitionError("contract path differs from the frozen contract")
    _require_regular_file(contract_path, "frozen acquisition contract")
    for label, digest in (
        ("contract", expected_contract_sha256),
        ("source", expected_source_sha256),
        ("test", expected_test_sha256),
        ("interpreter", expected_interpreter_sha256),
        ("preflight evidence", expected_preflight_evidence_sha256),
        ("execution authority", expected_execution_authority_sha256),
    ):
        if not _valid_sha256(digest):
            raise AcquisitionError(f"{label} SHA-256 is not an exact lowercase digest")
    contract_bytes = contract_path.read_bytes()
    contract_hash = sha256_bytes(contract_bytes)
    if contract_hash != expected_contract_sha256:
        raise AcquisitionError("contract SHA-256 mismatch")
    if contract_hash == CONTRACT_SHA256 and not production_contract:
        raise AcquisitionError(
            "frozen production contract bytes are prohibited outside the exact vault path"
        )
    if expected_contract_path == _lexical_absolute(CONTRACT_PATH) and contract_hash != CONTRACT_SHA256:
        raise AcquisitionError("compiled frozen contract SHA-256 mismatch")
    tool_path = _lexical_absolute(Path(__file__))
    test_path = tool_path.with_name(
        "test_fetch_firex_aq_phase1_authorities_20190802_20190803.py"
    )
    _require_regular_file(tool_path, "acquisition source")
    _require_regular_file(test_path, "acquisition focused tests")
    if sha256_file(tool_path) != expected_source_sha256:
        raise AcquisitionError("source SHA-256 differs from reviewed evidence")
    if sha256_file(test_path) != expected_test_sha256:
        raise AcquisitionError("test SHA-256 differs from reviewed evidence")
    if enforce_runtime:
        if _lexical_absolute(Path(sys.executable)) != _lexical_absolute(FROZEN_PYTHON):
            raise AcquisitionError(f"wrong Python runtime: {sys.executable}")
        _require_regular_file(FROZEN_PYTHON, "frozen Python interpreter")
        if sha256_file(FROZEN_PYTHON) != expected_interpreter_sha256:
            raise AcquisitionError("interpreter SHA-256 differs from reviewed evidence")
    if tuple(targets) != TARGETS or tuple(pages) != PAGES:
        raise AcquisitionError("frozen target or official-page inventory changed")
    parent_records, parent_aggregate = verify_frozen_parent_files(parent_files)
    preflight_record, preflight_evidence_lexical = _load_json_evidence(
        preflight_evidence_path,
        expected_preflight_evidence_sha256,
        "released tooling/preflight evidence",
    )
    preflight_summary = _verify_preflight_evidence(
        preflight_record,
        contract_sha256=contract_hash,
        source_path=tool_path,
        source_sha256=expected_source_sha256,
        test_path=test_path,
        test_sha256=expected_test_sha256,
        interpreter_sha256=expected_interpreter_sha256,
        attempt_root=destination,
        parent_aggregate_sha256=parent_aggregate,
    )
    authority_record, execution_authority_lexical = _load_json_evidence(
        execution_authority_path,
        expected_execution_authority_sha256,
        "explicit same-turn execution authority",
    )
    authority_clock = clock()
    authority_summary = _verify_execution_authority(
        authority_record,
        now=_parse_utc(authority_clock, "execution clock"),
        contract_sha256=contract_hash,
        source_sha256=expected_source_sha256,
        test_sha256=expected_test_sha256,
        interpreter_sha256=expected_interpreter_sha256,
        attempt_root=destination,
        preflight_evidence_sha256=expected_preflight_evidence_sha256,
    )

    documentary_audit, documentary_paths = verify_documentary_authorities(
        documentary_spec
    )
    r12_payload = documentary_paths["R12"].read_bytes()
    r12_audit, r12_rows = audit_r12_workbook(
        r12_payload, (target.julian_day for target in targets)
    )
    expected_preseal_files = {
        "acquisition_contract.yml",
        *(page.relative_path for page in pages),
        *(
            f"raw/{target.date.replace('-', '')}/{target.filename}"
            for target in targets
        ),
        *(
            f"headers/{target.date.replace('-', '')}/{target.filename}.header"
            for target in targets
        ),
        "audits/header_schema_audit.json",
        "audits/documentary_authority_audit.json",
        "audits/date_local_semantic_audit.json",
        MANIFEST_NAME,
    }
    if len(expected_preseal_files) != 32:
        raise AcquisitionError(
            f"compiled successful pre-seal inventory is not 32 files: {len(expected_preseal_files)}"
        )
    destination.mkdir()
    if not stat.S_ISDIR(destination.lstat().st_mode):
        raise AcquisitionError("exclusively created attempt root is not a directory")
    phase = "exclusive-attempt-root-created"
    try:
        _write_new(destination / "acquisition_contract.yml", contract_bytes)
        phase = "official-page-retrieval"
        page_map = {page.key: page for page in pages}
        page_payloads: dict[str, bytes] = {}
        page_records: list[dict[str, object]] = []
        for page in pages:
            response = _normalize_response(fetcher(page.url), page.url)
            if response.http_status is None:
                raise AcquisitionError(f"formal HTTP status absent for {page.key}")
            page_payloads[page.key] = response.payload
            _write_new(destination / page.relative_path, response.payload)
            page_records.append(
                {
                    "key": page.key,
                    "requested_url": page.url,
                    "final_url": response.final_url,
                    "http_status": response.http_status,
                    "content_type": response.headers.get("content-type"),
                    "retrieved_utc": clock(),
                    "bytes": len(response.payload),
                    "sha256": sha256_bytes(response.payload),
                    "relative_path": page.relative_path,
                }
            )
        discovered = discover_payload_urls(
            page_payloads, targets=targets, pages=pages
        )
        r12_live_anchor = confirm_r12_archive_anchor(page_payloads, pages=pages)
        page_hashes = {item["key"]: item["sha256"] for item in page_records}
        parsed_by_key: dict[tuple[str, str], IcarttPayload] = {}
        target_by_key = {(target.date, target.product): target for target in targets}
        payload_records: list[dict[str, object]] = []
        header_audits: list[dict[str, object]] = []
        phase = "exact-twelve-payload-retrieval-and-header-audit"
        for target in targets:
            key = (target.date, target.product)
            href, url = discovered[key]
            response = _normalize_response(fetcher(url), url)
            if response.http_status is None:
                raise AcquisitionError(f"formal HTTP status absent for {target.filename}")
            served = _served_filename(response, target.filename)
            parsed = parse_icartt(response.payload, target.date)
            header_audit = audit_product_header(target, parsed)
            parsed_by_key[key] = parsed
            header_audits.append(header_audit)
            compact = target.date.replace("-", "")
            raw_relative = Path("raw") / compact / target.filename
            header_relative = Path("headers") / compact / f"{target.filename}.header"
            _write_new(destination / raw_relative, response.payload)
            _write_new(destination / header_relative, parsed.header)
            digest = sha256_bytes(response.payload)
            payload_records.append(
                {
                    "date": target.date,
                    "product": target.product,
                    "revision": target.revision,
                    "candidate_role": target.candidate_role,
                    "filename": target.filename,
                    "archive_page_key": target.page_key,
                    "archive_page_sha256": page_hashes[target.page_key],
                    "archive_href": href,
                    "requested_url": url,
                    "final_url": response.final_url,
                    "http_status": response.http_status,
                    "served_filename": served,
                    "content_disposition": response.headers.get("content-disposition"),
                    "content_type": response.headers.get("content-type"),
                    "retrieved_utc": clock(),
                    "bytes": len(response.payload),
                    "sha256": digest,
                    "raw_relative_path": raw_relative.as_posix(),
                    "header_relative_path": header_relative.as_posix(),
                    "header_line_count": parsed.header_line_count,
                    "file_format_index": parsed.file_format_index,
                    "header_bytes": len(parsed.header),
                    "header_sha256": sha256_bytes(parsed.header),
                    "record_count": len(parsed.rows),
                    "time_domain_and_cadence": header_audit[
                        "time_domain_and_cadence"
                    ],
                    "scale_sentinel_field_semantics": header_audit[
                        "dependent_field_contracts"
                    ],
                    "source_record_identifier": {
                        "scheme": "payload-sha256:data-record-ordinal-zero-based",
                        "namespace": digest,
                        "first": f"{digest}:0",
                    },
                    "bytes_or_tokens_transformed": False,
                }
            )

        phase = "date-local-semantic-authority-audit"
        date_audits: dict[str, object] = {}
        header_by_key = {
            (str(item["date"]), str(item["product"])): item
            for item in header_audits
        }
        holmes_spec = next(item for item in documentary_spec.files if item.key == "Holmes")
        zeng_spec = next(item for item in documentary_spec.files if item.key == "Zeng")
        for date in ("2019-08-02", "2019-08-03"):
            r9_target = target_by_key[(date, "R9")]
            r9_parsed = parsed_by_key[(date, "R9")]
            r9_structure, r9_records, r9_intervals = audit_r9(
                r9_target, r9_parsed
            )
            mirror = audit_r9_mrg01(
                date,
                r9_parsed,
                r9_records,
                parsed_by_key[(date, "mrg01")],
            )
            interval = compare_r9_r12_intervals(
                date, r9_intervals, r12_rows[r9_target.julian_day]
            )
            date_audits[date] = {
                "status": "PASS",
                "R9_structure": r9_structure,
                "R9_mrg01": mirror,
                "R9_R12": interval,
                "FSU_Holmes": audit_fsu_holmes_crosswalk(
                    date,
                    header_by_key[(date, "FSU")],
                    documentary_audit,
                    expected_sha256=holmes_spec.sha256,
                    expected_role=holmes_spec.role,
                ),
                "AOP_Zeng": audit_aop_zeng_crosswalk(
                    date,
                    header_by_key[(date, "AOP")],
                    documentary_audit,
                    expected_sha256=zeng_spec.sha256,
                    expected_role=zeng_spec.role,
                ),
                "SP2_revision_local": header_by_key[(date, "SP2")],
                "AMS_revision_local": header_by_key[(date, "AMS")],
                "August6_counts_mappings_exceptions_or_applicability_inherited": False,
                "transformation_join_match_support_statistics": False,
            }

        header_payload = _render_json(
            {"status": "PASS", "payload_count": len(header_audits), "payloads": header_audits}
        )
        documentary_payload = _render_json(
            {
                "documentary_authorities": documentary_audit,
                "R12_structure": r12_audit,
                "R12_live_anchor_confirmation": r12_live_anchor,
            }
        )
        semantic_payload = _render_json(
            {
                "status": "PASS",
                "dates": date_audits,
                "all_or_nothing_two_date_release": True,
                "prospective_support_after_phase1": 0,
                "science_join_created": False,
            }
        )
        _write_new(destination / "audits/header_schema_audit.json", header_payload)
        _write_new(
            destination / "audits/documentary_authority_audit.json", documentary_payload
        )
        _write_new(destination / "audits/date_local_semantic_audit.json", semantic_payload)

        successful_relative_files = sorted(
            expected_preseal_files | {FINAL_SEAL_NAME}
        )
        inventory_sha256 = sha256_bytes(
            "".join(f"{path}\n" for path in successful_relative_files).encode("utf-8")
        )
        manifest: dict[str, object] = {
            "schema_version": 1,
            "manifest_id": (
                "stage1-firex-aq-evidence-expansion-phase1-authority-"
                "20190802-20190803-v1"
            ),
            "status": "SEALED-PHASE1-AUTHORITY-INDEPENDENT-RESULTS-AUDIT-PENDING",
            "campaign": "FIREX-AQ",
            "platform": "DC-8",
            "dates": ["2019-08-02", "2019-08-03"],
            "created_utc": clock(),
            "attempt_root": str(destination),
            "retry_number": retry_number,
            "execution_authority_id": authority_summary["authority_id"],
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
                "interpreter_path": str(FROZEN_PYTHON),
                "interpreter_sha256": expected_interpreter_sha256,
                "preflight_evidence_path": preflight_evidence_lexical,
                "preflight_evidence_sha256": expected_preflight_evidence_sha256,
                "preflight_evidence": preflight_summary,
                "execution_authority_path": execution_authority_lexical,
                "execution_authority_sha256": expected_execution_authority_sha256,
                "execution_authority": authority_summary,
                "dependency_scope": "Python-standard-library-only",
            },
            "frozen_parent_files": parent_records,
            "frozen_parent_inventory_sha256": parent_aggregate,
            "official_pages": page_records,
            "R12_live_anchor_confirmation": r12_live_anchor,
            "payloads": payload_records,
            "documentary_authorities": documentary_audit,
            "audit_artifacts": {
                "header_schema": {
                    "relative_path": "audits/header_schema_audit.json",
                    "sha256": sha256_bytes(header_payload),
                    "status": "PASS",
                },
                "documentary_authority": {
                    "relative_path": "audits/documentary_authority_audit.json",
                    "sha256": sha256_bytes(documentary_payload),
                    "status": "PASS",
                },
                "date_local_semantic": {
                    "relative_path": "audits/date_local_semantic_audit.json",
                    "sha256": sha256_bytes(semantic_payload),
                    "status": "PASS",
                },
            },
            "publication_inventory": {
                "status": "PASS-COMPILED-EXACT-LAYOUT",
                "successful_regular_file_count": 33,
                "relative_files": successful_relative_files,
                "relative_files_sha256": inventory_sha256,
                "final_seal_written_last": True,
                "stop_record_permitted_in_success": False,
                "symlinks_special_extras_hidden_partials_or_staging_residue": False,
            },
            "acceptance": {
                "payload_identities": "12/12-PASS",
                "complete_headers": "12/12-PASS",
                "both_dates_date_local_semantics": "PASS",
                "all_or_nothing_two_date_release": True,
                "August6_date_local_inheritance": False,
                "independent_results_audit": "PENDING",
                "phase2_released": False,
                "prospective_support": {
                    "independent_clusters": 0,
                    "rows": 0,
                    "model_states": 0,
                    "passing_age_bins": 0,
                },
                "transformation_join_match_support_statistics_interpretation": False,
                "model_build_Slurm_day8": False,
            },
        }
        rendered_manifest = _render_json(manifest)
        _write_new(destination / MANIFEST_NAME, rendered_manifest)
        seal_payload = _render_json(
            {
                "schema_version": 1,
                "status": "SEALED",
                "manifest_relative_path": MANIFEST_NAME,
                "manifest_sha256": sha256_bytes(rendered_manifest),
                "contract_sha256": contract_hash,
                "payload_count": len(payload_records),
                "date_count": 2,
                "official_page_snapshot_count": len(page_map),
                "exact_successful_regular_file_count": 33,
                "relative_files_sha256": inventory_sha256,
                "attempt_root": str(destination),
                "retry_number": retry_number,
                "preflight_evidence_sha256": expected_preflight_evidence_sha256,
                "execution_authority_sha256": expected_execution_authority_sha256,
                "frozen_parent_inventory_sha256": parent_aggregate,
                "sealed_utc": clock(),
            }
        )
        phase = "exact-inventory-and-final-no-replace-seal"
        inventory_result = _seal_attempt_noreplace(
            destination, seal_payload, expected_preseal_files
        )
        if inventory_result["final"]["regular_file_count"] != 33:
            raise AcquisitionError("post-seal exact inventory did not contain 33 files")
        return manifest
    except BaseException as error:
        try:
            _record_failed_attempt(
                destination, error=error, phase=phase, clock=clock
            )
        except BaseException as stop_error:
            raise AcquisitionError(
                f"attempt failed and STOP evidence could not be retained: "
                f"original={error!r}; stop={stop_error!r}"
            ) from error
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--test-sha256", required=True)
    parser.add_argument("--interpreter-sha256", required=True)
    parser.add_argument("--preflight-evidence", type=Path, required=True)
    parser.add_argument("--preflight-evidence-sha256", required=True)
    parser.add_argument("--execution-authority", type=Path, required=True)
    parser.add_argument("--execution-authority-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = acquire(
        args.output_dir,
        contract_path=args.contract,
        expected_contract_sha256=args.contract_sha256,
        expected_source_sha256=args.source_sha256,
        expected_test_sha256=args.test_sha256,
        expected_interpreter_sha256=args.interpreter_sha256,
        preflight_evidence_path=args.preflight_evidence,
        expected_preflight_evidence_sha256=args.preflight_evidence_sha256,
        execution_authority_path=args.execution_authority,
        expected_execution_authority_sha256=args.execution_authority_sha256,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
