#!/usr/bin/env python3
"""Revalidate the accepted FIREX-AQ matcher on the Tier-F carrier population."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

import numpy as np

if __package__:
    from .firex_history_time import format_utc_timestamp
    from .firex_model_collocation import (
        ABSORPTION_COMPONENTS,
        WAVELENGTHS_NM,
        _model_absorption_name,
        _model_field_alias,
        load_relevant_model_records,
        sha256,
    )
    from .firex_model_match import (
        G_STANDARD_M_S2,
        convert_matched_absorption_to_aop_reference,
        match_aircraft_to_model,
    )
else:
    from firex_history_time import format_utc_timestamp
    from firex_model_collocation import (  # type: ignore[no-redef]
        ABSORPTION_COMPONENTS,
        WAVELENGTHS_NM,
        _model_absorption_name,
        _model_field_alias,
        load_relevant_model_records,
        sha256,
    )
    from firex_model_match import (  # type: ignore[no-redef]
        G_STANDARD_M_S2,
        convert_matched_absorption_to_aop_reference,
        match_aircraft_to_model,
    )


REQUIRED_CARRIER_FIELDS = (
    "carrier_source_record_id",
    "carrier_ordinal",
    "carrier_raw_record_sha256",
    "Time_Start",
    "Time_Stop",
    "Latitude",
    "Longitude",
    "MSL_GPS_Altitude",
)
SUMMED_COMPONENTS = ("BC", "BrC", "OA", "Dust", "Other")
BASE_TIME = np.datetime64("2019-08-06T00:00:00", "ns")


class TierFMechanicalMatchError(ValueError):
    """Raised when the frozen Tier-F mechanical contract is violated."""


def _finite_float(row: dict[str, str], field: str, row_number: int) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise TierFMechanicalMatchError(
            f"carrier row {row_number} field {field} is not numeric"
        ) from exc
    if not np.isfinite(value):
        raise TierFMechanicalMatchError(
            f"carrier row {row_number} field {field} is not finite"
        )
    return value


def read_carrier(
    path: Path, *, expected_sha256: str, expected_rows: int
) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    """Read the complete ordered carrier without applying a science filter."""

    if not path.is_file():
        raise TierFMechanicalMatchError(f"carrier is absent: {path}")
    actual_sha = sha256(path)
    if actual_sha != expected_sha256:
        raise TierFMechanicalMatchError("carrier SHA-256 differs from frozen value")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise TierFMechanicalMatchError("carrier CSV has no header")
        missing = [name for name in REQUIRED_CARRIER_FIELDS if name not in reader.fieldnames]
        if missing:
            raise TierFMechanicalMatchError(
                "carrier lacks required fields: " + ", ".join(missing)
            )
        rows = list(reader)
    if len(rows) != expected_rows:
        raise TierFMechanicalMatchError(
            f"carrier rows {len(rows)} != frozen {expected_rows}"
        )

    ordinal = np.asarray(
        [int(_finite_float(row, "carrier_ordinal", i + 2)) for i, row in enumerate(rows)],
        dtype=np.int64,
    )
    if not np.array_equal(ordinal, np.arange(expected_rows, dtype=np.int64)):
        raise TierFMechanicalMatchError("carrier ordinals are not contiguous from zero")
    seconds = np.asarray(
        [_finite_float(row, "Time_Start", i + 2) for i, row in enumerate(rows)]
    )
    stop_seconds = np.asarray(
        [_finite_float(row, "Time_Stop", i + 2) for i, row in enumerate(rows)]
    )
    if np.any(seconds != np.rint(seconds)):
        raise TierFMechanicalMatchError("Time_Start must be integral seconds")
    if not np.array_equal(stop_seconds, seconds + 1.0):
        raise TierFMechanicalMatchError("Time_Stop must equal Time_Start plus one")
    nanoseconds = np.rint(seconds * 1.0e9)
    if np.any(np.abs(seconds * 1.0e9 - nanoseconds) > 0.5):
        raise TierFMechanicalMatchError("Time_Start is not representable in nanoseconds")
    timestamps = BASE_TIME + nanoseconds.astype(np.int64).astype("timedelta64[ns]")
    latitude = np.asarray(
        [_finite_float(row, "Latitude", i + 2) for i, row in enumerate(rows)]
    )
    longitude = np.asarray(
        [_finite_float(row, "Longitude", i + 2) for i, row in enumerate(rows)]
    )
    altitude = np.asarray(
        [_finite_float(row, "MSL_GPS_Altitude", i + 2) for i, row in enumerate(rows)]
    )
    source_ids = np.asarray([row["carrier_source_record_id"] for row in rows], dtype=object)
    raw_hashes = np.asarray([row["carrier_raw_record_sha256"] for row in rows], dtype=object)
    if len(set(source_ids.tolist())) != expected_rows:
        raise TierFMechanicalMatchError("carrier source-record identities are not unique")
    if any(len(value) != 64 for value in raw_hashes):
        raise TierFMechanicalMatchError("carrier raw-record SHA-256 field is malformed")

    arrays = {
        "source_id": source_ids,
        "ordinal": ordinal,
        "raw_sha256": raw_hashes,
        "time_start_seconds": seconds,
        "time_stop_seconds": stop_seconds,
        "time": timestamps,
        "latitude": latitude,
        "longitude": longitude,
        "altitude_msl_m": altitude,
    }
    report = {
        "path": str(path.resolve()),
        "sha256": actual_sha,
        "rows": expected_rows,
        "first_source_id": str(source_ids[0]),
        "last_source_id": str(source_ids[-1]),
        "first_time_utc": format_utc_timestamp(timestamps[0]),
        "last_time_utc": format_utc_timestamp(timestamps[-1]),
        "post_midnight_rows": int(np.count_nonzero(seconds >= 86400.0)),
        "navigation": {
            "latitude": "Latitude",
            "longitude": "Longitude",
            "altitude_msl_m": "MSL_GPS_Altitude",
        },
        "selection": "all carrier rows; no science-field filter",
    }
    return arrays, report


def _json_value(value: object) -> bool | float | int | str | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"unsupported output value {type(value).__name__}")


def build_revalidation(
    *,
    carrier_path: Path,
    expected_carrier_sha256: str,
    expected_rows: int,
    model_history_paths: Sequence[Path],
    expected_model_sha256: Sequence[str],
    maximum_time_offset_seconds: float,
    maximum_latitude_offset_degrees: float,
    maximum_longitude_offset_degrees: float,
    maximum_vertical_offset_m: float,
    reference_pressure_hpa: float,
    reference_temperature_k: float,
    component_rtol: float,
    component_atol_mm1: float,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Build row output and mechanics-only summary after frozen gates pass."""

    if len(model_history_paths) != len(expected_model_sha256):
        raise TierFMechanicalMatchError("model path/hash counts differ")
    model_provenance = []
    for path, expected in zip(model_history_paths, expected_model_sha256, strict=True):
        actual = sha256(path)
        if actual != expected:
            raise TierFMechanicalMatchError(f"model HISTORY hash mismatch: {path}")
        model_provenance.append({"path": str(path.resolve()), "sha256": actual})
    carrier, carrier_report = read_carrier(
        carrier_path,
        expected_sha256=expected_carrier_sha256,
        expected_rows=expected_rows,
    )
    (
        model_time,
        model_latitude,
        model_longitude,
        model_box_height,
        model_arrays,
        model_time_sources,
    ) = load_relevant_model_records(
        model_history_paths,
        observation_time=carrier["time"],
        maximum_time_offset_seconds=maximum_time_offset_seconds,
    )
    aliases: dict[str, str] = {}
    model_fields = {
        "model_pressure_hpa": model_arrays["Met_PMID"],
        "model_temperature_k": model_arrays["Met_T"],
    }
    for wavelength in WAVELENGTHS_NM:
        for component in ABSORPTION_COMPONENTS:
            alias = _model_field_alias(wavelength, component)
            aliases[alias] = _model_absorption_name(wavelength, component)
            model_fields[alias] = model_arrays[aliases[alias]]

    matched = match_aircraft_to_model(
        observation_time=carrier["time"],
        observation_latitude=carrier["latitude"],
        observation_longitude=carrier["longitude"],
        observation_altitude_m=carrier["altitude_msl_m"],
        model_time=model_time,
        model_latitude=model_latitude,
        model_longitude=model_longitude,
        model_box_height_m=model_box_height,
        model_surface_geopotential_m2_s2=model_arrays["Met_PHIS"] * G_STANDARD_M_S2,
        model_fields=model_fields,
        maximum_time_offset_seconds=maximum_time_offset_seconds,
        maximum_vertical_offset_m=maximum_vertical_offset_m,
    )
    accepted = matched.valid
    if not np.any(accepted):
        raise TierFMechanicalMatchError("matcher accepted zero carrier rows")
    maxima = {
        "absolute_time_offset_seconds": float(np.nanmax(np.abs(matched.time_offset_seconds[accepted]))),
        "absolute_latitude_offset_degrees": float(np.nanmax(np.abs(matched.latitude_offset_degrees[accepted]))),
        "absolute_longitude_offset_degrees": float(np.nanmax(np.abs(matched.longitude_offset_degrees[accepted]))),
        "absolute_vertical_offset_m": float(np.nanmax(np.abs(matched.altitude_offset_m[accepted]))),
    }
    if maxima["absolute_time_offset_seconds"] > maximum_time_offset_seconds:
        raise TierFMechanicalMatchError("accepted row exceeds time bound")
    if maxima["absolute_latitude_offset_degrees"] > maximum_latitude_offset_degrees:
        raise TierFMechanicalMatchError("accepted row exceeds latitude half-grid bound")
    if maxima["absolute_longitude_offset_degrees"] > maximum_longitude_offset_degrees:
        raise TierFMechanicalMatchError("accepted row exceeds longitude half-grid bound")
    if maxima["absolute_vertical_offset_m"] > maximum_vertical_offset_m:
        raise TierFMechanicalMatchError("accepted row exceeds vertical bound")

    pressure = matched.sampled_fields["model_pressure_hpa"]
    temperature = matched.sampled_fields["model_temperature_k"]
    converted: dict[str, np.ndarray] = {}
    for alias in aliases:
        values = np.full(expected_rows, np.nan)
        values[accepted] = convert_matched_absorption_to_aop_reference(
            matched.sampled_fields[alias][accepted],
            pressure[accepted],
            temperature[accepted],
            aop_reference_pressure_hpa=reference_pressure_hpa,
            aop_reference_temperature_k=reference_temperature_k,
        )
        converted[alias] = values

    closure: dict[str, dict[str, float | int]] = {}
    for state, values in (("ambient", matched.sampled_fields), ("aop_reference", converted)):
        closure[state] = {}
        for wavelength in WAVELENGTHS_NM:
            total_alias = _model_field_alias(wavelength, "Tot")
            total = values[total_alias][accepted]
            parts = sum(values[_model_field_alias(wavelength, c)][accepted] for c in SUMMED_COMPONENTS)
            all_values = np.column_stack(
                [values[_model_field_alias(wavelength, c)][accepted] for c in ABSORPTION_COMPONENTS]
            )
            finite_nonnegative = np.all(np.isfinite(all_values)) and np.all(all_values >= 0.0)
            difference = np.abs(total - parts)
            failures = int(np.count_nonzero(~np.isclose(
                total, parts, rtol=component_rtol, atol=component_atol_mm1
            )))
            closure[state][f"{wavelength}_max_abs_mm1"] = float(np.max(difference))
            closure[state][f"{wavelength}_failures"] = failures
            if not finite_nonnegative or failures:
                raise TierFMechanicalMatchError(
                    f"{state} model component gate fails at {wavelength} nm"
                )

    rows: list[dict[str, object]] = []
    for index in range(expected_rows):
        time_index = int(matched.model_time_index[index])
        source = model_time_sources[time_index] if time_index >= 0 else None
        row: dict[str, object] = {
            "carrier_source_record_id": str(carrier["source_id"][index]),
            "carrier_ordinal": carrier["ordinal"][index],
            "carrier_raw_record_sha256": str(carrier["raw_sha256"][index]),
            "carrier_time_start_seconds": carrier["time_start_seconds"][index],
            "carrier_time_stop_seconds": carrier["time_stop_seconds"][index],
            "observation_time_utc": format_utc_timestamp(carrier["time"][index]),
            "observation_latitude_degrees": carrier["latitude"][index],
            "observation_longitude_degrees": carrier["longitude"][index],
            "observation_altitude_msl_m": carrier["altitude_msl_m"][index],
            "match_valid": bool(accepted[index]),
            "match_rejection_reason": str(matched.rejection_reason[index]),
            "model_time_utc": source["timestamp"] if source else None,
            "model_history_file": source["path"] if source else None,
            "model_history_local_record_index": source["local_record_index"] if source else None,
            "model_time_offset_seconds": matched.time_offset_seconds[index],
            "model_latitude_index": matched.model_lat_index[index],
            "model_longitude_index": matched.model_lon_index[index],
            "model_level_index": matched.model_level_index[index],
            "model_latitude_offset_degrees": matched.latitude_offset_degrees[index],
            "model_longitude_offset_degrees": matched.longitude_offset_degrees[index],
            "model_altitude_offset_m": matched.altitude_offset_m[index],
            "model_layer_centre_altitude_m": matched.model_layer_centre_altitude_m[index],
            "model_pressure_hpa": pressure[index],
            "model_temperature_k": temperature[index],
        }
        for alias in aliases:
            row[alias] = matched.sampled_fields[alias][index]
            row[alias.replace("_ambient_", "_aop_reference_")] = converted[alias][index]
        rows.append({key: _json_value(value) for key, value in row.items()})

    reason_counts = Counter(str(value) for value in matched.rejection_reason)
    summary: dict[str, object] = {
        "schema_version": "firex-tier-f-mechanical-match-v1",
        "result": "completed",
        "carrier": carrier_report,
        "model_history": {
            "files": model_provenance,
            "selected_records": model_time_sources,
            "selected_first": format_utc_timestamp(model_time[0]),
            "selected_last": format_utc_timestamp(model_time[-1]),
            "time_contract": "native CF minutes-since coordinate, strict 20-minute cadence",
        },
        "matching": {
            "algorithm": "accepted nearest time/grid-centre/geometric-layer matcher",
            "maximum_time_offset_seconds": maximum_time_offset_seconds,
            "maximum_latitude_offset_degrees": maximum_latitude_offset_degrees,
            "maximum_longitude_offset_degrees": maximum_longitude_offset_degrees,
            "maximum_vertical_offset_m": maximum_vertical_offset_m,
            "rows": expected_rows,
            "accepted_rows": int(np.count_nonzero(accepted)),
            "rejection_counts": dict(sorted(reason_counts.items())),
            "offset_maxima": maxima,
        },
        "volume_state": {
            "input": "dry ambient volume",
            "output": "dry AOP reference volume",
            "reference_pressure_hpa": reference_pressure_hpa,
            "reference_temperature_k": reference_temperature_k,
        },
        "component_closure": {
            "rtol": component_rtol,
            "atol_mm1": component_atol_mm1,
            "diagnostics": closure,
        },
        "field_mapping": aliases,
        "non_claims": [
            "No carrier or model HISTORY input was modified.",
            "No science-field filter, agreement-dependent rematching, or post-midnight clipping was used.",
            "This is mechanical matching and arithmetic validation, not a model-skill result.",
        ],
    }
    return summary, rows


