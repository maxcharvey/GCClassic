#!/usr/bin/env python3
"""Validate the frozen FIREX-AQ logical inventory and optional ICARTT payloads.

The validator is deliberately read-only.  With no data directory it checks the
reviewed logical contract.  With ``--data-dir`` it additionally checks archive
filenames and ICARTT headers, then records byte sizes and SHA-256 values without
parsing or transforming science rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

import yaml


EXPECTED_WAVELENGTHS = [405, 532, 664]
EXPECTED_ABSORPTION_FIELDS = [
    "abs_dry_405",
    "abs_dry_532",
    "abs_dry_664",
]
EXPECTED_FLIGHT_DATES = [
    "20190722", "20190724", "20190725", "20190729", "20190730",
    "20190802", "20190803", "20190806", "20190807", "20190808",
    "20190812", "20190813", "20190815", "20190816", "20190819",
    "20190821", "20190823", "20190826", "20190829", "20190830",
    "20190831", "20190903", "20190905",
]
EXPECTED_MERGE_FILES = [
    f"FIREXAQ-mrg01-DC8_merge_{date}_R3.ict" for date in EXPECTED_FLIGHT_DATES
]
DIRECT_REQUIREMENTS = {
    "aop": EXPECTED_ABSORPTION_FIELDS,
    "smoke_age": ["smoke_age", "smoke_age_unc", "smoke_agemethod"],
    "sp2": ["BC_mass_90_550_nm", "BC_Dilution_Flag"],
    "ams": ["OA_PM1_AMS", "OA_prec_PM1_AMS", "OA_DL_PM1_AMS"],
}
MERGE_REQUIRED_ANY = [
    ("Latitude",),
    ("Longitude",),
    ("MSL_GPS_Altitude",),
    tuple(EXPECTED_ABSORPTION_FIELDS),
    ("Smoke_flag",),
    ("BC_mass_90_550_nm",),
    ("OA_PM1_AMS",),
    ("CO_DACOM",),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fail(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def load_contract(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError("inventory manifest must be a YAML mapping")
    return value


def validate_logical_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    absorption = contract.get("observation_space", {}).get("absorption", [])
    wavelengths = [entry.get("wavelength_nm") for entry in absorption]
    fields = [entry.get("field") for entry in absorption]
    units = [entry.get("unit") for entry in absorption]

    _fail(errors, wavelengths == EXPECTED_WAVELENGTHS,
          f"absorption wavelengths must be {EXPECTED_WAVELENGTHS}")
    _fail(errors, fields == EXPECTED_ABSORPTION_FIELDS,
          f"absorption fields must be {EXPECTED_ABSORPTION_FIELDS}")
    _fail(errors, units == ["Mm-1"] * 3, "all absorption units must be Mm-1")
    _fail(
        errors,
        contract.get("observation_space", {}).get("state")
        == "dry_instrument_standard_conditions",
        "observation state must be dry_instrument_standard_conditions",
    )
    _fail(
        errors,
        contract.get("observation_space", {}).get("aae", {})
        .get("endpoint_wavelengths_nm") == [405, 664],
        "AAE endpoints must be 405 and 664 nm",
    )
    _fail(
        errors,
        contract.get("observation_space", {}).get("rejected_middle_wavelength_nm")
        == 488,
        "the rejected provisional middle wavelength must remain recorded as 488 nm",
    )
    _fail(errors, contract.get("merge_files") == EXPECTED_MERGE_FILES,
          "merge_files must exactly match the frozen 23-flight R3 inventory")
    _fail(
        errors,
        contract.get("derived_products", {}).get("non_bc_absorption_residual", {})
        .get("status") == "blocked_pending_separate_bc_optical_operator",
        "non-BC absorption residual must remain blocked",
    )
    _fail(
        errors,
        contract.get("acquisition_gate", {}).get("payloads_present") is False,
        "logical inventory must remain payloads_present: false until sealed",
    )
    _fail(
        errors,
        contract.get("qc", {}).get("retain_finite_negative_absorption") is True,
        "finite negative absorption retention must be explicit",
    )
    return errors


def read_icartt_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        first = handle.readline()
        try:
            header_lines = int(first.split(",", 1)[0].strip())
        except (ValueError, IndexError) as exc:
            raise ValueError(f"{path.name}: invalid ICARTT header-count line") from exc
        if header_lines < 2:
            raise ValueError(f"{path.name}: invalid ICARTT header count {header_lines}")
        lines = [first.rstrip("\n")]
        for _ in range(header_lines - 1):
            line = handle.readline()
            if line == "":
                raise ValueError(f"{path.name}: truncated ICARTT header")
            lines.append(line.rstrip("\n"))
    return lines


def _contains_all(header: str, names: Iterable[str]) -> bool:
    return all(name in header for name in names)


def _glob_pattern(filename_pattern: str) -> str:
    return filename_pattern.replace("YYYYMMDD", "*")


def has_explicit_standard_conditions(header: str) -> bool:
    """Return true only when STP temperature and pressure are numerically defined."""

    relevant = "\n".join(
        line for line in header.splitlines()
        if "stp" in line.lower() or "standard" in line.lower()
    )
    number = r"[-+]?\d+(?:\.\d+)?"
    temperature = re.search(
        rf"{number}\s*(?:K\b|kelvin\b|deg(?:ree)?s?\s*C\b|°C\b)",
        relevant,
        flags=re.IGNORECASE,
    )
    pressure = re.search(
        rf"{number}\s*(?:hPa\b|mbar\b|mb\b|Pa\b|atm\b)",
        relevant,
        flags=re.IGNORECASE,
    )
    return temperature is not None and pressure is not None


def validate_payloads(contract: dict[str, Any], data_dir: Path) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    provenance: list[dict[str, Any]] = []
    headers: dict[Path, str] = {}

    def inspect(path: Path) -> str:
        if path not in headers:
            try:
                lines = read_icartt_header(path)
            except ValueError as exc:
                errors.append(str(exc))
                lines = []
            headers[path] = "\n".join(lines)
            provenance.append({
                "archive_filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
        return headers[path]

    for filename in EXPECTED_MERGE_FILES:
        path = data_dir / filename
        if not path.is_file():
            errors.append(f"missing merge file: {filename}")
            continue
        header = inspect(path)
        for names in MERGE_REQUIRED_ANY:
            if not _contains_all(header, names):
                errors.append(f"{filename}: missing header field(s) {list(names)}")

    authorities = contract.get("direct_product_authorities", {})
    for family, required_fields in DIRECT_REQUIREMENTS.items():
        pattern = authorities.get(family, {}).get("filename_pattern")
        if not isinstance(pattern, str):
            errors.append(f"missing direct-product filename pattern for {family}")
            continue
        matches = sorted(data_dir.glob(_glob_pattern(pattern)))
        if not matches:
            errors.append(f"no direct {family} files match {pattern}")
            continue
        combined = "\n".join(inspect(path) for path in matches)
        if not _contains_all(combined, required_fields):
            errors.append(
                f"direct {family} headers missing required field(s) "
                f"{required_fields}"
            )
        if family == "aop" and not has_explicit_standard_conditions(combined):
            errors.append(
                "direct AOP headers do not numerically define both standard "
                "temperature and standard pressure"
            )

    provenance.sort(key=lambda item: item["archive_filename"])
    return errors, provenance


def build_report(manifest: Path, data_dir: Path | None) -> dict[str, Any]:
    contract = load_contract(manifest)
    errors = validate_logical_contract(contract)
    provenance: list[dict[str, Any]] = []
    mode = "logical_contract"
    if data_dir is not None:
        mode = "logical_contract_and_payload_headers"
        payload_errors, provenance = validate_payloads(contract, data_dir)
        errors.extend(payload_errors)
    return {
        "schema_version": 1,
        "validator": "firex-aq-observation-inventory-v1",
        "mode": mode,
        "manifest": str(manifest.resolve()),
        "data_dir": str(data_dir.resolve()) if data_dir is not None else None,
        "result": "pass" if not errors else "fail",
        "errors": errors,
        "payload_provenance": provenance,
        "non_claims": [
            "No science rows were transformed.",
            "No model optical or physical acceptance is implied.",
            "A non-BC absorption residual remains blocked.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.manifest, args.data_dir)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
