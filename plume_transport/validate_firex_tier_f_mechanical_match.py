#!/usr/bin/env python3
"""Independently audit a Tier-F mechanical matcher output."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


WAVELENGTHS = (405, 532, 664)
COMPONENTS = ("tot", "bc", "brc", "oa", "dust", "other")
SUMMED = ("bc", "brc", "oa", "dust", "other")
STATES = ("ambient", "aop_reference")


class TierFMechanicalValidationError(ValueError):
    """Raised when validation inputs cannot be audited safely."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(row: dict[str, str], field: str, number: int) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise TierFMechanicalValidationError(
            f"row {number} field {field} is not numeric"
        ) from exc
    if not math.isfinite(value):
        raise TierFMechanicalValidationError(
            f"row {number} field {field} is not finite"
        )
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TierFMechanicalValidationError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TierFMechanicalValidationError("summary JSON root is not an object")
    return value


def _load_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise TierFMechanicalValidationError(f"CSV has no header: {path}")
            return list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise TierFMechanicalValidationError(f"cannot read CSV: {path}") from exc


def build_report(
    summary_path: Path,
    rows_path: Path,
    carrier_path: Path,
    *,
    expected_carrier_sha256: str,
    expected_model_sha256: Sequence[str],
    expected_rows: int,
    maximum_time_offset_seconds: float,
    maximum_latitude_offset_degrees: float,
    maximum_longitude_offset_degrees: float,
    maximum_vertical_offset_m: float,
    component_rtol: float,
    component_atol_mm1: float,
) -> dict[str, Any]:
    """Return a fail-closed audit without changing any input."""

    summary = _load_json(summary_path)
    rows = _load_csv(rows_path)
    carrier = _load_csv(carrier_path)
    errors: list[str] = []
    if sha256(carrier_path) != expected_carrier_sha256:
        errors.append("carrier SHA-256 differs from frozen value")
    if summary.get("schema_version") != "firex-tier-f-mechanical-match-v1":
        errors.append("unexpected summary schema")
    if summary.get("result") != "completed":
        errors.append("summary is not completed")
    if "metrics_model_minus_observation" in summary:
        errors.append("mechanical summary contains prohibited skill metrics")
    if len(rows) != expected_rows or len(carrier) != expected_rows:
        errors.append("row count differs from frozen carrier count")

    summary_files = summary.get("model_history", {}).get("files", [])
    actual_model_hashes = [
        item.get("sha256") for item in summary_files if isinstance(item, dict)
    ] if isinstance(summary_files, list) else []
    if actual_model_hashes != list(expected_model_sha256):
        errors.append("ordered model HISTORY hashes differ")

    valid_count = 0
    reasons: Counter[str] = Counter()
    ids: set[str] = set()
    maxima = {
        "absolute_time_offset_seconds": 0.0,
        "absolute_latitude_offset_degrees": 0.0,
        "absolute_longitude_offset_degrees": 0.0,
        "absolute_vertical_offset_m": 0.0,
    }
    closure = {
        state: {str(wavelength): 0.0 for wavelength in WAVELENGTHS}
        for state in STATES
    }
    try:
        for index, (row, source) in enumerate(zip(rows, carrier, strict=True)):
            number = index + 2
            if row.get("carrier_source_record_id") != source.get("carrier_source_record_id"):
                errors.append(f"row {number} source identity/order differs")
            if row.get("carrier_raw_record_sha256") != source.get("carrier_raw_record_sha256"):
                errors.append(f"row {number} raw-record hash differs")
            if int(_finite(row, "carrier_ordinal", number)) != index:
                errors.append(f"row {number} carrier ordinal differs")
            start = _finite(row, "carrier_time_start_seconds", number)
            stop = _finite(row, "carrier_time_stop_seconds", number)
            if start != round(start) or stop != start + 1.0:
                errors.append(f"row {number} one-second time contract fails")
            source_id = row.get("carrier_source_record_id", "")
            if source_id in ids:
                errors.append(f"row {number} duplicates source identity")
            ids.add(source_id)
            encoded = row.get("match_valid")
            if encoded not in {"True", "False"}:
                raise TierFMechanicalValidationError(
                    f"row {number} match_valid is not textual Boolean"
                )
            valid = encoded == "True"
            reason = row.get("match_rejection_reason", "")
            reasons[reason] += 1
            if valid != (reason == "accepted"):
                errors.append(f"row {number} validity/reason differs")
            if not valid:
                continue
            valid_count += 1
            offsets = {
                "absolute_time_offset_seconds": abs(_finite(row, "model_time_offset_seconds", number)),
                "absolute_latitude_offset_degrees": abs(_finite(row, "model_latitude_offset_degrees", number)),
                "absolute_longitude_offset_degrees": abs(_finite(row, "model_longitude_offset_degrees", number)),
                "absolute_vertical_offset_m": abs(_finite(row, "model_altitude_offset_m", number)),
            }
            for key, value in offsets.items():
                maxima[key] = max(maxima[key], value)
            if _finite(row, "model_pressure_hpa", number) <= 0.0:
                errors.append(f"row {number} model pressure is not positive")
            if _finite(row, "model_temperature_k", number) <= 0.0:
                errors.append(f"row {number} model temperature is not positive")
            for state in STATES:
                for wavelength in WAVELENGTHS:
                    values = {
                        component: _finite(
                            row,
                            f"model_abs_{wavelength}_{component}_{state}_mm1",
                            number,
                        )
                        for component in COMPONENTS
                    }
                    if min(values.values()) < 0.0:
                        errors.append(
                            f"row {number} {state} {wavelength} component is negative"
                        )
                    difference = abs(
                        values["tot"] - sum(values[c] for c in SUMMED)
                    )
                    closure[state][str(wavelength)] = max(
                        closure[state][str(wavelength)], difference
                    )
                    if not math.isclose(
                        values["tot"],
                        sum(values[c] for c in SUMMED),
                        rel_tol=component_rtol,
                        abs_tol=component_atol_mm1,
                    ):
                        errors.append(
                            f"row {number} {state} {wavelength} closure fails"
                        )
    except (TierFMechanicalValidationError, ValueError) as exc:
        errors.append(str(exc))

    limits = {
        "absolute_time_offset_seconds": maximum_time_offset_seconds,
        "absolute_latitude_offset_degrees": maximum_latitude_offset_degrees,
        "absolute_longitude_offset_degrees": maximum_longitude_offset_degrees,
        "absolute_vertical_offset_m": maximum_vertical_offset_m,
    }
    for key, limit in limits.items():
        if maxima[key] > limit:
            errors.append(f"{key} exceeds frozen bound")
    matching = summary.get("matching", {})
    if not isinstance(matching, dict):
        errors.append("summary matching block is malformed")
    else:
        if matching.get("rows") != expected_rows:
            errors.append("summary carrier row count differs")
        if matching.get("accepted_rows") != valid_count:
            errors.append("summary accepted count differs")
        if matching.get("rejection_counts") != dict(sorted(reasons.items())):
            errors.append("summary rejection counts differ")
    if valid_count == 0:
        errors.append("zero valid matches")

    return {
        "schema_version": "firex-tier-f-mechanical-match-validation-v1",
        "result": "pass" if not errors else "fail",
        "inputs": {
            "summary_json": str(summary_path.resolve()),
            "summary_sha256": sha256(summary_path),
            "rows_csv": str(rows_path.resolve()),
            "rows_sha256": sha256(rows_path),
            "carrier_csv": str(carrier_path.resolve()),
            "carrier_sha256": sha256(carrier_path),
        },
        "checks": {
            "expected_rows": expected_rows,
            "ordered_unique_rows": len(ids),
            "accepted_rows": valid_count,
            "rejection_counts": dict(sorted(reasons.items())),
            "offset_maxima": maxima,
            "component_closure_max_abs_mm1": closure,
        },
        "errors": errors,
        "non_claims": [
            "No input or result was modified.",
            "This audits matching and arithmetic, not model skill.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary_json", type=Path)
    parser.add_argument("rows_csv", type=Path)
    parser.add_argument("--carrier", required=True, type=Path)
    parser.add_argument("--expected-carrier-sha256", required=True)
    parser.add_argument("--expected-model-sha256", action="append", required=True)
    parser.add_argument("--expected-rows", required=True, type=int)
    parser.add_argument("--maximum-time-offset-seconds", required=True, type=float)
    parser.add_argument("--maximum-latitude-offset-degrees", required=True, type=float)
    parser.add_argument("--maximum-longitude-offset-degrees", required=True, type=float)
    parser.add_argument("--maximum-vertical-offset-m", required=True, type=float)
    parser.add_argument("--component-rtol", type=float, default=1e-6)
    parser.add_argument("--component-atol-mm1", type=float, default=1e-8)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        args.summary_json,
        args.rows_csv,
        args.carrier,
        expected_carrier_sha256=args.expected_carrier_sha256,
        expected_model_sha256=args.expected_model_sha256,
        expected_rows=args.expected_rows,
        maximum_time_offset_seconds=args.maximum_time_offset_seconds,
        maximum_latitude_offset_degrees=args.maximum_latitude_offset_degrees,
        maximum_longitude_offset_degrees=args.maximum_longitude_offset_degrees,
        maximum_vertical_offset_m=args.maximum_vertical_offset_m,
        component_rtol=args.component_rtol,
        component_atol_mm1=args.component_atol_mm1,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