def write_results(
    summary: dict[str, object],
    rows: Sequence[dict[str, object]],
    *,
    output_json: Path,
    output_csv: Path,
) -> None:
    if not rows or output_json.resolve() == output_csv.resolve():
        raise TierFMechanicalMatchError("invalid or empty output request")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carrier", required=True, type=Path)
    parser.add_argument("--expected-carrier-sha256", required=True)
    parser.add_argument("--expected-rows", required=True, type=int)
    parser.add_argument("--model-history", required=True, nargs="+", type=Path)
    parser.add_argument("--expected-model-sha256", required=True, action="append")
    parser.add_argument("--maximum-time-offset-seconds", required=True, type=float)
    parser.add_argument("--maximum-latitude-offset-degrees", required=True, type=float)
    parser.add_argument("--maximum-longitude-offset-degrees", required=True, type=float)
    parser.add_argument("--maximum-vertical-offset-m", required=True, type=float)
    parser.add_argument("--reference-pressure-hpa", required=True, type=float)
    parser.add_argument("--reference-temperature-k", required=True, type=float)
    parser.add_argument("--component-rtol", type=float, default=1e-6)
    parser.add_argument("--component-atol-mm1", type=float, default=1e-8)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary, rows = build_revalidation(
        carrier_path=args.carrier,
        expected_carrier_sha256=args.expected_carrier_sha256,
        expected_rows=args.expected_rows,
        model_history_paths=args.model_history,
        expected_model_sha256=args.expected_model_sha256,
        maximum_time_offset_seconds=args.maximum_time_offset_seconds,
        maximum_latitude_offset_degrees=args.maximum_latitude_offset_degrees,
        maximum_longitude_offset_degrees=args.maximum_longitude_offset_degrees,
        maximum_vertical_offset_m=args.maximum_vertical_offset_m,
        reference_pressure_hpa=args.reference_pressure_hpa,
        reference_temperature_k=args.reference_temperature_k,
        component_rtol=args.component_rtol,
        component_atol_mm1=args.component_atol_mm1,
    )
    write_results(summary, rows, output_json=args.output_json, output_csv=args.output_csv)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
