#!/usr/bin/env python3
"""Validate Qck-bottom donor diagnostics across the v1 and v2 schemas.

The v1 path preserves archival Phase-D0 interpretation.  The v2 path verifies
the staged conservative full-column correction and its explicit roundoff
closure declaration.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path

from validate_tpcore_cell_diagnostics import (
    CELL_SCHEMA_VERSION_V2,
    CELL_SCHEMA_VERSION_V3,
    G0_100_KG_PER_HPA_M2,
    CellEvent,
    close_enough,
    read_events,
    require_close,
)


DONOR_SCHEMA_VERSION_V1 = "plume-tpcore-donor-events-v1"
DONOR_SCHEMA_VERSION_V2 = "plume-tpcore-donor-events-v2"
DONOR_SCHEMA_VERSION_V3 = "plume-tpcore-donor-events-v3"
DONOR_SCHEMA_VERSION = DONOR_SCHEMA_VERSION_V3
DONOR_COLUMNS_V1 = (
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
    "i_tpcore",
    "j_tpcore",
    "k_tpcore",
    "k_model",
    "deficit_hpa",
    "immediate_available_above_hpa",
    "withdrawn_from_immediate_hpa",
    "column_total_above_hpa",
    "column_positive_above_hpa",
    "column_net_mass_hpa",
    "unfilled_by_immediate_hpa",
    "unfillable_column_mass_hpa",
    "area_m2",
    "event_mass_delta_kg",
)
DONOR_V2_EXTENSION_COLUMNS = (
    "correction_policy",
    "correction_outcome",
    "donor_count",
    "full_column_withdrawn_hpa",
    "declared_roundoff_closure_hpa",
    "correction_tolerance_hpa",
)
DONOR_COLUMNS_V2 = DONOR_COLUMNS_V1 + DONOR_V2_EXTENSION_COLUMNS
DONOR_V3_EXTENSION_COLUMNS = (
    "correction_policy",
    "correction_outcome",
    "donor_count",
    "full_column_withdrawn_hpa",
    "declared_closure_hpa",
    "ordinary_roundoff_tolerance_hpa",
    "microclosure_event_max_kg",
    "microclosure_call_max_kg",
)
DONOR_COLUMNS_V3 = DONOR_COLUMNS_V1 + DONOR_V3_EXTENSION_COLUMNS
DONOR_COLUMNS = DONOR_COLUMNS_V1 + DONOR_V2_EXTENSION_COLUMNS + DONOR_V3_EXTENSION_COLUMNS
DONOR_INTEGER_COLUMNS = {
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
DONOR_FLOAT_COLUMNS = set(DONOR_COLUMNS).difference(DONOR_INTEGER_COLUMNS).difference(
    {
        "schema_version",
        "run_id",
        "manifest_id",
        "tag",
        "correction_policy",
        "correction_outcome",
    }
)


@dataclass(frozen=True)
class DonorEvent:
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
    i_tpcore: int
    j_tpcore: int
    k_tpcore: int
    k_model: int
    deficit_hpa: float
    immediate_available_above_hpa: float
    withdrawn_from_immediate_hpa: float
    column_total_above_hpa: float
    column_positive_above_hpa: float
    column_net_mass_hpa: float
    unfilled_by_immediate_hpa: float
    unfillable_column_mass_hpa: float
    area_m2: float
    event_mass_delta_kg: float
    correction_policy: str = "native_immediate_donor_v1"
    correction_outcome: str = "legacy_native"
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
    """Normalize an archival native-immediate donor record to the v2 model."""

    withdrawn = float(parsed["withdrawn_from_immediate_hpa"])
    unfilled = float(parsed["unfilled_by_immediate_hpa"])
    return {
        "correction_policy": "native_immediate_donor_v1",
        "correction_outcome": "legacy_native",
        "donor_count": int(withdrawn > 0.0),
        "full_column_withdrawn_hpa": withdrawn,
        "declared_roundoff_closure_hpa": unfilled,
        "correction_tolerance_hpa": 0.0,
    }


def read_donor_events(path: Path) -> list[DonorEvent]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        if fieldnames == DONOR_COLUMNS_V1:
            columns = DONOR_COLUMNS_V1
            expected_schema = DONOR_SCHEMA_VERSION_V1
        elif fieldnames == DONOR_COLUMNS_V2:
            columns = DONOR_COLUMNS_V2
            expected_schema = DONOR_SCHEMA_VERSION_V2
        elif fieldnames == DONOR_COLUMNS_V3:
            columns = DONOR_COLUMNS_V3
            expected_schema = DONOR_SCHEMA_VERSION_V3
        else:
            raise ValueError(f"{path}: donor-event header does not match v1, v2, or v3")
        events: list[DonorEvent] = []
        for row_number, row in enumerate(reader, 2):
            if set(row) != set(columns):
                raise ValueError(f"{path}: row {row_number} has an invalid column set")
            parsed: dict[str, str | int | float] = {}
            for column in columns:
                value = row[column]
                if value is None or value == "":
                    raise ValueError(f"{path}: row {row_number} has empty {column}")
                if column in DONOR_INTEGER_COLUMNS:
                    try:
                        parsed[column] = int(value)
                    except ValueError as error:
                        raise ValueError(
                            f"{path}: row {row_number} has non-integer {column}"
                        ) from error
                elif column in DONOR_FLOAT_COLUMNS:
                    parsed[column] = finite_float(value, f"{path}: row {row_number} {column}")
                else:
                    parsed[column] = value
            if expected_schema == DONOR_SCHEMA_VERSION_V1:
                parsed.update(legacy_v1_extension(parsed))
            event = DonorEvent(**parsed)  # type: ignore[arg-type]
            if event.schema_version != expected_schema:
                raise ValueError(f"{path}: row {row_number} has unknown schema")
            if min(event.i_tpcore, event.j_tpcore, event.k_tpcore, event.k_model) < 1:
                raise ValueError(f"{path}: row {row_number} has a non-positive index")
            events.append(event)
    return events


def event_key(event: CellEvent | DonorEvent) -> tuple[int, str, int, int, int]:
    return (
        event.tpcore_call_index,
        event.tag,
        event.i_tpcore,
        event.j_tpcore,
        event.k_tpcore,
    )


def require_matching_provenance(donor: DonorEvent, cell: CellEvent) -> None:
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
        "i_tpcore",
        "j_tpcore",
        "k_tpcore",
        "k_model",
    ):
        if getattr(donor, field) != getattr(cell, field):
            raise ValueError(f"{event_key(donor)}: donor {field} differs from cell event")


def blank_summary() -> dict[str, float | int]:
    return {
        "event_count": 0,
        "immediate_shortfall_event_count": 0,
        "column_feasible_event_count": 0,
        "column_strictly_feasible_event_count": 0,
        "column_roundoff_limited_event_count": 0,
        "column_infeasible_event_count": 0,
        "total_deficit_hpa": 0.0,
        "total_immediate_shortfall_hpa": 0.0,
        "total_unfillable_column_mass_hpa": 0.0,
        "total_event_mass_delta_kg": 0.0,
    }


def column_feasibility_tolerance_hpa(
    event: DonorEvent, relative_tolerance: float, absolute_tolerance_hpa: float
) -> float:
    """Return the declared numerical tolerance for the column residual.

    The residual is a subtraction of two potentially tiny, nearly equal hPa
    inventories.  Its relative tolerance must therefore be scaled by the
    physical operands, not by the residual itself (which would make any
    nonzero residual fail a relative comparison).
    """

    scale = max(abs(event.column_total_above_hpa), abs(event.deficit_hpa))
    return max(absolute_tolerance_hpa, relative_tolerance * scale)


def add_to_summary(
    summary: dict[str, float | int],
    event: DonorEvent,
    relative_tolerance: float,
    absolute_tolerance_hpa: float,
) -> None:
    summary["event_count"] = int(summary["event_count"]) + 1
    summary["total_deficit_hpa"] = float(summary["total_deficit_hpa"]) + event.deficit_hpa
    summary["total_immediate_shortfall_hpa"] = float(
        summary["total_immediate_shortfall_hpa"]
    ) + max(event.unfilled_by_immediate_hpa, 0.0)
    summary["total_unfillable_column_mass_hpa"] = float(
        summary["total_unfillable_column_mass_hpa"]
    ) + max(event.unfillable_column_mass_hpa, 0.0)
    summary["total_event_mass_delta_kg"] = float(
        summary["total_event_mass_delta_kg"]
    ) + event.event_mass_delta_kg
    if event.unfilled_by_immediate_hpa > absolute_tolerance_hpa:
        summary["immediate_shortfall_event_count"] = int(
            summary["immediate_shortfall_event_count"]
        ) + 1
    if event.column_net_mass_hpa >= 0.0:
        summary["column_feasible_event_count"] = int(
            summary["column_feasible_event_count"]
        ) + 1
        summary["column_strictly_feasible_event_count"] = int(
            summary["column_strictly_feasible_event_count"]
        ) + 1
    elif event.column_net_mass_hpa >= -column_feasibility_tolerance_hpa(
        event, relative_tolerance, absolute_tolerance_hpa
    ):
        summary["column_feasible_event_count"] = int(
            summary["column_feasible_event_count"]
        ) + 1
        summary["column_roundoff_limited_event_count"] = int(
            summary["column_roundoff_limited_event_count"]
        ) + 1
    else:
        summary["column_infeasible_event_count"] = int(
            summary["column_infeasible_event_count"]
        ) + 1


def validate(
    cell_events: list[CellEvent],
    donor_events: list[DonorEvent],
    relative_tolerance: float,
    absolute_tolerance_hpa: float,
    absolute_tolerance_kg: float,
    microclosure_event_max_kg: float | None = None,
    microclosure_call_max_kg: float | None = None,
    microclosure_tag_max_kg: float | None = None,
    microclosure_all_tag_max_kg: float | None = None,
) -> dict[str, object]:
    bottom_events = [event for event in cell_events if event.event_type == "QCK_BOTTOM"]
    cell_index = {event_key(event): event for event in bottom_events}
    donor_index = {event_key(event): event for event in donor_events}
    if len(cell_index) != len(bottom_events):
        raise ValueError("cell-event ledger has duplicate QCK_BOTTOM coordinates")
    if len(donor_index) != len(donor_events):
        raise ValueError("donor-event ledger has duplicate coordinates")
    if set(cell_index) != set(donor_index):
        missing = sorted(set(cell_index).difference(donor_index))
        unexpected = sorted(set(donor_index).difference(cell_index))
        raise ValueError(
            "donor-event coverage differs from QCK_BOTTOM events: "
            f"missing={missing}, unexpected={unexpected}"
        )

    overall = blank_summary()
    per_tag: dict[str, dict[str, float | int]] = {}
    microclosure_by_call_tag: dict[tuple[int, str], float] = {}
    microclosure_by_tag: dict[str, float] = {}
    microclosure_total_kg = 0.0
    for key in sorted(cell_index):
        cell = cell_index[key]
        donor = donor_index[key]
        require_matching_provenance(donor, cell)
        require_close(
            donor.deficit_hpa,
            cell.deficit_hpa,
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: deficit",
        )
        require_close(
            donor.immediate_available_above_hpa,
            cell.available_above_hpa,
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: immediate donor",
        )
        require_close(
            donor.withdrawn_from_immediate_hpa,
            cell.withdrawn_from_above_hpa,
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: immediate withdrawal",
        )
        require_close(
            donor.area_m2,
            cell.area_m2,
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: area",
        )
        require_close(
            donor.event_mass_delta_kg,
            cell.event_mass_delta_kg,
            relative_tolerance,
            absolute_tolerance_kg,
            f"{key}: event mass delta",
        )
        require_close(
            donor.deficit_hpa,
            -cell.dq_at_correction_hpa,
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: deficit from correction state",
        )
        require_close(
            donor.withdrawn_from_immediate_hpa,
            min(donor.deficit_hpa, donor.immediate_available_above_hpa),
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: native immediate withdrawal",
        )
        require_close(
            donor.unfilled_by_immediate_hpa,
            donor.deficit_hpa - donor.withdrawn_from_immediate_hpa,
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: immediate shortfall",
        )
        require_close(
            donor.column_net_mass_hpa,
            donor.column_total_above_hpa - donor.deficit_hpa,
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: column net mass",
        )
        require_close(
            donor.unfillable_column_mass_hpa,
            max(-donor.column_net_mass_hpa, 0.0),
            relative_tolerance,
            absolute_tolerance_hpa,
            f"{key}: unfillable column mass",
        )
        # Positivity is a sign invariant, not a closeness comparison.  Real
        # QCK_BOTTOM events can be positive while smaller than the absolute
        # reconciliation tolerance (ordinary-roundoff closures do exactly
        # this), so do not classify them as zero here.
        if donor.deficit_hpa <= 0.0:
            raise ValueError(f"{key}: bottom event has a non-positive deficit")
        if donor.column_positive_above_hpa < -absolute_tolerance_hpa:
            raise ValueError(f"{key}: positive donor inventory is negative")
        if donor.unfilled_by_immediate_hpa < -absolute_tolerance_hpa:
            raise ValueError(f"{key}: immediate shortfall is negative")
        if donor.unfillable_column_mass_hpa < -absolute_tolerance_hpa:
            raise ValueError(f"{key}: unfillable column mass is negative")
        if donor.column_total_above_hpa > donor.column_positive_above_hpa and not close_enough(
            donor.column_total_above_hpa,
            donor.column_positive_above_hpa,
            relative_tolerance,
            absolute_tolerance_hpa,
        ):
            raise ValueError(f"{key}: column total exceeds positive donor inventory")
        schema_pairs = {
            DONOR_SCHEMA_VERSION_V1: "plume-tpcore-cell-events-v1",
            DONOR_SCHEMA_VERSION_V2: CELL_SCHEMA_VERSION_V2,
            DONOR_SCHEMA_VERSION_V3: CELL_SCHEMA_VERSION_V3,
        }
        if schema_pairs[donor.schema_version] != cell.schema_version:
            raise ValueError(f"{key}: donor and cell schema generations differ")
        if donor.schema_version == DONOR_SCHEMA_VERSION_V2:
            if donor.correction_policy != "full_column_nearest_above_v1":
                raise ValueError(f"{key}: v2 donor event has unknown policy")
            if donor.correction_outcome not in {"exact", "roundoff_closed"}:
                raise ValueError(f"{key}: v2 donor event has unknown outcome")
            if (
                donor.correction_policy != cell.correction_policy
                or donor.correction_outcome != cell.correction_outcome
            ):
                raise ValueError(f"{key}: donor and cell correction metadata differ")
            if donor.donor_count != cell.donor_count or donor.donor_count < 0:
                raise ValueError(f"{key}: v2 donor count is invalid")
            require_close(
                donor.full_column_withdrawn_hpa,
                cell.full_column_withdrawn_hpa,
                relative_tolerance,
                absolute_tolerance_hpa,
                f"{key}: full-column withdrawal",
            )
            require_close(
                donor.declared_roundoff_closure_hpa,
                cell.declared_roundoff_closure_hpa,
                relative_tolerance,
                absolute_tolerance_hpa,
                f"{key}: roundoff closure",
            )
            require_close(
                donor.correction_tolerance_hpa,
                cell.correction_tolerance_hpa,
                relative_tolerance,
                absolute_tolerance_hpa,
                f"{key}: correction tolerance",
            )
            require_close(
                donor.full_column_withdrawn_hpa,
                donor.deficit_hpa - donor.declared_roundoff_closure_hpa,
                relative_tolerance,
                absolute_tolerance_hpa,
                f"{key}: conservative full-column withdrawal",
            )
            if donor.full_column_withdrawn_hpa > (
                donor.column_positive_above_hpa + donor.correction_tolerance_hpa
            ):
                raise ValueError(f"{key}: full-column withdrawal exceeds donor inventory")
            if donor.correction_tolerance_hpa < 0.0:
                raise ValueError(f"{key}: v2 correction tolerance is negative")
            if donor.correction_outcome == "exact":
                if donor.donor_count < 1:
                    raise ValueError(f"{key}: exact correction has no donor")
                require_close(
                    donor.declared_roundoff_closure_hpa,
                    0.0,
                    relative_tolerance,
                    absolute_tolerance_hpa,
                    f"{key}: exact closure",
                )
                require_close(
                    donor.event_mass_delta_kg,
                    0.0,
                    relative_tolerance,
                    absolute_tolerance_kg,
                    f"{key}: exact event mass delta",
                )
            else:
                if donor.declared_roundoff_closure_hpa <= 0.0:
                    raise ValueError(f"{key}: roundoff closure is not positive")
                if (
                    donor.declared_roundoff_closure_hpa
                    > donor.correction_tolerance_hpa
                ):
                    raise ValueError(f"{key}: roundoff closure exceeds tolerance")
        elif donor.schema_version == DONOR_SCHEMA_VERSION_V3:
            limits = (
                microclosure_event_max_kg,
                microclosure_call_max_kg,
                microclosure_tag_max_kg,
                microclosure_all_tag_max_kg,
            )
            if any(limit is None or limit <= 0.0 for limit in limits):
                raise ValueError(
                    f"{key}: v3 validation requires four positive microclosure ceilings"
                )
            if donor.correction_policy != "full_column_nearest_above_microclosure_v2":
                raise ValueError(f"{key}: v3 donor event has unknown policy")
            if donor.correction_outcome not in {
                "exact",
                "roundoff_closed",
                "microclosure_closed",
            }:
                raise ValueError(f"{key}: v3 donor event has unknown outcome")
            if (
                donor.correction_policy != cell.correction_policy
                or donor.correction_outcome != cell.correction_outcome
            ):
                raise ValueError(f"{key}: donor and cell correction metadata differ")
            if donor.donor_count != cell.donor_count or donor.donor_count < 0:
                raise ValueError(f"{key}: v3 donor count is invalid")
            for field in (
                "full_column_withdrawn_hpa",
                "declared_closure_hpa",
                "ordinary_roundoff_tolerance_hpa",
                "microclosure_event_max_kg",
                "microclosure_call_max_kg",
            ):
                require_close(
                    getattr(donor, field),
                    getattr(cell, field),
                    relative_tolerance,
                    absolute_tolerance_hpa,
                    f"{key}: {field}",
                )
            require_close(
                donor.microclosure_event_max_kg,
                float(microclosure_event_max_kg),
                0.0,
                0.0,
                f"{key}: manifested event ceiling",
            )
            require_close(
                donor.microclosure_call_max_kg,
                float(microclosure_call_max_kg),
                0.0,
                0.0,
                f"{key}: manifested call ceiling",
            )
            require_close(
                donor.full_column_withdrawn_hpa,
                donor.deficit_hpa - donor.declared_closure_hpa,
                relative_tolerance,
                absolute_tolerance_hpa,
                f"{key}: v3 full-column withdrawal",
            )
            expected_mass_kg = (
                donor.declared_closure_hpa
                * donor.area_m2
                * G0_100_KG_PER_HPA_M2
            )
            require_close(
                donor.event_mass_delta_kg,
                expected_mass_kg,
                relative_tolerance,
                absolute_tolerance_kg,
                f"{key}: declared pressure-to-mass closure",
            )
            if donor.correction_outcome == "exact":
                if donor.donor_count < 1:
                    raise ValueError(f"{key}: exact correction has no donor")
                require_close(
                    donor.declared_closure_hpa,
                    0.0,
                    relative_tolerance,
                    absolute_tolerance_hpa,
                    f"{key}: exact closure",
                )
            elif donor.correction_outcome == "roundoff_closed":
                if donor.declared_closure_hpa <= 0.0:
                    raise ValueError(f"{key}: roundoff closure is not positive")
                if donor.declared_closure_hpa > donor.ordinary_roundoff_tolerance_hpa:
                    raise ValueError(f"{key}: roundoff closure exceeds ordinary tolerance")
            else:
                if donor.declared_closure_hpa <= donor.ordinary_roundoff_tolerance_hpa:
                    raise ValueError(
                        f"{key}: microclosure does not exceed ordinary tolerance"
                    )
                if donor.event_mass_delta_kg > float(microclosure_event_max_kg):
                    raise ValueError(f"{key}: microclosure exceeds event ceiling")
                call_tag = (donor.tpcore_call_index, donor.tag)
                microclosure_by_call_tag[call_tag] = (
                    microclosure_by_call_tag.get(call_tag, 0.0)
                    + donor.event_mass_delta_kg
                )
                microclosure_by_tag[donor.tag] = (
                    microclosure_by_tag.get(donor.tag, 0.0)
                    + donor.event_mass_delta_kg
                )
                microclosure_total_kg += donor.event_mass_delta_kg

        add_to_summary(overall, donor, relative_tolerance, absolute_tolerance_hpa)
        add_to_summary(
            per_tag.setdefault(donor.tag, blank_summary()),
            donor,
            relative_tolerance,
            absolute_tolerance_hpa,
        )

    if microclosure_call_max_kg is not None:
        for call_tag, closure_kg in microclosure_by_call_tag.items():
            if closure_kg > microclosure_call_max_kg:
                raise ValueError(f"{call_tag}: microclosure exceeds Qckxyz call ceiling")
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
        "schema_versions": sorted({event.schema_version for event in donor_events}),
        "covered_bottom_event_count": len(donor_events),
        "relative_tolerance": relative_tolerance,
        "absolute_tolerance_hpa": absolute_tolerance_hpa,
        "absolute_tolerance_kg": absolute_tolerance_kg,
        "microclosure_total_kg": microclosure_total_kg,
        "microclosure_by_tag_kg": dict(sorted(microclosure_by_tag.items())),
        "summary": overall,
        "per_tag": {tag: per_tag[tag] for tag in sorted(per_tag)},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cell_event_ledger", type=Path)
    parser.add_argument("donor_event_ledger", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--relative-tolerance", type=float, default=1.0e-9)
    parser.add_argument("--absolute-tolerance-hpa", type=float, default=1.0e-30)
    parser.add_argument("--absolute-tolerance-kg", type=float, default=1.0e-9)
    parser.add_argument("--microclosure-event-max-kg", type=float)
    parser.add_argument("--microclosure-call-max-kg", type=float)
    parser.add_argument("--microclosure-tag-max-kg", type=float)
    parser.add_argument("--microclosure-all-tag-max-kg", type=float)
    args = parser.parse_args()
    if (
        args.relative_tolerance < 0.0
        or args.absolute_tolerance_hpa < 0.0
        or args.absolute_tolerance_kg < 0.0
    ):
        raise ValueError("tolerances must be non-negative")
    result = validate(
        read_events(args.cell_event_ledger),
        read_donor_events(args.donor_event_ledger),
        args.relative_tolerance,
        args.absolute_tolerance_hpa,
        args.absolute_tolerance_kg,
        args.microclosure_event_max_kg,
        args.microclosure_call_max_kg,
        args.microclosure_tag_max_kg,
        args.microclosure_all_tag_max_kg,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
