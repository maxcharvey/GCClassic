#!/usr/bin/env python3
"""Fail-closed row-level FIREX-AQ / GEOS-Chem exact-band collocation.

The module intentionally keeps file I/O at this boundary rather than adding
NetCDF assumptions to :mod:`firex_model_match`.  It retains exactly the
frozen all-three-band observation rows, decodes both observation and model
times from their CF metadata, samples only model records that could satisfy
the requested time tolerance, and writes a provenance-rich summary and CSV.
It never changes an observation or HISTORY file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import h5py
import numpy as np

if __package__:
    from .firex_history_time import (
        FirexHistoryTimeError,
        format_utc_timestamp,
        load_history_time_series,
        parse_utc_timestamp,
    )
    from .firex_model_match import (
        G_STANDARD_M_S2,
        FirexModelMatchError,
        convert_matched_absorption_to_aop_reference,
        match_aircraft_to_model,
    )
else:
    from firex_history_time import (  # type: ignore[no-redef]
        FirexHistoryTimeError,
        format_utc_timestamp,
        load_history_time_series,
        parse_utc_timestamp,
    )
    from firex_model_match import (  # type: ignore[no-redef]
        G_STANDARD_M_S2,
        FirexModelMatchError,
        convert_matched_absorption_to_aop_reference,
        match_aircraft_to_model,
    )


_OBS_MINUTES_SINCE = re.compile(r"^\s*minutes\s+since\s+(.+?)\s*$", re.I)
_NANOSECONDS_PER_MINUTE = 60_000_000_000

OBSERVATION_FIELDS = (
    "time",
    "lat",
    "lon",
    "alt",
    "Smoke_flag",
    "smoke_age_corr",
    "BC_mass_90_550_nm",
    "abs_dry_405",
    "abs_dry_532",
    "abs_dry_664",
)

ABSORPTION_COMPONENTS = ("Tot", "BC", "BrC", "OA", "Dust", "Other")
WAVELENGTHS_NM = (405, 532, 664)


class FirexModelCollocationError(ValueError):
    """Raised when the file-backed collocation contract is violated."""


def sha256(path: Path) -> str:
    """Return a file hash without loading the complete file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _attr_text(value: object, name: str) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).decode("ascii", errors="strict")
    if isinstance(value, str):
        return value
    raise FirexModelCollocationError(
        f"attribute {name} must be an ASCII string, got {type(value).__name__}"
    )


def _require_unit(dataset: h5py.Dataset, expected: str) -> None:
    if "units" not in dataset.attrs:
        raise FirexModelCollocationError(f"{dataset.name}: units attribute is absent")
    actual = _attr_text(dataset.attrs["units"], f"{dataset.name}:units").strip()
    if actual != expected:
        raise FirexModelCollocationError(
            f"{dataset.name}: units {actual!r} != required {expected!r}"
        )


def decode_observation_cf_minutes(
    values: np.ndarray,
    units: object,
    calendar: object,
) -> np.ndarray:
    """Decode the frozen FIREX-AQ observation time metadata without filenames.

    ``proleptic_gregorian`` and ``gregorian`` are equivalent for this 2019
    campaign. Any other calendar is rejected rather than approximated.
    """

    numeric = np.asarray(values, dtype=np.float64)
    if numeric.ndim != 1 or numeric.size == 0 or not np.all(np.isfinite(numeric)):
        raise FirexModelCollocationError(
            "observation time must be a nonempty, finite, one-dimensional array"
        )
    calendar_text = _attr_text(calendar, "observation time:calendar").strip().lower()
    if calendar_text not in {"gregorian", "proleptic_gregorian"}:
        raise FirexModelCollocationError(
            "unsupported observation calendar "
            f"{calendar_text!r}; expected gregorian or proleptic_gregorian"
        )
    units_text = _attr_text(units, "observation time:units")
    match = _OBS_MINUTES_SINCE.fullmatch(units_text)
    if match is None:
        raise FirexModelCollocationError(
            f"unsupported observation time units {units_text!r}"
        )
    try:
        reference = parse_utc_timestamp(match.group(1), "observation CF time reference")
    except FirexHistoryTimeError as exc:
        raise FirexModelCollocationError(
            f"invalid observation time reference: {units_text!r}"
        ) from exc
    raw_nanoseconds = numeric * _NANOSECONDS_PER_MINUTE
    rounded_nanoseconds = np.rint(raw_nanoseconds)
    if np.any(np.abs(raw_nanoseconds - rounded_nanoseconds) > 0.5):
        raise FirexModelCollocationError(
            "observation time cannot be represented at nanosecond precision"
        )
    return reference + rounded_nanoseconds.astype(np.int64).astype("timedelta64[ns]")


