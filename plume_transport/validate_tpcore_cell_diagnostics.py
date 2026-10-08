#!/usr/bin/env python3
"""Validate the runtime-gated per-cell TPCORE positivity event ledger.

The event ledger is intentionally a diagnostic companion to the existing V2
global ledger.  It proves that the event-level bottom residuals and negative
floor replacements reconcile to the independently reduced global mass deltas.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Iterable

from validate_tpcore_budget import Record, read_ledger


CELL_SCHEMA_VERSION_V1 = "plume-tpcore-cell-events-v1"
CELL_SCHEMA_VERSION_V2 = "plume-tpcore-cell-events-v2"
CELL_SCHEMA_VERSION_V3 = "plume-tpcore-cell-events-v3"
CELL_SCHEMA_VERSION = CELL_SCHEMA_VERSION_V3
G0_100_KG_PER_HPA_M2 = 100.0 / 9.80665
CELL_COLUMNS_V1 = (
    "schema_version",
    "run_id",
    "manifest_id",
    "model_date",
    "model_time",
    "elapsed_seconds",
    "heartbeat_index",
    "omp_thread_count",
    "tpcore_call_index",
    "tag",
    "event_type",
    "i_tpcore",
    "j_tpcore",
    "k_tpcore",
    "k_model",
    "dq_after_horizontal_hpa",
    "dq_after_fzppm_hpa",
    "dq_at_correction_hpa",
    "deficit_hpa",
    "available_above_hpa",
    "withdrawn_from_above_hpa",
    "unfilled_deficit_hpa",
    "q_before_kgkg",
    "q_after_kgkg",
    "delp_hpa",
    "area_m2",
    "event_mass_delta_kg",
)
CELL_V2_EXTENSION_COLUMNS = (
    "correction_policy",
    "correction_outcome",
    "donor_count",
    "full_column_withdrawn_hpa",
    "declared_roundoff_closure_hpa",
    "correction_tolerance_hpa",
)
CELL_COLUMNS_V2 = CELL_COLUMNS_V1 + CELL_V2_EXTENSION_COLUMNS
CELL_V3_EXTENSION_COLUMNS = (
    "correction_policy",
    "correction_outcome",
    "donor_count",
    "full_column_withdrawn_hpa",
    "declared_closure_hpa",
    "ordinary_roundoff_tolerance_hpa",
    "microclosure_event_max_kg",
    "microclosure_call_max_kg",
)
CELL_COLUMNS_V3 = CELL_COLUMNS_V1 + CELL_V3_EXTENSION_COLUMNS
CELL_COLUMNS = CELL_COLUMNS_V1 + CELL_V2_EXTENSION_COLUMNS + CELL_V3_EXTENSION_COLUMNS
INTEGER_COLUMNS = {
    "model_date",
    "model_time",
    "elapsed_seconds",
    "heartbeat_index",
    "omp_thread_count",
    "tpcore_call_index",
    "i_tpcore",
    "j_tpcore",
    "k_tpcore",
    "k_model",
    "donor_count",
}
FLOAT_COLUMNS = set(CELL_COLUMNS).difference(INTEGER_COLUMNS).difference(
    {
        "schema_version",
        "run_id",
        "manifest_id",
        "tag",
        "event_type",
        "correction_policy",
        "correction_outcome",
    }
)
QCK_EVENT_TYPES = {"QCK_TOP", "QCK_INTERIOR", "QCK_BOTTOM"}
FLOOR_EVENT_TYPE = "QPTR_NEGATIVE_FLOOR"


@dataclass(frozen=True)
class CellEvent:
    schema_version: str
    run_id: str
    manifest_id: str
    model_date: int
    model_time: int
    elapsed_seconds: int
    heartbeat_index: int
    omp_thread_count: int
    tpcore_call_index: int
    tag: str
    event_type: str
    i_tpcore: int
    j_tpcore: int
    k_tpcore: int
    k_model: int
    dq_after_horizontal_hpa: float
    dq_after_fzppm_hpa: float
    dq_at_correction_hpa: float
    deficit_hpa: float
    available_above_hpa: float
    withdrawn_from_above_hpa: float
    unfilled_deficit_hpa: float
    q_before_kgkg: float
    q_after_kgkg: float
    delp_hpa: float
    area_m2: float
    event_mass_delta_kg: float
    correction_policy: str = "not_applicable"
    correction_outcome: str = "not_applicable"
    donor_count: int = 0
    full_column_withdrawn_hpa: float = 0.0
    declared_roundoff_closure_hpa: float = 0.0
    correction_tolerance_hpa: float = 0.0
    declared_closure_hpa: float = 0.0
    ordinary_roundoff_tolerance_hpa: float = 0.0
    microclosure_event_max_kg: float = 0.0
    microclosure_call_max_kg: float = 0.0


def finite_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{label}: not a floating-point value") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{label}: value is not finite")
    return parsed


def legacy_v1_extension(parsed: dict[str, str | int | float]) -> dict[str, str | int | float]:
    """Normalize archival v1 native-Qck records to the v2 event model."""

    event_type = str(parsed["event_type"])
    withdrawn = float(parsed["withdrawn_from_above_hpa"])
    unfilled = float(parsed["unfilled_deficit_hpa"])
    if event_type == "QCK_BOTTOM":
        return {
            "correction_policy": "native_immediate_donor_v1",
            "correction_outcome": "legacy_native",
            "donor_count": int(withdrawn > 0.0),
            "full_column_withdrawn_hpa": withdrawn,
            "declared_roundoff_closure_hpa": unfilled,
            "correction_tolerance_hpa": 0.0,
        }
    if event_type in QCK_EVENT_TYPES:
        return {
            "correction_policy": "native_qck_v1",
            "correction_outcome": "not_applicable",
            "donor_count": 0,
            "full_column_withdrawn_hpa": 0.0,
            "declared_roundoff_closure_hpa": 0.0,
            "correction_tolerance_hpa": 0.0,
        }
    return {
        "correction_policy": "not_applicable",
        "correction_outcome": "not_applicable",
        "donor_count": 0,
        "full_column_withdrawn_hpa": 0.0,
        "declared_roundoff_closure_hpa": 0.0,
        "correction_tolerance_hpa": 0.0,
    }


def read_events(path: Path) -> list[CellEvent]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        if fieldnames == CELL_COLUMNS_V1:
            columns = CELL_COLUMNS_V1
            expected_schema = CELL_SCHEMA_VERSION_V1
        elif fieldnames == CELL_COLUMNS_V2:
            columns = CELL_COLUMNS_V2
            expected_schema = CELL_SCHEMA_VERSION_V2
        elif fieldnames == CELL_COLUMNS_V3:
            columns = CELL_COLUMNS_V3
            expected_schema = CELL_SCHEMA_VERSION_V3
        else:
            raise ValueError(f"{path}: cell-event header does not match v1, v2, or v3")
        events: list[CellEvent] = []
        for row_number, row in enumerate(reader, 2):
            if set(row) != set(columns):
                raise ValueError(f"{path}: row {row_number} has an invalid column set")
            parsed: dict[str, str | int | float] = {}
            for column in columns:
                value = row[column]
                if value is None or value == "":
                    raise ValueError(f"{path}: row {row_number} has empty {column}")
                if column in INTEGER_COLUMNS:
                    try:
                        parsed[column] = int(value)
                    except ValueError as error:
                        raise ValueError(
                            f"{path}: row {row_number} has non-integer {column}"
                        ) from error
                elif column in FLOAT_COLUMNS:
                    parsed[column] = finite_float(value, f"{path}: row {row_number} {column}")
                else:
                    parsed[column] = value
            if expected_schema == CELL_SCHEMA_VERSION_V1:
                parsed.update(legacy_v1_extension(parsed))
            event = CellEvent(**parsed)  # type: ignore[arg-type]
            if event.schema_version != expected_schema:
                raise ValueError(f"{path}: row {row_number} has unknown schema")
            if event.event_type not in QCK_EVENT_TYPES | {FLOOR_EVENT_TYPE}:
                raise ValueError(f"{path}: row {row_number} has unknown event type")
            if min(event.i_tpcore, event.j_tpcore, event.k_tpcore, event.k_model) < 1:
                raise ValueError(f"{path}: row {row_number} has a non-positive index")
            events.append(event)
    return events


def close_enough(
    actual: float, expected: float, relative_tolerance: float, absolute_tolerance: float
) -> bool:
    difference = abs(actual - expected)
    scale = max(abs(actual), abs(expected), absolute_tolerance)
    return difference <= absolute_tolerance or difference / scale <= relative_tolerance


def require_close(
    actual: float,
    expected: float,
    relative_tolerance: float,
    absolute_tolerance: float,
    label: str,
) -> None:
    if not close_enough(actual, expected, relative_tolerance, absolute_tolerance):
        raise ValueError(
            f"{label}: actual={actual:.17e}, expected={expected:.17e}, "
            f"difference={abs(actual - expected):.17e}"
        )


def key_from_ledger(record: Record) -> tuple[int, str]:
    return (record.tpcore_call_index, record.tag)


def key_from_event(event: CellEvent) -> tuple[int, str]:
    return (event.tpcore_call_index, event.tag)


def grouped(events: Iterable[CellEvent]) -> dict[tuple[int, str], list[CellEvent]]:
    result: dict[tuple[int, str], list[CellEvent]] = {}
    for event in events:
        result.setdefault(key_from_event(event), []).append(event)
    return result


def require_event_provenance(event: CellEvent, record: Record) -> None:
    """Reject an event row that does not belong to its global-ledger row."""

    for field in (
        "run_id",
        "manifest_id",
        "model_date",
        "model_time",
        "elapsed_seconds",
        "heartbeat_index",
        "omp_thread_count",
        "tpcore_call_index",
        "tag",
    ):
        if getattr(event, field) != getattr(record, field):
            raise ValueError(
                f"{record.tpcore_call_index, record.tag}: event {field} differs "
                "from its global ledger provenance"
            )


def summarize_origin(events: Iterable[CellEvent]) -> dict[str, int]:
    counts = {"horizontal_negative": 0, "fzppm_created": 0, "qck_cascade": 0}
    for event in events:
        if event.dq_after_horizontal_hpa < 0.0:
            counts["horizontal_negative"] += 1
        elif event.dq_after_fzppm_hpa < 0.0:
            counts["fzppm_created"] += 1
        elif event.dq_at_correction_hpa < 0.0:
            counts["qck_cascade"] += 1
        else:
            raise ValueError(
                f"{event.tag} call {event.tpcore_call_index}: Qck event is not negative"
            )
    return counts


def validate(
    ledger: list[Record],
    events: list[CellEvent],
    relative_tolerance: float,
    absolute_tolerance_kg: float,
    microclosure_event_max_kg: float | None = None,
    microclosure_call_max_kg: float | None = None,
    microclosure_tag_max_kg: float | None = None,
    microclosure_all_tag_max_kg: float | None = None,
) -> dict[str, object]:
    if not events:
        raise ValueError("cell-event ledger has no events")
    event_groups = grouped(events)
    qck_post = {
        key_from_ledger(record): record
        for record in ledger
        if record.boundary == "POST_QCKXYZ"
    }
    floor_pre = {
        key_from_ledger(record): record
        for record in ledger
        if record.boundary == "PRE_QPTR_NEGATIVE_FLOOR"
    }
    floor_post = {
        key_from_ledger(record): record
        for record in ledger
        if record.boundary == "POST_QPTR_NEGATIVE_FLOOR"
    }
    required_keys = set(qck_post) | set(floor_pre) | set(floor_post)
    unexpected = sorted(set(event_groups).difference(required_keys))
    if unexpected:
        raise ValueError(f"cell-event ledger has unknown call/tag keys: {unexpected}")

    per_key: dict[str, object] = {}
    microclosure_by_tag: dict[str, float] = {}
    microclosure_total_kg = 0.0
    for key in sorted(required_keys):
        if key not in qck_post or key not in floor_pre or key not in floor_post:
            raise ValueError(f"global ledger is incomplete for call/tag {key}")
        qck_events = [
            event for event in event_groups.get(key, []) if event.event_type in QCK_EVENT_TYPES
        ]
        floor_events = [
            event
            for event in event_groups.get(key, [])
            if event.event_type == FLOOR_EVENT_TYPE
        ]
        qck_record = qck_post[key]
        pre_floor_record = floor_pre[key]
        post_floor_record = floor_post[key]
        for event in qck_events:
            require_event_provenance(event, qck_record)
        for event in floor_events:
            require_event_provenance(event, qck_record)
        if len(qck_events) != qck_record.corrected_cell_count:
            raise ValueError(
                f"{key}: Qck event count {len(qck_events)} differs from "
                f"ledger {qck_record.corrected_cell_count}"
            )
        qck_delta = sum(event.event_mass_delta_kg for event in qck_events)
        require_close(
            qck_delta,
            qck_record.correction_mass_delta_kg,
            relative_tolerance,
            absolute_tolerance_kg,
            f"{key}: Qck event mass reconciliation",
        )
        bottom_delta = sum(
            event.event_mass_delta_kg
            for event in qck_events
            if event.event_type == "QCK_BOTTOM"
        )
        require_close(
            bottom_delta,
            qck_delta,
            relative_tolerance,
            absolute_tolerance_kg,
            f"{key}: bottom residual reconciliation",
        )
        for event in qck_events:
            require_close(
                event.deficit_hpa,
                -event.dq_at_correction_hpa,
                relative_tolerance,
                1.0e-30,
                f"{key}: Qck deficit",
            )
            if event.event_type == "QCK_TOP":
                require_close(
                    event.event_mass_delta_kg,
                    0.0,
                    relative_tolerance,
                    absolute_tolerance_kg,
                    f"{key}: top Qck mass delta",
                )
            else:
                require_close(
                    event.withdrawn_from_above_hpa,
                    min(event.deficit_hpa, event.available_above_hpa),
                    relative_tolerance,
                    1.0e-30,
                    f"{key}: Qck withdrawal",
                )
                if event.event_type == "QCK_INTERIOR":
                    require_close(
                        event.event_mass_delta_kg,
                        0.0,
                        relative_tolerance,
                        absolute_tolerance_kg,
                        f"{key}: interior Qck mass delta",
                    )
                else:
                    require_close(
                        event.unfilled_deficit_hpa,
                        event.deficit_hpa - event.withdrawn_from_above_hpa,
                        relative_tolerance,
                        1.0e-30,
                        f"{key}: bottom unfilled deficit",
                    )
                    if event.schema_version == CELL_SCHEMA_VERSION_V2:
                        if (
                            event.correction_policy
                            != "full_column_nearest_above_v1"
                        ):
                            raise ValueError(f"{key}: v2 bottom event has unknown policy")
                        if event.correction_outcome not in {
                            "exact",
                            "roundoff_closed",
                        }:
                            raise ValueError(f"{key}: v2 bottom event has unknown outcome")
                        if event.correction_tolerance_hpa < 0.0:
                            raise ValueError(f"{key}: v2 bottom tolerance is negative")
                        if event.donor_count < 0:
                            raise ValueError(f"{key}: v2 bottom donor count is invalid")
                        require_close(
                            event.full_column_withdrawn_hpa,
                            event.deficit_hpa - event.declared_roundoff_closure_hpa,
                            relative_tolerance,
                            1.0e-30,
                            f"{key}: v2 full-column withdrawal",
                        )
                        if event.declared_roundoff_closure_hpa < -1.0e-30:
                            raise ValueError(f"{key}: v2 roundoff closure is negative")
                        if event.correction_outcome == "exact":
                            if event.donor_count < 1:
                                raise ValueError(f"{key}: exact correction has no donor")
                            require_close(
                                event.declared_roundoff_closure_hpa,
                                0.0,
                                relative_tolerance,
                                1.0e-30,
                                f"{key}: exact correction closure",
                            )
                            require_close(
                                event.event_mass_delta_kg,
                                0.0,
                                relative_tolerance,
                                absolute_tolerance_kg,
                                f"{key}: exact correction mass delta",
                            )
                        else:
                            if event.declared_roundoff_closure_hpa <= 0.0:
                                raise ValueError(f"{key}: roundoff closure is not positive")
                            if (
                                event.declared_roundoff_closure_hpa
                                > event.correction_tolerance_hpa
                            ):
                                raise ValueError(
                                    f"{key}: roundoff closure exceeds its tolerance"
                                )
                    elif event.schema_version == CELL_SCHEMA_VERSION_V3:
                        limits = (
                            microclosure_event_max_kg,
                            microclosure_call_max_kg,
                            microclosure_tag_max_kg,
                            microclosure_all_tag_max_kg,
                        )
                        if any(limit is None or limit <= 0.0 for limit in limits):
                            raise ValueError(
                                f"{key}: v3 validation requires four positive "
                                "microclosure ceilings"
                            )
                        if (
                            event.correction_policy
                            != "full_column_nearest_above_microclosure_v2"
                        ):
                            raise ValueError(f"{key}: v3 bottom event has unknown policy")
                        if event.correction_outcome not in {
                            "exact",
                            "roundoff_closed",
                            "microclosure_closed",
                        }:
                            raise ValueError(f"{key}: v3 bottom event has unknown outcome")
                        if event.donor_count < 0:
                            raise ValueError(f"{key}: v3 bottom donor count is invalid")
                        if event.ordinary_roundoff_tolerance_hpa < 0.0:
                            raise ValueError(f"{key}: v3 roundoff tolerance is negative")
                        require_close(
                            event.microclosure_event_max_kg,
                            float(microclosure_event_max_kg),
                            0.0,
                            0.0,
                            f"{key}: manifested event ceiling",
                        )
                        require_close(
                            event.microclosure_call_max_kg,
                            float(microclosure_call_max_kg),
                            0.0,
                            0.0,
                            f"{key}: manifested call ceiling",
                        )
                        require_close(
                            event.full_column_withdrawn_hpa,
                            event.deficit_hpa - event.declared_closure_hpa,
                            relative_tolerance,
                            1.0e-30,
                            f"{key}: v3 full-column withdrawal",
                        )
                        expected_mass_kg = (
                            event.declared_closure_hpa
                            * event.area_m2
                            * G0_100_KG_PER_HPA_M2
                        )
                        require_close(
                            event.event_mass_delta_kg,
                            expected_mass_kg,
                            relative_tolerance,
                            absolute_tolerance_kg,
                            f"{key}: declared pressure-to-mass closure",
                        )
                        if event.correction_outcome == "exact":
                            if event.donor_count < 1:
                                raise ValueError(f"{key}: exact correction has no donor")
                            require_close(
                                event.declared_closure_hpa,
                                0.0,
                                relative_tolerance,
                                1.0e-30,
                                f"{key}: exact correction closure",
                            )
                        elif event.correction_outcome == "roundoff_closed":
                            if event.declared_closure_hpa <= 0.0:
                                raise ValueError(f"{key}: roundoff closure is not positive")
                            if (
                                event.declared_closure_hpa
                                > event.ordinary_roundoff_tolerance_hpa
                            ):
                                raise ValueError(
                                    f"{key}: roundoff closure exceeds ordinary tolerance"
                                )
                        else:
                            if (
                                event.declared_closure_hpa
                                <= event.ordinary_roundoff_tolerance_hpa
                            ):
                                raise ValueError(
                                    f"{key}: microclosure does not exceed ordinary tolerance"
                                )
                            if event.event_mass_delta_kg > float(
                                microclosure_event_max_kg
                            ):
                                raise ValueError(f"{key}: microclosure exceeds event ceiling")
                            microclosure_by_tag[event.tag] = (
                                microclosure_by_tag.get(event.tag, 0.0)
                                + event.event_mass_delta_kg
                            )
                            microclosure_total_kg += event.event_mass_delta_kg

        if len(floor_events) != pre_floor_record.negative_cell_count:
            raise ValueError(
                f"{key}: floor event count {len(floor_events)} differs from "
                f"pre-floor ledger {pre_floor_record.negative_cell_count}"
            )
        if len(floor_events) != post_floor_record.corrected_cell_count:
            raise ValueError(
                f"{key}: floor event count {len(floor_events)} differs from "
                f"post-floor ledger {post_floor_record.corrected_cell_count}"
            )
        floor_delta = sum(event.event_mass_delta_kg for event in floor_events)
        require_close(
            floor_delta,
            post_floor_record.correction_mass_delta_kg,
            relative_tolerance,
            absolute_tolerance_kg,
            f"{key}: floor event mass reconciliation",
        )
        for event in floor_events:
            if event.q_before_kgkg >= 0.0:
                raise ValueError(f"{key}: floor event does not start negative")
            require_close(
                event.q_after_kgkg,
                1.0e-26,
                relative_tolerance,
                1.0e-35,
                f"{key}: floor replacement value",
            )

        key_microclosure_kg = sum(
            event.event_mass_delta_kg
            for event in qck_events
            if event.correction_outcome == "microclosure_closed"
        )
        if (
            microclosure_call_max_kg is not None
            and key_microclosure_kg > microclosure_call_max_kg
        ):
            raise ValueError(f"{key}: microclosure exceeds Qckxyz call ceiling")
        per_key[f"call_{key[0]}_{key[1]}"] = {
            "qck_event_count": len(qck_events),
            "qck_event_mass_delta_kg": qck_delta,
            "bottom_event_mass_delta_kg": bottom_delta,
            "qck_origin": summarize_origin(qck_events),
            "floor_event_count": len(floor_events),
            "floor_event_mass_delta_kg": floor_delta,
            "microclosure_mass_kg": key_microclosure_kg,
        }
    if microclosure_tag_max_kg is not None:
        for tag, closure_kg in microclosure_by_tag.items():
            if closure_kg > microclosure_tag_max_kg:
                raise ValueError(f"{tag}: cumulative microclosure exceeds tag ceiling")
    if (
        microclosure_all_tag_max_kg is not None
        and microclosure_total_kg > microclosure_all_tag_max_kg
    ):
        raise ValueError("cumulative microclosure exceeds all-tag ceiling")
    return {
        "status": "PASS",
        "event_count": len(events),
        "relative_tolerance": relative_tolerance,
        "absolute_tolerance_kg": absolute_tolerance_kg,
        "microclosure_total_kg": microclosure_total_kg,
        "microclosure_by_tag_kg": dict(sorted(microclosure_by_tag.items())),
        "per_call_tag": per_key,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("budget_ledger", type=Path)
    parser.add_argument("cell_event_ledger", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--relative-tolerance", type=float, default=1.0e-9)
    parser.add_argument("--absolute-tolerance-kg", type=float, default=1.0e-9)
    parser.add_argument("--microclosure-event-max-kg", type=float)
    parser.add_argument("--microclosure-call-max-kg", type=float)
    parser.add_argument("--microclosure-tag-max-kg", type=float)
    parser.add_argument("--microclosure-all-tag-max-kg", type=float)
    args = parser.parse_args()
    if args.relative_tolerance < 0.0 or args.absolute_tolerance_kg < 0.0:
        raise ValueError("tolerances must be non-negative")
    result = validate(
        read_ledger(args.budget_ledger),
        read_events(args.cell_event_ledger),
        args.relative_tolerance,
        args.absolute_tolerance_kg,
        args.microclosure_event_max_kg,
        args.microclosure_call_max_kg,
        args.microclosure_tag_max_kg,
        args.microclosure_all_tag_max_kg,
    )
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
