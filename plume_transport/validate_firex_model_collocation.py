#!/usr/bin/env python3
"""Validate a completed FIREX-AQ / GEOS-Chem collocation without rewriting it."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence


WAVELENGTHS_NM = (405, 532, 664)
COMPONENTS = ("tot", "bc", "brc", "oa", "dust", "other")
SUMMED_COMPONENTS = ("bc", "brc", "oa", "dust", "other")
VOLUME_STATES = ("ambient", "aop_reference")


class FirexCollocationValidationError(ValueError):
    """Raised when validator arguments or files cannot be interpreted safely."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_float(row: dict[str, str], field: str, row_number: int) -> float:
    if field not in row:
        raise FirexCollocationValidationError(f"CSV lacks required field {field}")
    try:
        value = float(row[field])
    except (TypeError, ValueError) as exc:
        raise FirexCollocationValidationError(
            f"CSV row {row_number} field {field} is not numeric"
        ) from exc
    if not math.isfinite(value):
        raise FirexCollocationValidationError(
            f"CSV row {row_number} field {field} is not finite"
        )
    return value


def _check(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FirexCollocationValidationError(f"summary JSON is absent: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FirexCollocationValidationError(
            f"summary JSON is not readable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise FirexCollocationValidationError("summary JSON root must be an object")
    return value


def _load_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FirexCollocationValidationError(f"row CSV is absent: {path}")
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise FirexCollocationValidationError("row CSV has no header")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FirexCollocationValidationError(
            f"row CSV is not readable: {path}"
        ) from exc
    if not rows:
        raise FirexCollocationValidationError("row CSV contains no data rows")
    return rows


def build_report(
    summary_path: Path,
    csv_path: Path,
    *,
    expected_observation_sha256: str,
    expected_model_sha256: Sequence[str],
    expected_rows: int,
    expected_selected_records: int,
    expected_selected_first: str,
    expected_selected_last: str,
    maximum_time_offset_seconds: float,
    maximum_latitude_offset_degrees: float,
    maximum_longitude_offset_degrees: float,
    maximum_vertical_offset_m: float,
    expected_negative_counts: Sequence[int],
    expected_positive_aae_rows: int,
    component_rtol: float,
    component_atol_mm1: float,
) -> dict[str, Any]:
    """Return a fail-closed, JSON-safe validation report."""

    if expected_rows < 1 or expected_selected_records < 1:
        raise FirexCollocationValidationError(
            "expected row and selected-record counts must be positive"
        )
    if len(expected_negative_counts) != len(WAVELENGTHS_NM):
        raise FirexCollocationValidationError(
            "expected negative counts must contain 405, 532, and 664 values"
        )
    numeric_limits = (
        maximum_time_offset_seconds,
        maximum_latitude_offset_degrees,
        maximum_longitude_offset_degrees,
        maximum_vertical_offset_m,
        component_rtol,
        component_atol_mm1,
    )
    if any(not math.isfinite(value) or value < 0 for value in numeric_limits):
        raise FirexCollocationValidationError(
            "matching limits and component tolerances must be finite and nonnegative"
        )

    summary = _load_summary(summary_path)
    rows = _load_rows(csv_path)
    errors: list[str] = []

    observation = summary.get("observation", {})
    model_history = summary.get("model_history", {})
    matching = summary.get("matching", {})
    volume_state = summary.get("volume_state", {})
    metrics = summary.get("metrics_model_minus_observation", {})
    _check(
        errors,
        summary.get("schema_version") == "firex-model-collocation-v1",
        "unexpected collocation schema version",
    )
    _check(errors, summary.get("result") == "completed", "summary result is not completed")
    _check(
        errors,
        observation.get("sha256") == expected_observation_sha256,
        "observation SHA-256 does not match the frozen carrier",
    )
    _check(
        errors,
        observation.get("strict_rows") == expected_rows,
        "summary strict-row count does not match the frozen count",
    )
    _check(
        errors,
        matching.get("strict_observation_rows") == expected_rows,
        "matching strict-row count does not match the frozen count",
    )
    _check(
        errors,
        matching.get("accepted_rows") == expected_rows,
        "not every frozen strict row was accepted",
    )
    _check(
        errors,
        matching.get("rejection_counts") == {"accepted": expected_rows},
        "summary rejection counts are not exactly all accepted",
    )
    _check(
        errors,
        matching.get("maximum_time_offset_seconds")
        == maximum_time_offset_seconds,
        "summary time tolerance differs from the frozen value",
    )
    _check(
        errors,
        matching.get("maximum_vertical_offset_m") == maximum_vertical_offset_m,
        "summary vertical tolerance differs from the frozen value",
    )
    _check(
        errors,
        volume_state.get("aop_reference_pressure_hpa") == 1013.0,
        "AOP reference pressure must be exactly 1013 hPa",
    )
    _check(
        errors,
        volume_state.get("aop_reference_temperature_k") == 273.0,
        "AOP reference temperature must be exactly 273 K",
    )
    _check(
        errors,
        model_history.get("selected_first") == expected_selected_first,
        "selected model first timestamp differs from the frozen value",
    )
    _check(
        errors,
        model_history.get("selected_last") == expected_selected_last,
        "selected model last timestamp differs from the frozen value",
    )
    selected_records = model_history.get("selected_records", [])
    _check(
        errors,
        isinstance(selected_records, list)
        and len(selected_records) == expected_selected_records,
        "selected model record count differs from the frozen value",
    )
    model_files = model_history.get("files", [])
    observed_model_hashes = (
        [entry.get("sha256") for entry in model_files]
        if isinstance(model_files, list)
        and all(isinstance(entry, dict) for entry in model_files)
        else []
    )
    _check(
        errors,
        observed_model_hashes == list(expected_model_sha256),
        "model HISTORY hashes or order differ from the frozen inputs",
    )
    _check(errors, len(rows) == expected_rows, "CSV row count differs from frozen count")

    valid_count = 0
    reasons: Counter[str] = Counter()
    maxima = {
        "absolute_time_offset_seconds": 0.0,
        "absolute_latitude_offset_degrees": 0.0,
        "absolute_longitude_offset_degrees": 0.0,
        "absolute_vertical_offset_m": 0.0,
    }
    negative_counts = {str(wavelength): 0 for wavelength in WAVELENGTHS_NM}
    positive_aae_rows = 0
    closure_maxima: dict[str, dict[str, float]] = {
        state: {str(wavelength): 0.0 for wavelength in WAVELENGTHS_NM}
        for state in VOLUME_STATES
    }

    try:
        for row_number, row in enumerate(rows, start=2):
            valid_text = row.get("match_valid", "").strip().lower()
            valid = valid_text == "true"
            valid_count += int(valid)
            reason = row.get("match_rejection_reason", "")
            reasons[reason] += 1
            _check(
                errors,
                valid and reason == "accepted",
                f"CSV row {row_number} is not an accepted match",
            )

            time_offset = abs(
                _finite_float(row, "model_time_offset_seconds", row_number)
            )
            latitude_offset = abs(
                _finite_float(row, "model_latitude_offset_degrees", row_number)
            )
            longitude_offset = abs(
                _finite_float(row, "model_longitude_offset_degrees", row_number)
            )
            vertical_offset = abs(
                _finite_float(row, "model_altitude_offset_m", row_number)
            )
            maxima["absolute_time_offset_seconds"] = max(
                maxima["absolute_time_offset_seconds"], time_offset
            )
            maxima["absolute_latitude_offset_degrees"] = max(
                maxima["absolute_latitude_offset_degrees"], latitude_offset
            )
            maxima["absolute_longitude_offset_degrees"] = max(
                maxima["absolute_longitude_offset_degrees"], longitude_offset
            )
            maxima["absolute_vertical_offset_m"] = max(
                maxima["absolute_vertical_offset_m"], vertical_offset
            )

            pressure = _finite_float(row, "model_pressure_hpa", row_number)
            temperature = _finite_float(row, "model_temperature_k", row_number)
            _check(errors, pressure > 0.0, f"CSV row {row_number} pressure is not positive")
            _check(
                errors,
                temperature > 0.0,
                f"CSV row {row_number} temperature is not positive",
            )

            observation_values: dict[int, float] = {}
            for wavelength in WAVELENGTHS_NM:
                observation_value = _finite_float(
                    row, f"observation_abs_{wavelength}_mm1", row_number
                )
                observation_values[wavelength] = observation_value
                negative_counts[str(wavelength)] += int(observation_value < 0.0)
                for state in VOLUME_STATES:
                    prefix = f"model_abs_{wavelength}_"
                    total = _finite_float(
                        row, f"{prefix}tot_{state}_mm1", row_number
                    )
                    component_sum = sum(
                        _finite_float(
                            row, f"{prefix}{component}_{state}_mm1", row_number
                        )
                        for component in SUMMED_COMPONENTS
                    )
                    _check(
                        errors,
                        total >= 0.0 and component_sum >= 0.0,
                        f"CSV row {row_number} model absorption is negative",
                    )
                    difference = abs(total - component_sum)
                    closure_maxima[state][str(wavelength)] = max(
                        closure_maxima[state][str(wavelength)], difference
                    )
                    _check(
                        errors,
                        math.isclose(
                            total,
                            component_sum,
                            rel_tol=component_rtol,
                            abs_tol=component_atol_mm1,
                        ),
                        f"CSV row {row_number} {state} component closure fails "
                        f"at {wavelength} nm",
                    )
            positive_aae_rows += int(
                observation_values[405] > 0.0 and observation_values[664] > 0.0
            )
    except FirexCollocationValidationError as exc:
        errors.append(str(exc))

    _check(errors, valid_count == expected_rows, "CSV valid-row count differs from frozen count")
    _check(
        errors,
        reasons == Counter({"accepted": expected_rows}),
        "CSV rejection reasons are not exactly all accepted",
    )
    _check(
        errors,
        maxima["absolute_time_offset_seconds"] <= maximum_time_offset_seconds,
        "a row exceeds the maximum time offset",
    )
    _check(
        errors,
        maxima["absolute_latitude_offset_degrees"]
        <= maximum_latitude_offset_degrees,
        "a row exceeds the half-grid latitude offset",
    )
    _check(
        errors,
        maxima["absolute_longitude_offset_degrees"]
        <= maximum_longitude_offset_degrees,
        "a row exceeds the half-grid longitude offset",
    )
    _check(
        errors,
        maxima["absolute_vertical_offset_m"] <= maximum_vertical_offset_m,
        "a row exceeds the maximum vertical offset",
    )
    _check(
        errors,
        [negative_counts[str(value)] for value in WAVELENGTHS_NM]
        == list(expected_negative_counts),
        "finite negative observation counts differ from the frozen values",
    )
    _check(
        errors,
        positive_aae_rows == expected_positive_aae_rows,
        "positive 405/664 observation-pair count differs from the frozen value",
    )
    for wavelength in WAVELENGTHS_NM:
        metric = metrics.get(str(wavelength), {})
        _check(
            errors,
            isinstance(metric, dict) and metric.get("n") == expected_rows,
            f"{wavelength} nm metric count differs from accepted rows",
        )

    return {
        "schema_version": "firex-model-collocation-validation-v1",
        "validator": "validate_firex_model_collocation.py",
        "result": "pass" if not errors else "fail",
        "inputs": {
            "summary_json": str(summary_path.resolve()),
            "summary_sha256": sha256(summary_path),
            "rows_csv": str(csv_path.resolve()),
            "rows_sha256": sha256(csv_path),
        },
        "checks": {
            "expected_rows": expected_rows,
            "accepted_rows": valid_count,
            "rejection_counts": dict(sorted(reasons.items())),
            "selected_model_records": len(selected_records)
            if isinstance(selected_records, list)
            else None,
            "offset_maxima": maxima,
            "finite_negative_observation_counts": negative_counts,
            "positive_405_664_observation_pairs": positive_aae_rows,
            "component_closure_max_abs_mm1": closure_maxima,
            "component_rtol": component_rtol,
            "component_atol_mm1": component_atol_mm1,
        },
        "errors": errors,
        "non_claims": [
            "No observation, model HISTORY, collocation JSON, or row CSV value was modified.",
            "This validates matching and arithmetic contracts, not model skill.",
            "Model component attribution is not direct validation against observed BrC.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary_json", type=Path)
    parser.add_argument("rows_csv", type=Path)
    parser.add_argument("--expected-observation-sha256", required=True)
    parser.add_argument("--expected-model-sha256", action="append", required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--expected-selected-records", type=int, required=True)
    parser.add_argument("--expected-selected-first", required=True)
    parser.add_argument("--expected-selected-last", required=True)
    parser.add_argument("--maximum-time-offset-seconds", type=float, required=True)
    parser.add_argument("--maximum-latitude-offset-degrees", type=float, required=True)
    parser.add_argument("--maximum-longitude-offset-degrees", type=float, required=True)
    parser.add_argument("--maximum-vertical-offset-m", type=float, required=True)
    parser.add_argument(
        "--expected-negative-counts",
        type=int,
        nargs=3,
        metavar=("N405", "N532", "N664"),
        required=True,
    )
    parser.add_argument("--expected-positive-aae-rows", type=int, required=True)
    parser.add_argument("--component-rtol", type=float, default=1.0e-6)
    parser.add_argument("--component-atol-mm1", type=float, default=1.0e-8)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output is not None and args.output.resolve() in {
        args.summary_json.resolve(),
        args.rows_csv.resolve(),
    }:
        raise FirexCollocationValidationError(
            "validation report must not overwrite a collocation input"
        )
    report = build_report(
        args.summary_json,
        args.rows_csv,
        expected_observation_sha256=args.expected_observation_sha256,
        expected_model_sha256=args.expected_model_sha256,
        expected_rows=args.expected_rows,
        expected_selected_records=args.expected_selected_records,
        expected_selected_first=args.expected_selected_first,
        expected_selected_last=args.expected_selected_last,
        maximum_time_offset_seconds=args.maximum_time_offset_seconds,
        maximum_latitude_offset_degrees=args.maximum_latitude_offset_degrees,
        maximum_longitude_offset_degrees=args.maximum_longitude_offset_degrees,
        maximum_vertical_offset_m=args.maximum_vertical_offset_m,
        expected_negative_counts=args.expected_negative_counts,
        expected_positive_aae_rows=args.expected_positive_aae_rows,
        component_rtol=args.component_rtol,
        component_atol_mm1=args.component_atol_mm1,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
