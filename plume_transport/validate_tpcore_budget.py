#!/usr/bin/env python3
"""Validate the runtime-gated PLUME-012 TPCORE causal budget ledger.

This is intentionally a diagnostic validator, not a science-acceptance
validator.  It accepts a localized non-conservation result and reports the
first boundary containing it; incomplete records or unreconciled checkpoint /
Budget evidence are failures.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from manifest_utils import load_manifest


TAGS = ("PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE")
AGING_TAGS = TAGS + tuple(f"{tag}_PI" for tag in TAGS)
V1_BOUNDARIES = (
    "TPCORE_ENTRY",
    "PRE_QCKXYZ",
    "POST_QCKXYZ",
    "TPCORE_EXIT_POST_RESET",
)
V2_BOUNDARIES = (
    "TPCORE_ENTRY",
    "PRE_QCKXYZ",
    "POST_QCKXYZ",
    "PRE_QPTR_NEGATIVE_FLOOR",
    "POST_QPTR_NEGATIVE_FLOOR",
    "TPCORE_EXIT_POST_RESET",
)
SCHEMA_VERSION_V1 = "plume-tpcore-budget-v1"
SCHEMA_VERSION_V2 = "plume-tpcore-budget-v2"
SCHEMA_BOUNDARIES = {
    SCHEMA_VERSION_V1: V1_BOUNDARIES,
    SCHEMA_VERSION_V2: V2_BOUNDARIES,
}
COLUMNS_V1 = (
    "schema_version",
    "run_id",
    "manifest_id",
    "model_date",
    "model_time",
    "elapsed_seconds",
    "heartbeat_index",
    "omp_thread_count",
    "tpcore_call_index",
    "boundary",
    "tag",
    "global_mass_kg",
    "boundary_delta_kg",
    "global_dry_air_mass_kg",
    "negative_cell_count",
    "minimum_mixing_ratio",
    "total_negative_mass_kg",
    "corrected_cell_count",
    "correction_mass_delta_kg",
)
COLUMNS_V2 = (*COLUMNS_V1, "qckxyz_invoked")
SCHEMA_COLUMNS = {
    SCHEMA_VERSION_V1: COLUMNS_V1,
    SCHEMA_VERSION_V2: COLUMNS_V2,
}
INTEGER_FIELDS = {
    "model_date",
    "model_time",
    "elapsed_seconds",
    "heartbeat_index",
    "omp_thread_count",
    "tpcore_call_index",
    "negative_cell_count",
    "corrected_cell_count",
    "qckxyz_invoked",
}
FLOAT_FIELDS = {
    "global_mass_kg",
    "boundary_delta_kg",
    "global_dry_air_mass_kg",
    "minimum_mixing_ratio",
    "total_negative_mass_kg",
    "correction_mass_delta_kg",
}


@dataclass(frozen=True)
class Record:
    schema_version: str
    run_id: str
    manifest_id: str
    model_date: int
    model_time: int
    elapsed_seconds: int
    heartbeat_index: int
    omp_thread_count: int
    tpcore_call_index: int
    boundary: str
    tag: str
    global_mass_kg: float
    boundary_delta_kg: float
    global_dry_air_mass_kg: float
    negative_cell_count: int
    minimum_mixing_ratio: float
    total_negative_mass_kg: float
    corrected_cell_count: int
    correction_mass_delta_kg: float
    qckxyz_invoked: int | None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def finite_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{label}: not a floating-point value") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{label}: value is not finite")
    return parsed


def parse_record(
    row: dict[str, str], row_number: int, columns: tuple[str, ...]
) -> Record:
    if set(row) != set(columns):
        missing = sorted(set(columns).difference(row))
        extra = sorted(set(row).difference(columns))
        raise ValueError(f"ledger row {row_number}: missing={missing}, extra={extra}")
    parsed: dict[str, Any] = {}
    for key in columns:
        value = row[key]
        if value is None or value == "":
            raise ValueError(f"ledger row {row_number}: {key} is empty")
        if key in INTEGER_FIELDS:
            try:
                parsed[key] = int(value)
            except ValueError as error:
                raise ValueError(f"ledger row {row_number}: {key} is not an integer") from error
        elif key in FLOAT_FIELDS:
            parsed[key] = finite_float(value, f"ledger row {row_number}: {key}")
        else:
            parsed[key] = value
    if "qckxyz_invoked" not in parsed:
        parsed["qckxyz_invoked"] = None
    return Record(**parsed)


def read_ledger(path: Path) -> list[Record]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        if columns not in SCHEMA_COLUMNS.values():
            raise ValueError(
                f"{path}: header {reader.fieldnames!r} does not match a supported schema"
            )
        records = [
            parse_record(row, number, columns) for number, row in enumerate(reader, 2)
        ]
    if not records:
        raise ValueError(f"{path}: ledger has no records")
    return records


def relative_difference(left: float, right: float, floor: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), floor)


def relative_l1(actual: np.ndarray, reference: np.ndarray, floor: float) -> float:
    if actual.shape != reference.shape:
        raise ValueError(f"array shape mismatch: {actual.shape} != {reference.shape}")
    difference = float(np.abs(actual - reference).sum(dtype=np.float64))
    denominator = max(float(np.abs(reference).sum(dtype=np.float64)), floor)
    return difference / denominator


def require_close(
    actual: float,
    expected: float,
    relative_tolerance: float,
    absolute_tolerance: float,
    label: str,
) -> float:
    difference = abs(actual - expected)
    relative = relative_difference(actual, expected, absolute_tolerance)
    if difference > absolute_tolerance and relative > relative_tolerance:
        raise ValueError(
            f"{label}: actual={actual:.17e}, expected={expected:.17e}, "
            f"relative_error={relative:.17e}"
        )
    return relative


def checkpoint_path(directory: Path, label: str, model_time: datetime) -> Path:
    return directory / (
        f"GEOSChem.PlumeCheckpoint.{label}.{model_time.strftime('%Y%m%d_%H%M%S')}z.nc4"
    )


def read_checkpoint_masses(path: Path, expected_tags: tuple[str, ...] = TAGS) -> dict[str, float]:
    with h5py.File(path, "r") as dataset:
        values = np.asarray(dataset["global_plume_mass"][:], dtype=np.float64)
        tag_names = dataset["tag_id"].attrs.get("tag_names")
        if isinstance(tag_names, bytes):
            tag_names = tag_names.decode("utf-8")
        if str(tag_names) != ",".join(expected_tags):
            raise ValueError(f"{path}: tag-name metadata differs from the checkpoint contract")
        if values.shape != (len(expected_tags),) or np.any(~np.isfinite(values)):
            raise ValueError(f"{path}: invalid global plume mass")
    return {tag: float(values[index]) for index, tag in enumerate(expected_tags)}


def read_budget_record_time(path: Path) -> datetime:
    """Return the sole time coordinate carried by a Budget diagnostic file."""
    with h5py.File(path, "r") as dataset:
        if "time" not in dataset:
            raise KeyError(f"{path}: missing time coordinate")
        values = np.asarray(dataset["time"][:], dtype=np.float64)
        if values.shape != (1,) or np.any(~np.isfinite(values)):
            raise ValueError(f"{path}: invalid Budget time coordinate")
        units = dataset["time"].attrs.get("units")
        if isinstance(units, bytes):
            units = units.decode("utf-8")
        prefix = "minutes since "
        if not isinstance(units, str) or not units.startswith(prefix):
            raise ValueError(f"{path}: unsupported Budget time units {units!r}")
        calendar = dataset["time"].attrs.get("calendar")
        if isinstance(calendar, bytes):
            calendar = calendar.decode("utf-8")
        if str(calendar) != "gregorian":
            raise ValueError(f"{path}: unsupported Budget calendar {calendar!r}")
    try:
        reference = datetime.fromisoformat(units[len(prefix):]).replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ValueError(f"{path}: invalid Budget time reference {units!r}") from error
    return reference + timedelta(minutes=float(values[0]))


def read_budget_transport_column_delta(path: Path, tag: str, duration_s: float) -> np.ndarray:
    name = f"BudgetTransportFull_{tag}"
    with h5py.File(path, "r") as dataset:
        if name not in dataset:
            raise KeyError(f"{path}: missing {name}")
        values = np.asarray(dataset[name][:], dtype=np.float64)
        if values.ndim != 3 or values.shape[0] != 1 or np.any(~np.isfinite(values)):
            raise ValueError(f"{path}: invalid {name}")
        units = dataset[name].attrs.get("units")
        if isinstance(units, bytes):
            units = units.decode("utf-8")
        if str(units) != "kg s-1":
            raise ValueError(f"{path}: {name} has unexpected units {units!r}")
        averaging_method = dataset[name].attrs.get("averaging_method")
        if isinstance(averaging_method, bytes):
            averaging_method = averaging_method.decode("utf-8")
        if str(averaging_method) != "time-averaged":
            raise ValueError(f"{path}: {name} is not time-averaged")
    return values[0] * duration_s


def read_checkpoint_column_mass(path: Path, tag: str) -> np.ndarray:
    name = f"PlumeMass_{tag}"
    with h5py.File(path, "r") as dataset:
        if name not in dataset:
            raise KeyError(f"{path}: missing {name}")
        values = np.asarray(dataset[name][:], dtype=np.float64)
        if values.ndim != 3 or np.any(~np.isfinite(values)):
            raise ValueError(f"{path}: invalid {name}")
    return values.sum(axis=0, dtype=np.float64)


def choose_budget_paths(run_directory: Path, requested: list[Path] | None) -> tuple[Path, ...]:
    if requested:
        paths = tuple(path.resolve() for path in requested)
        if len(set(paths)) != len(paths):
            raise ValueError("Budget diagnostic arguments must not repeat a file")
        return paths
    matches = sorted((run_directory / "OutputDir").glob("GEOSChem.Budget.*.nc4"))
    if not matches:
        raise ValueError("no Budget diagnostics found")
    return tuple(path.resolve() for path in matches)


def budget_interval_durations_s(
    file_count: int,
    expected_heartbeats: int,
    timestep_s: int,
    duration_s: float,
) -> tuple[float, ...]:
    """Allow one full-duration file or a reviewed file for each heartbeat."""
    if file_count == 1:
        return (duration_s,)
    if file_count == expected_heartbeats:
        return (float(timestep_s),) * expected_heartbeats
    raise ValueError(
        "Budget diagnostics must contain either one full-duration file or "
        "one file for each expected transport heartbeat; "
        f"found {file_count} for {expected_heartbeats} heartbeats"
    )


def validate_budget_file_schedule(
    paths: tuple[Path, ...],
    intervals_s: tuple[float, ...],
    start: datetime,
    timestep_s: int,
) -> None:
    """Fail closed if a Budget file is missing, stale, duplicated, or unordered."""
    if len(paths) != len(intervals_s):
        raise AssertionError("Budget file schedule has inconsistent lengths")
    expected_times = (
        (start,)
        if len(paths) == 1
        else tuple(start + timedelta(seconds=index * timestep_s) for index in range(len(paths)))
    )
    actual_times = tuple(read_budget_record_time(path) for path in paths)
    if actual_times != expected_times:
        raise ValueError(
            "Budget diagnostic times differ from the frozen heartbeat schedule: "
            f"actual={actual_times}, expected={expected_times}"
        )


def validate_ledger(
    manifest: dict[str, Any], ledger_path: Path, checkpoint_directory: Path, budget_paths: tuple[Path, ...]
) -> dict[str, Any]:
    runtime = manifest["tpcore_budget_runtime"]
    acceptance = manifest["acceptance"]
    run = manifest["run"]
    schema_version = str(runtime["schema_version"])
    if schema_version not in SCHEMA_BOUNDARIES:
        raise ValueError(f"unsupported manifest ledger schema {schema_version!r}")
    boundaries = SCHEMA_BOUNDARIES[schema_version]
    expected_manifest_boundaries = tuple(str(value) for value in runtime["expected_boundaries"])
    if expected_manifest_boundaries != boundaries:
        raise ValueError("manifest TPCORE boundary sequence differs from its ledger schema")
    case_id = str(manifest["case_id"])
    manifest_id = str(runtime["manifest_id"])
    expected_threads = int(run["omp_threads"])
    expected_qckxyz_invoked = int(
        bool(run["operators"]["transport_fill_negative_values"])
    )
    expected_heartbeats = int(run["expected_dynamic_heartbeats"])
    timestep_s = int(run["transport_timestep_s"])
    start = parse_utc(str(run["start"]))
    duration_s = (parse_utc(str(run["end"])) - start).total_seconds()
    if duration_s != expected_heartbeats * timestep_s:
        raise ValueError("TPCORE diagnostic duration does not equal its heartbeat contract")
    budget_intervals_s = budget_interval_durations_s(
        len(budget_paths), expected_heartbeats, timestep_s, duration_s
    )
    validate_budget_file_schedule(budget_paths, budget_intervals_s, start, timestep_s)
    budget_report = {
        "paths": [str(path) for path in budget_paths],
        "sha256": [sha256(path) for path in budget_paths],
        "interval_durations_s": list(budget_intervals_s),
    }

    relative_tolerance = float(acceptance["tpcore_budget_checkpoint_relative"])
    absolute_tolerance = float(acceptance["tpcore_budget_absolute_kg"])
    conservation_tolerance = float(acceptance["transport_conservation_relative"])
    denominator_floor = float(acceptance["relative_denominator_floor_kg"])
    budget_tolerance = float(acceptance["budget_transport_crosscheck_relative_l1"])
    if min(relative_tolerance, absolute_tolerance, conservation_tolerance, denominator_floor, budget_tolerance) < 0.0:
        raise ValueError("Phase-A budget tolerances must be non-negative")

    records = read_ledger(ledger_path)
    expected_count = expected_heartbeats * len(TAGS) * len(boundaries)
    if int(runtime["expected_records"]) != expected_count:
        raise ValueError("manifest TPCORE budget record count is inconsistent with its cadence")
    if len(records) != expected_count:
        raise ValueError(f"ledger has {len(records)} records, expected {expected_count}")
    index: dict[tuple[int, str, str], Record] = {}
    for record in records:
        if record.schema_version != schema_version:
            raise ValueError(f"unsupported schema {record.schema_version!r}")
        if record.run_id != case_id or record.manifest_id != manifest_id:
            raise ValueError("ledger run/manifest provenance does not match the manifest")
        if record.tag not in TAGS or record.boundary not in boundaries:
            raise ValueError("ledger has an unknown tag or boundary")
        if record.omp_thread_count != expected_threads:
            raise ValueError("ledger thread count differs from the frozen case control")
        if record.tpcore_call_index not in range(1, expected_heartbeats + 1):
            raise ValueError("ledger TPCORE-call index is out of range")
        if record.heartbeat_index != record.tpcore_call_index:
            raise ValueError("ledger heartbeat and TPCORE-call index disagree")
        expected_elapsed = (record.tpcore_call_index - 1) * timestep_s
        expected_time = start + timedelta(seconds=expected_elapsed)
        if record.elapsed_seconds != expected_elapsed:
            raise ValueError("ledger elapsed time differs from the heartbeat contract")
        if record.model_date != int(expected_time.strftime("%Y%m%d")) or record.model_time != int(expected_time.strftime("%H%M%S")):
            raise ValueError("ledger model time differs from the heartbeat contract")
        if record.negative_cell_count < 0 or record.corrected_cell_count < 0:
            raise ValueError("ledger has a negative cell count")
        if record.total_negative_mass_kg < 0.0:
            raise ValueError("ledger total negative mass must be a magnitude")
        if schema_version == SCHEMA_VERSION_V2:
            if record.qckxyz_invoked not in (0, 1):
                raise ValueError("v2 ledger qckxyz_invoked must be zero or one")
            if record.qckxyz_invoked != expected_qckxyz_invoked:
                raise ValueError("ledger Qckxyz invocation differs from the manifest LFILL switch")
        elif record.qckxyz_invoked is not None:
            raise ValueError("v1 ledger unexpectedly contains qckxyz_invoked")
        key = (record.tpcore_call_index, record.tag, record.boundary)
        if key in index:
            raise ValueError(f"ledger has duplicate record {key}")
        index[key] = record

    expected_keys = {
        (call, tag, boundary)
        for call in range(1, expected_heartbeats + 1)
        for tag in TAGS
        for boundary in boundaries
    }
    if set(index) != expected_keys:
        missing = sorted(expected_keys.difference(index))
        extra = sorted(set(index).difference(expected_keys))
        raise ValueError(f"ledger boundary sequence is incomplete; missing={missing}, extra={extra}")
    positions = {
        (record.tpcore_call_index, record.tag, record.boundary): position
        for position, record in enumerate(records)
    }
    checkpoint_tags = (
        AGING_TAGS
        if manifest.get("preparation_contract") == "stage1-aging-v1"
        else TAGS
    )
    for call in range(1, expected_heartbeats + 1):
        for tag in TAGS:
            ordered_positions = [positions[(call, tag, boundary)] for boundary in boundaries]
            if ordered_positions != sorted(ordered_positions):
                raise ValueError(f"{tag} heartbeat {call}: boundary records are out of order")
    for call in range(1, expected_heartbeats):
        current = [positions[(call, tag, boundary)] for tag in TAGS for boundary in boundaries]
        following = [
            positions[(call + 1, tag, boundary)] for tag in TAGS for boundary in boundaries
        ]
        if max(current) >= min(following):
            raise ValueError("TPCORE-call records are not globally ordered")

    by_tag: dict[str, dict[str, Any]] = {}
    transport_delta_by_tag: dict[str, float] = {}
    for tag in TAGS:
        calls: dict[str, Any] = {}
        total_transport_delta = 0.0
        first_nonconserving: str | None = None
        for call in range(1, expected_heartbeats + 1):
            sequence = [index[(call, tag, boundary)] for boundary in boundaries]
            entry = sequence[0]
            exit_post_reset = sequence[-1]
            expected_deltas = (
                0.0,
                *(
                    later.global_mass_kg - earlier.global_mass_kg
                    for earlier, later in zip(sequence, sequence[1:])
                ),
            )
            for record, expected_delta in zip(sequence, expected_deltas, strict=True):
                require_close(
                    record.boundary_delta_kg,
                    expected_delta,
                    relative_tolerance,
                    absolute_tolerance,
                    f"{tag} heartbeat {call} {record.boundary} boundary delta",
                )

            pre_qck = index[(call, tag, "PRE_QCKXYZ")]
            post_qck = index[(call, tag, "POST_QCKXYZ")]
            zero_correction_records = [entry, pre_qck, exit_post_reset]
            if schema_version == SCHEMA_VERSION_V2:
                pre_floor = index[(call, tag, "PRE_QPTR_NEGATIVE_FLOOR")]
                post_floor = index[(call, tag, "POST_QPTR_NEGATIVE_FLOOR")]
                zero_correction_records.append(pre_floor)
            for record in zero_correction_records:
                if record.corrected_cell_count != 0:
                    raise ValueError(
                        f"{tag} heartbeat {call}: {record.boundary} correction count is nonzero"
                    )
                if record.correction_mass_delta_kg != 0.0:
                    raise ValueError(
                        f"{tag} heartbeat {call}: {record.boundary} correction delta is nonzero"
                    )

            require_close(
                post_qck.correction_mass_delta_kg,
                post_qck.global_mass_kg - pre_qck.global_mass_kg,
                relative_tolerance,
                absolute_tolerance,
                f"{tag} heartbeat {call} Qckxyz correction delta",
            )
            for record in (pre_qck, post_qck):
                if record.minimum_mixing_ratio > 0.0:
                    raise ValueError(
                        f"{tag} heartbeat {call}: Qckxyz minimum mixing ratio is positive"
                    )

            if schema_version == SCHEMA_VERSION_V2:
                if expected_qckxyz_invoked == 0:
                    if post_qck.corrected_cell_count != 0:
                        raise ValueError(
                            f"{tag} heartbeat {call}: bypassed Qckxyz corrected cells"
                        )
                    require_close(
                        post_qck.global_mass_kg,
                        pre_qck.global_mass_kg,
                        relative_tolerance,
                        absolute_tolerance,
                        f"{tag} heartbeat {call} bypassed Qckxyz mass",
                    )
                    if post_qck.negative_cell_count != pre_qck.negative_cell_count:
                        raise ValueError(
                            f"{tag} heartbeat {call}: bypassed Qckxyz negative count changed"
                        )
                    require_close(
                        post_qck.minimum_mixing_ratio,
                        pre_qck.minimum_mixing_ratio,
                        relative_tolerance,
                        absolute_tolerance,
                        f"{tag} heartbeat {call} bypassed Qckxyz minimum",
                    )
                    require_close(
                        post_qck.total_negative_mass_kg,
                        pre_qck.total_negative_mass_kg,
                        relative_tolerance,
                        absolute_tolerance,
                        f"{tag} heartbeat {call} bypassed Qckxyz negative mass",
                    )

                require_close(
                    post_floor.correction_mass_delta_kg,
                    post_floor.global_mass_kg - pre_floor.global_mass_kg,
                    relative_tolerance,
                    absolute_tolerance,
                    f"{tag} heartbeat {call} concentration-floor correction delta",
                )
                if post_floor.corrected_cell_count != pre_floor.negative_cell_count:
                    raise ValueError(
                        f"{tag} heartbeat {call}: concentration-floor corrected count differs "
                        "from its pre-floor negative count"
                    )
                if post_floor.negative_cell_count != 0 or post_floor.total_negative_mass_kg != 0.0:
                    raise ValueError(
                        f"{tag} heartbeat {call}: concentration floor left negative tracer mass"
                    )
                if post_floor.minimum_mixing_ratio < 0.0:
                    raise ValueError(
                        f"{tag} heartbeat {call}: concentration floor minimum remains negative"
                    )

            threshold = conservation_tolerance * max(
                abs(entry.global_mass_kg), denominator_floor
            )
            for record, delta in zip(sequence[1:], expected_deltas[1:], strict=True):
                if first_nonconserving is None and abs(delta) > threshold:
                    first_nonconserving = record.boundary
            total_transport_delta += exit_post_reset.global_mass_kg - entry.global_mass_kg
            calls[str(call)] = {
                "records": {record.boundary: asdict(record) for record in sequence},
                "conservation_threshold_kg": threshold,
            }
        by_tag[tag] = {
            "first_nonconserving_boundary": first_nonconserving,
            "calls": calls,
        }
        transport_delta_by_tag[tag] = total_transport_delta

    checkpoints_enabled = bool(
        manifest.get("checkpoint_runtime", {}).get("enabled", False)
    )
    if not checkpoints_enabled:
        classifications = {
            tag: by_tag[tag]["first_nonconserving_boundary"] for tag in TAGS
        }
        if any(boundary == "POST_QCKXYZ" for boundary in classifications.values()):
            diagnostic_outcome = "qckxyz_localized"
        elif any(
            boundary == "POST_QPTR_NEGATIVE_FLOOR"
            for boundary in classifications.values()
        ):
            diagnostic_outcome = "qptr_negative_floor_localized"
        elif any(boundary is not None for boundary in classifications.values()):
            diagnostic_outcome = "non_qckxyz_boundary_localized"
        else:
            diagnostic_outcome = "no_resolved_nonconservation"
        return {
            "status": "pass",
            "diagnostic_outcome": diagnostic_outcome,
            "ledger_schema_version": schema_version,
            "qckxyz_invoked": (
                bool(expected_qckxyz_invoked)
                if schema_version == SCHEMA_VERSION_V2
                else None
            ),
            "case_id": case_id,
            "manifest_id": manifest_id,
            "ledger": {"path": str(ledger_path), "sha256": sha256(ledger_path)},
            "checkpoint_directory": None,
            "budget": budget_report,
            "first_nonconserving_boundary": classifications,
            "tag_records": by_tag,
            "checkpoint_reconciliation": {
                "status": "not_applicable_checkpoint_runtime_disabled"
            },
            "budget_reconciliation": {
                "status": "not_applicable_without_checkpoint_columns"
            },
        }

    checkpoint_reconciliation: dict[str, dict[str, float]] = {}
    checkpoint_transport_column_delta: dict[str, np.ndarray] = {}
    for call in range(1, expected_heartbeats + 1):
        model_time = start + timedelta(seconds=(call - 1) * timestep_s)
        c0_path = checkpoint_path(checkpoint_directory, "C0_PRE_TPCORE", model_time)
        c1_path = checkpoint_path(checkpoint_directory, "C1_POST_TPCORE", model_time)
        if not c0_path.is_file() or not c1_path.is_file():
            raise FileNotFoundError(f"missing C0/C1 checkpoint for heartbeat {call}")
        c0_all = read_checkpoint_masses(c0_path, checkpoint_tags)
        c1_all = read_checkpoint_masses(c1_path, checkpoint_tags)
        c0 = {tag: c0_all[tag] for tag in TAGS}
        c1 = {tag: c1_all[tag] for tag in TAGS}
        for tag in TAGS:
            c0_column_mass = read_checkpoint_column_mass(c0_path, tag)
            c1_column_mass = read_checkpoint_column_mass(c1_path, tag)
            column_delta = c1_column_mass - c0_column_mass
            if tag in checkpoint_transport_column_delta:
                checkpoint_transport_column_delta[tag] += column_delta
            else:
                checkpoint_transport_column_delta[tag] = column_delta
            entry = index[(call, tag, "TPCORE_ENTRY")]
            exit_post_reset = index[(call, tag, "TPCORE_EXIT_POST_RESET")]
            entry_error = require_close(
                entry.global_mass_kg,
                c0[tag],
                relative_tolerance,
                absolute_tolerance,
                f"{tag} heartbeat {call} entry/C0 reconciliation",
            )
            exit_error = require_close(
                exit_post_reset.global_mass_kg,
                c1[tag],
                relative_tolerance,
                absolute_tolerance,
                f"{tag} heartbeat {call} exit/C1 reconciliation",
            )
            checkpoint_reconciliation[f"heartbeat_{call}:{tag}"] = {
                "entry_to_C0_relative_error": entry_error,
                "exit_to_C1_relative_error": exit_error,
                "entry_global_dry_air_mass_kg": entry.global_dry_air_mass_kg,
                "exit_global_dry_air_mass_kg": exit_post_reset.global_dry_air_mass_kg,
            }

    budget_reconciliation: dict[str, dict[str, float]] = {}
    source_mass_per_tag = float(manifest["source"]["total_mass_per_tag_kg"])
    for tag in TAGS:
        budget_contributions = tuple(
            read_budget_transport_column_delta(path, tag, interval_s)
            for path, interval_s in zip(budget_paths, budget_intervals_s, strict=True)
        )
        budget_column_delta = np.zeros_like(budget_contributions[0], dtype=np.float64)
        for contribution in budget_contributions:
            budget_column_delta += contribution
        checkpoint_column_delta = checkpoint_transport_column_delta[tag]
        budget_checkpoint_error = relative_l1(
            budget_column_delta,
            checkpoint_column_delta,
            denominator_floor,
        )
        if budget_checkpoint_error > budget_tolerance:
            raise ValueError(
                f"{tag} BudgetTransportFull/checkpoint column-L1 reconciliation: "
                f"relative_error={budget_checkpoint_error:.17e}"
            )
        ledger_delta = transport_delta_by_tag[tag]
        checkpoint_delta = float(checkpoint_column_delta.sum(dtype=np.float64))
        ledger_checkpoint_error = require_close(
            ledger_delta,
            checkpoint_delta,
            relative_tolerance,
            absolute_tolerance,
            f"{tag} ledger/checkpoint global transport reconciliation",
        )
        budget_delta = float(budget_column_delta.sum(dtype=np.float64))
        budget_ledger_residual = budget_delta - ledger_delta
        budget_reconciliation[tag] = {
            "ledger_transport_delta_kg": ledger_delta,
            "checkpoint_transport_delta_kg": checkpoint_delta,
            "budget_transport_delta_kg": budget_delta,
            "ledger_checkpoint_relative_error": ledger_checkpoint_error,
            "budget_checkpoint_column_l1_relative_error": budget_checkpoint_error,
            "budget_ledger_global_residual_kg": budget_ledger_residual,
            "budget_ledger_global_residual_relative_to_emitted": abs(budget_ledger_residual)
            / max(source_mass_per_tag, denominator_floor),
        }

    classifications = {
        tag: by_tag[tag]["first_nonconserving_boundary"] for tag in TAGS
    }
    if any(boundary == "POST_QCKXYZ" for boundary in classifications.values()):
        diagnostic_outcome = "qckxyz_localized"
    elif any(
        boundary == "POST_QPTR_NEGATIVE_FLOOR" for boundary in classifications.values()
    ):
        diagnostic_outcome = "qptr_negative_floor_localized"
    elif any(boundary is not None for boundary in classifications.values()):
        diagnostic_outcome = "non_qckxyz_boundary_localized"
    else:
        diagnostic_outcome = "no_resolved_nonconservation"

    return {
        "status": "pass",
        "diagnostic_outcome": diagnostic_outcome,
        "ledger_schema_version": schema_version,
        "qckxyz_invoked": (
            bool(expected_qckxyz_invoked)
            if schema_version == SCHEMA_VERSION_V2
            else None
        ),
        "case_id": case_id,
        "manifest_id": manifest_id,
        "ledger": {"path": str(ledger_path), "sha256": sha256(ledger_path)},
        "checkpoint_directory": str(checkpoint_directory),
        "budget": budget_report,
        "first_nonconserving_boundary": classifications,
        "tag_records": by_tag,
        "checkpoint_reconciliation": checkpoint_reconciliation,
        "budget_reconciliation": budget_reconciliation,
    }


def failure_report(manifest_path: Path, error: Exception) -> dict[str, Any]:
    return {
        "status": "fail",
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path),
        "error_type": type(error).__name__,
        "error_message": str(error),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--checkpoint-directory", type=Path)
    parser.add_argument("--budget", type=Path, action="append")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if str(manifest["acceptance"]["contract_version"]) not in {
            "stage1-tpcore-causality-v1",
            "stage1-tpcore-causality-v2",
        }:
            raise ValueError("manifest does not declare the PLUME-012 causality contract")
        run_directory = Path(manifest["paths"]["run_directory"]).resolve()
        ledger_path = (args.ledger or Path(manifest["paths"]["tpcore_budget_file"])).resolve()
        checkpoint_directory = (
            args.checkpoint_directory or Path(manifest["paths"]["checkpoint_directory"])
        ).resolve()
        budget_paths = choose_budget_paths(run_directory, args.budget)
        result = validate_ledger(manifest, ledger_path, checkpoint_directory, budget_paths)
    except Exception as error:
        if args.report:
            args.report.write_text(
                json.dumps(failure_report(args.manifest, error), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        raise
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