def read_strict_observations(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[dict[str, np.ndarray], np.ndarray, dict[str, object]]:
    """Read exactly the frozen observation selection and no relaxed rows."""

    if not path.is_file():
        raise FirexModelCollocationError(f"observation carrier is absent: {path}")
    actual_sha = sha256(path)
    if actual_sha != expected_sha256:
        raise FirexModelCollocationError(
            "observation carrier SHA-256 does not match the frozen value"
        )
    with h5py.File(path, "r") as dataset:
        missing = [name for name in OBSERVATION_FIELDS if name not in dataset]
        if missing:
            raise FirexModelCollocationError(
                "observation carrier lacks required fields: " + ", ".join(missing)
            )
        arrays = {name: np.asarray(dataset[name][...]) for name in OBSERVATION_FIELDS}
        timestamps = decode_observation_cf_minutes(
            arrays.pop("time"),
            dataset["time"].attrs.get("units"),
            dataset["time"].attrs.get("calendar"),
        )
        arrays["time"] = timestamps
        row_count = timestamps.size
        if any(value.shape != (row_count,) for value in arrays.values()):
            raise FirexModelCollocationError(
                "all required observation fields must share the time dimension"
            )

    smoke = arrays["Smoke_flag"] == 1.0
    corrected_age = np.isfinite(arrays["smoke_age_corr"]) & (
        arrays["smoke_age_corr"] >= 0.0
    )
    navigation = (
        np.isfinite(arrays["lat"])
        & np.isfinite(arrays["lon"])
        & np.isfinite(arrays["alt"])
    )
    optical = (
        np.isfinite(arrays["abs_dry_405"])
        & np.isfinite(arrays["abs_dry_532"])
        & np.isfinite(arrays["abs_dry_664"])
    )
    corrected_bc = np.isfinite(arrays["BC_mass_90_550_nm"])
    strict = smoke & corrected_age & navigation & optical & corrected_bc
    indices = np.flatnonzero(strict)
    if indices.size == 0:
        raise FirexModelCollocationError(
            "zero rows satisfy the frozen all-three-band observation contract"
        )
    selected = {name: np.asarray(values[indices]) for name, values in arrays.items()}
    selected["source_row_index"] = indices.astype(np.int64)
    report = {
        "path": str(path.resolve()),
        "sha256": actual_sha,
        "rows": int(row_count),
        "strict_rows": int(indices.size),
        "strict_first": format_utc_timestamp(selected["time"][0]),
        "strict_last": format_utc_timestamp(selected["time"][-1]),
        "contract": [
            "Smoke_flag == 1",
            "finite nonnegative smoke_age_corr",
            "finite lat, lon, alt",
            "finite abs_dry_405, abs_dry_532, abs_dry_664",
            "finite corrected BC_mass_90_550_nm",
        ],
    }
    return selected, strict, report


def _model_absorption_name(wavelength_nm: int, component: str) -> str:
    return f"AerosolDryAbs{wavelength_nm}.0nm_{component}"


def _model_field_alias(wavelength_nm: int, component: str) -> str:
    return f"model_abs_{wavelength_nm}_{component.lower()}_ambient_mm1"


def _validate_model_file_schema(
    dataset: h5py.File,
    *,
    expected_latitude: np.ndarray | None,
    expected_longitude: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    required = ["lat", "lon", "Met_BXHEIGHT", "Met_PHIS", "Met_PMID", "Met_T"]
    required += [
        _model_absorption_name(wavelength, component)
        for wavelength in WAVELENGTHS_NM
        for component in ABSORPTION_COMPONENTS
    ]
    missing = [name for name in required if name not in dataset]
    if missing:
        raise FirexModelCollocationError(
            f"{dataset.filename}: missing required model fields: {', '.join(missing)}"
        )
    latitude = np.asarray(dataset["lat"][:], dtype=np.float64)
    longitude = np.asarray(dataset["lon"][:], dtype=np.float64)
    if latitude.ndim != 1 or longitude.ndim != 1:
        raise FirexModelCollocationError("model latitude and longitude must be 1-D")
    if not np.all(np.isfinite(latitude)) or not np.all(np.isfinite(longitude)):
        raise FirexModelCollocationError("model latitude and longitude must be finite")
    _require_unit(dataset["lat"], "degrees_north")
    _require_unit(dataset["lon"], "degrees_east")
    _require_unit(dataset["Met_BXHEIGHT"], "m")
    _require_unit(dataset["Met_PHIS"], "m")
    _require_unit(dataset["Met_PMID"], "hPa")
    _require_unit(dataset["Met_T"], "K")
    for wavelength in WAVELENGTHS_NM:
        for component in ABSORPTION_COMPONENTS:
            _require_unit(dataset[_model_absorption_name(wavelength, component)], "Mm-1")
    if expected_latitude is not None and not np.array_equal(latitude, expected_latitude):
        raise FirexModelCollocationError("model latitude coordinate changes across files")
    if expected_longitude is not None and not np.array_equal(longitude, expected_longitude):
        raise FirexModelCollocationError("model longitude coordinate changes across files")
    return latitude, longitude


def load_relevant_model_records(
    paths: Sequence[Path],
    *,
    observation_time: np.ndarray,
    maximum_time_offset_seconds: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray], list[dict[str, object]]]:
    """Load only model records that can be nearest within the time tolerance."""

    if not np.isfinite(maximum_time_offset_seconds) or maximum_time_offset_seconds < 0:
        raise FirexModelCollocationError("maximum time offset must be finite and nonnegative")
    if not paths or len(set(paths)) != len(paths):
        raise FirexModelCollocationError("model history paths must be nonempty and unique")
    try:
        series = load_history_time_series(paths)
    except FirexHistoryTimeError as exc:
        raise FirexModelCollocationError(str(exc)) from exc
    timestep_ns = np.diff(series.timestamps.astype("datetime64[ns]").astype(np.int64))
    if timestep_ns.size and not np.all(timestep_ns == 20 * _NANOSECONDS_PER_MINUTE):
        raise FirexModelCollocationError(
            "model HISTORY records are not a strict 20-minute cadence"
        )
    margin_ns = int(np.rint(maximum_time_offset_seconds * 1.0e9))
    lower = np.min(observation_time).astype("datetime64[ns]") - np.timedelta64(margin_ns, "ns")
    upper = np.max(observation_time).astype("datetime64[ns]") + np.timedelta64(margin_ns, "ns")
    selected_global = np.flatnonzero(
        (series.timestamps.astype("datetime64[ns]") >= lower)
        & (series.timestamps.astype("datetime64[ns]") <= upper)
    )
    if selected_global.size == 0:
        raise FirexModelCollocationError(
            "no model HISTORY records lie within the requested matching window"
        )

    source: list[tuple[Path, int, np.datetime64]] = []
    for record in series.files:
        source.extend(
            (record.path, local_index, timestamp)
            for local_index, timestamp in enumerate(record.timestamps)
        )
    selections_by_file: dict[Path, list[tuple[int, int]]] = defaultdict(list)
    for selected_position, global_index in enumerate(selected_global):
        path, local_index, _ = source[int(global_index)]
        selections_by_file[path].append((selected_position, local_index))

    raw_fields = ["Met_BXHEIGHT", "Met_PHIS", "Met_PMID", "Met_T"]
    raw_fields += [
        _model_absorption_name(wavelength, component)
        for wavelength in WAVELENGTHS_NM
        for component in ABSORPTION_COMPONENTS
    ]
    loaded: dict[str, list[np.ndarray | None]] = {
        name: [None] * selected_global.size for name in raw_fields
    }
    latitude: np.ndarray | None = None
    longitude: np.ndarray | None = None
    for path in (record.path for record in series.files):
        if path not in selections_by_file:
            continue
        with h5py.File(path, "r") as dataset:
            latitude, longitude = _validate_model_file_schema(
                dataset, expected_latitude=latitude, expected_longitude=longitude
            )
            for selected_position, local_index in selections_by_file[path]:
                for name in raw_fields:
                    loaded[name][selected_position] = np.asarray(
                        dataset[name][local_index, ...], dtype=np.float64
                    )
    if latitude is None or longitude is None:
        raise FirexModelCollocationError("selected model records could not be read")
    arrays: dict[str, np.ndarray] = {}
    for name, values in loaded.items():
        if any(value is None for value in values):
            raise FirexModelCollocationError(f"missing selected record for {name}")
        arrays[name] = np.stack([value for value in values if value is not None])
        if not np.all(np.isfinite(arrays[name])):
            raise FirexModelCollocationError(f"selected model field {name} is nonfinite")
    if np.any(arrays["Met_BXHEIGHT"] <= 0.0):
        raise FirexModelCollocationError("selected Met_BXHEIGHT must be positive")
    for wavelength in WAVELENGTHS_NM:
        for component in ABSORPTION_COMPONENTS:
            name = _model_absorption_name(wavelength, component)
            if np.any(arrays[name] < 0.0):
                raise FirexModelCollocationError(
                    f"selected model absorption field {name} is negative"
                )

    selected_source = [
        {
            "path": str(source[int(global_index)][0]),
            "local_record_index": int(source[int(global_index)][1]),
            "timestamp": format_utc_timestamp(source[int(global_index)][2]),
        }
        for global_index in selected_global
    ]
    return (
        series.timestamps[selected_global],
        latitude,
        longitude,
        arrays["Met_BXHEIGHT"],
        arrays,
        selected_source,
    )


def _metric(model: np.ndarray, observation: np.ndarray) -> dict[str, float | int | None]:
    delta = model - observation
    result: dict[str, float | int | None] = {
        "n": int(delta.size),
        "model_mean_mm1": float(np.mean(model)),
        "observation_mean_mm1": float(np.mean(observation)),
        "bias_model_minus_observation_mm1": float(np.mean(delta)),
        "rmse_mm1": float(np.sqrt(np.mean(delta * delta))),
    }
    if delta.size >= 2 and np.std(model) > 0.0 and np.std(observation) > 0.0:
        result["pearson_r"] = float(np.corrcoef(model, observation)[0, 1])
    else:
        result["pearson_r"] = None
    return result


def _number(value: object) -> bool | float | int | str | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, np.datetime64):
        return format_utc_timestamp(value)
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def build_collocation(
    *,
    observation_path: Path,
    expected_observation_sha256: str,
    model_history_paths: Sequence[Path],
    maximum_time_offset_seconds: float,
    maximum_vertical_offset_m: float,
    aop_reference_pressure_hpa: float,
    aop_reference_temperature_k: float,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Return summary and row-level collocations after all gates pass."""

    if not np.isfinite(maximum_vertical_offset_m) or maximum_vertical_offset_m < 0:
        raise FirexModelCollocationError("maximum vertical offset must be finite and nonnegative")
    observations, _, observation_report = read_strict_observations(
        observation_path, expected_sha256=expected_observation_sha256
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
        observation_time=observations["time"],
        maximum_time_offset_seconds=maximum_time_offset_seconds,
    )

    model_fields: dict[str, np.ndarray] = {
        "model_pressure_hpa": model_arrays["Met_PMID"],
        "model_temperature_k": model_arrays["Met_T"],
    }
    aliases: dict[str, str] = {}
    for wavelength in WAVELENGTHS_NM:
        for component in ABSORPTION_COMPONENTS:
            alias = _model_field_alias(wavelength, component)
            aliases[alias] = _model_absorption_name(wavelength, component)
            model_fields[alias] = model_arrays[aliases[alias]]

    # HISTORY metadata explicitly identifies Met_PHIS as a surface height in m.
    # The tested matcher accepts geopotential in m2 s-2 and performs /g itself.
    surface_geopotential = model_arrays["Met_PHIS"] * G_STANDARD_M_S2
    try:
        matched = match_aircraft_to_model(
            observation_time=observations["time"],
            observation_latitude=observations["lat"],
            observation_longitude=observations["lon"],
            observation_altitude_m=observations["alt"],
            model_time=model_time,
            model_latitude=model_latitude,
            model_longitude=model_longitude,
            model_box_height_m=model_box_height,
            model_surface_geopotential_m2_s2=surface_geopotential,
            model_fields=model_fields,
            maximum_time_offset_seconds=maximum_time_offset_seconds,
            maximum_vertical_offset_m=maximum_vertical_offset_m,
        )
    except FirexModelMatchError as exc:
        raise FirexModelCollocationError(str(exc)) from exc

    standard_volume: dict[str, np.ndarray] = {}
    accepted = matched.valid
    pressure = matched.sampled_fields["model_pressure_hpa"]
    temperature = matched.sampled_fields["model_temperature_k"]
    for alias in aliases:
        converted = np.full(accepted.shape, np.nan, dtype=np.float64)
        if np.any(accepted):
            converted[accepted] = convert_matched_absorption_to_aop_reference(
                matched.sampled_fields[alias][accepted],
                pressure[accepted],
                temperature[accepted],
                aop_reference_pressure_hpa=aop_reference_pressure_hpa,
                aop_reference_temperature_k=aop_reference_temperature_k,
            )
        standard_volume[alias] = converted

    rows: list[dict[str, object]] = []
    for row_index in range(accepted.size):
        time_index = int(matched.model_time_index[row_index])
        source = model_time_sources[time_index] if time_index >= 0 else None
        row: dict[str, object] = {
            "observation_row_index": int(observations["source_row_index"][row_index]),
            "observation_time_utc": format_utc_timestamp(observations["time"][row_index]),
            "observation_latitude_degrees": observations["lat"][row_index],
            "observation_longitude_degrees": observations["lon"][row_index],
            "observation_altitude_m": observations["alt"][row_index],
            "observation_smoke_age_corr_s": observations["smoke_age_corr"][row_index],
            "observation_corrected_bc_ng_m3": observations["BC_mass_90_550_nm"][row_index],
            "observation_abs_405_mm1": observations["abs_dry_405"][row_index],
            "observation_abs_532_mm1": observations["abs_dry_532"][row_index],
            "observation_abs_664_mm1": observations["abs_dry_664"][row_index],
            "match_valid": bool(accepted[row_index]),
            "match_rejection_reason": str(matched.rejection_reason[row_index]),
            "model_time_utc": source["timestamp"] if source else None,
            "model_history_file": source["path"] if source else None,
            "model_history_local_record_index": source["local_record_index"] if source else None,
            "model_time_offset_seconds": matched.time_offset_seconds[row_index],
            "model_latitude_index": matched.model_lat_index[row_index],
            "model_longitude_index": matched.model_lon_index[row_index],
            "model_level_index": matched.model_level_index[row_index],
            "model_latitude_offset_degrees": matched.latitude_offset_degrees[row_index],
            "model_longitude_offset_degrees": matched.longitude_offset_degrees[row_index],
            "model_altitude_offset_m": matched.altitude_offset_m[row_index],
            "model_layer_centre_altitude_m": matched.model_layer_centre_altitude_m[row_index],
            "model_pressure_hpa": pressure[row_index],
            "model_temperature_k": temperature[row_index],
        }
        for alias in aliases:
            row[alias] = matched.sampled_fields[alias][row_index]
            row[alias.replace("_ambient_", "_aop_reference_")] = standard_volume[alias][
                row_index
            ]
        rows.append({key: _number(value) for key, value in row.items()})

    metrics: dict[str, dict[str, float | int | None]] = {}
    for wavelength in WAVELENGTHS_NM:
        alias = _model_field_alias(wavelength, "Tot")
        valid = accepted & np.isfinite(standard_volume[alias])
        observation = observations[f"abs_dry_{wavelength}"][valid].astype(np.float64)
        model = standard_volume[alias][valid]
        metrics[str(wavelength)] = _metric(model, observation) if model.size else {
            "n": 0,
            "model_mean_mm1": None,
            "observation_mean_mm1": None,
            "bias_model_minus_observation_mm1": None,
            "rmse_mm1": None,
            "pearson_r": None,
        }

    reason_counts = Counter(str(value) for value in matched.rejection_reason)
    model_provenance = [
        {"path": str(path.resolve()), "sha256": sha256(path)}
        for path in model_history_paths
    ]
    summary: dict[str, object] = {
        "schema_version": "firex-model-collocation-v1",
        "result": "completed",
        "observation": observation_report,
        "model_history": {
            "files": model_provenance,
            "selected_records": model_time_sources,
            "selected_first": format_utc_timestamp(model_time[0]),
            "selected_last": format_utc_timestamp(model_time[-1]),
            "time_contract": "native CF minutes-since coordinate, 20-minute cadence",
            "surface_height_adapter": "Met_PHIS m multiplied by g before matcher geopotential interface",
        },
        "matching": {
            "maximum_time_offset_seconds": maximum_time_offset_seconds,
            "maximum_vertical_offset_m": maximum_vertical_offset_m,
            "strict_observation_rows": int(accepted.size),
            "accepted_rows": int(np.count_nonzero(accepted)),
            "rejection_counts": dict(sorted(reason_counts.items())),
        },
        "volume_state": {
            "model_input": "dry ambient volume",
            "model_output": "dry AOP reference volume",
            "aop_reference_pressure_hpa": aop_reference_pressure_hpa,
            "aop_reference_temperature_k": aop_reference_temperature_k,
        },
        "metrics_model_minus_observation": metrics,
        "field_mapping": aliases,
        "non_claims": [
            "No observation or model NetCDF file or metadata was modified.",
            "No two-band substitution or relaxed observation selection was used.",
            "This collocation is not model tuning or a claim of scientific skill.",
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
    """Write only newly requested result files after a complete computation."""

    if output_json.resolve() == output_csv.resolve():
        raise FirexModelCollocationError("JSON and CSV outputs must differ")
    if not rows:
        raise FirexModelCollocationError("collocation produced no strict rows")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", required=True, type=Path)
    parser.add_argument("--expected-observation-sha256", required=True)
    parser.add_argument("--model-history", required=True, nargs="+", type=Path)
    parser.add_argument("--maximum-time-offset-seconds", type=float, default=1800.0)
    parser.add_argument("--maximum-vertical-offset-m", type=float, default=1000.0)
    parser.add_argument("--aop-reference-pressure-hpa", type=float, required=True)
    parser.add_argument("--aop-reference-temperature-k", type=float, required=True)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary, rows = build_collocation(
        observation_path=args.observation,
        expected_observation_sha256=args.expected_observation_sha256,
        model_history_paths=args.model_history,
        maximum_time_offset_seconds=args.maximum_time_offset_seconds,
        maximum_vertical_offset_m=args.maximum_vertical_offset_m,
        aop_reference_pressure_hpa=args.aop_reference_pressure_hpa,
        aop_reference_temperature_k=args.aop_reference_temperature_k,
    )
    write_results(
        summary,
        rows,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
