#!/usr/bin/env python3
"""Validate the final QCK corrected-trajectory sizing summary.

The summary is deliberately small and output-only.  Validation fails closed
when any record is missing, duplicated, non-finite, inconsistent with the
bounded-production closure, or above one of the declared ceilings.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any


SUMMARY_PREFIXES = {
    "schema": "QCK_BOTTOM_SIZING_SUMMARY ",
    "attempted": "QCK_BOTTOM_SIZING_MAX_ATTEMPTED ",
    "accepted": "QCK_BOTTOM_SIZING_MAX_ACCEPTED ",
    "call": "QCK_BOTTOM_SIZING_MAX_CALL ",
    "total": "QCK_BOTTOM_SIZING_TOTAL ",
}
KEY_VALUE_RE = re.compile(r"([a-z_]+)=\s*([^\s]+)")
BOUNDED_SUMMARY_RE = re.compile(
    r"QCK_BOTTOM bounded-production run closure summary:\s*"
    r"closure_kg=\s*([+\-0-9.eEdD]+),\s*run_max_kg=\s*([+\-0-9.eEdD]+)"
)
ABS_TOLERANCE_KG = 1.0e-12
REL_TOLERANCE = 1.0e-10


def _parse_fields(line: str) -> dict[str, str]:
    return dict(KEY_VALUE_RE.findall(line))


def _as_float(fields: dict[str, str], key: str, record: str) -> float:
    try:
        value = float(fields[key].replace("D", "E").replace("d", "e"))
    except (KeyError, ValueError) as error:
        raise ValueError(f"{record}: missing or invalid {key}") from error
    if not math.isfinite(value):
        raise ValueError(f"{record}: {key} must be finite")
    return value


def _as_int(fields: dict[str, str], key: str, record: str) -> int:
    try:
        return int(fields[key])
    except (KeyError, ValueError) as error:
        raise ValueError(f"{record}: missing or invalid {key}") from error


def _isclose(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=REL_TOLERANCE,
        abs_tol=ABS_TOLERANCE_KG,
    )


def _require_positive_identity(fields: dict[str, str], record: str) -> None:
    for key in ("species_index", "nymd", "nhms", "ordinal", "i", "j", "k"):
        value = _as_int(fields, key, record)
        minimum = 0 if key == "nhms" else 1
        if value < minimum:
            raise ValueError(f"{record}: positive event has invalid {key}={value}")
    if fields.get("species_name", "NONE") == "NONE":
        raise ValueError(f"{record}: positive event is missing species_name")


def parse_qck_sizing_summary(log_path: Path) -> dict[str, Any]:
    """Parse one complete final summary and its production-closure companion."""

    records: dict[str, dict[str, str]] = {}
    bounded: list[tuple[float, float]] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        for name, prefix in SUMMARY_PREFIXES.items():
            if line.startswith(prefix):
                if name in records:
                    raise ValueError(f"duplicate {name} sizing summary record")
                records[name] = _parse_fields(line)
        match = BOUNDED_SUMMARY_RE.search(line)
        if match:
            bounded.append(
                tuple(
                    float(item.replace("D", "E").replace("d", "e"))
                    for item in match.groups()
                )
            )

    missing = sorted(set(SUMMARY_PREFIXES) - set(records))
    if missing:
        raise ValueError(f"missing final QCK sizing summary records: {missing}")
    if len(bounded) != 1:
        raise ValueError(
            "expected exactly one bounded-production run closure summary, "
            f"found {len(bounded)}"
        )

    schema = records["schema"]
    if _as_int(schema, "schema_version", "schema") != 1:
        raise ValueError("unsupported QCK sizing schema version")
    if _as_int(schema, "enabled", "schema") != 1:
        raise ValueError("QCK sizing summary is not marked enabled")

    attempted = records["attempted"]
    accepted = records["accepted"]
    call = records["call"]
    total = records["total"]

    attempted_kg = _as_float(attempted, "event_kg", "attempted")
    accepted_kg = _as_float(accepted, "event_kg", "accepted")
    call_kg = _as_float(call, "closure_kg", "call")
    diagnostic_total_kg = _as_float(total, "closure_kg", "total")
    bounded_total_kg = _as_float(total, "bounded_closure_kg", "total")
    event_cap_kg = _as_float(total, "event_max_kg", "total")
    call_cap_kg = _as_float(total, "call_max_kg", "total")
    run_cap_kg = _as_float(total, "run_max_kg", "total")
    production_total_kg, production_run_cap_kg = bounded[0]

    named_values = {
        "attempted event": attempted_kg,
        "accepted event": accepted_kg,
        "species call": call_kg,
        "diagnostic cumulative closure": diagnostic_total_kg,
        "bounded cumulative closure": bounded_total_kg,
        "event ceiling": event_cap_kg,
        "call ceiling": call_cap_kg,
        "run ceiling": run_cap_kg,
    }
    for name, value in named_values.items():
        if value < 0.0:
            raise ValueError(f"{name} must be non-negative")
    for name, value in {
        "event ceiling": event_cap_kg,
        "call ceiling": call_cap_kg,
        "run ceiling": run_cap_kg,
    }.items():
        if value <= 0.0:
            raise ValueError(f"{name} must be positive")

    if attempted_kg > 0.0:
        _require_positive_identity(attempted, "attempted")
        if _as_int(attempted, "status", "attempted") not in (1, 4):
            raise ValueError("attempted maximum is not a closure-eligible outcome")
    if accepted_kg > 0.0:
        _require_positive_identity(accepted, "accepted")
    if call_kg > 0.0:
        for key in ("species_index", "nymd", "nhms", "ordinal"):
            value = _as_int(call, key, "call")
            minimum = 0 if key == "nhms" else 1
            if value < minimum:
                raise ValueError(f"call: positive maximum has invalid {key}={value}")
        if call.get("species_name", "NONE") == "NONE":
            raise ValueError("call: positive maximum is missing species_name")

    if accepted_kg > attempted_kg and not _isclose(accepted_kg, attempted_kg):
        raise ValueError("accepted-event maximum exceeds attempted-event maximum")
    if accepted_kg > event_cap_kg and not _isclose(accepted_kg, event_cap_kg):
        raise ValueError("accepted-event maximum exceeds event ceiling")
    if attempted_kg > event_cap_kg and not _isclose(attempted_kg, event_cap_kg):
        raise ValueError("attempted-event maximum exceeds event ceiling")
    if call_kg < accepted_kg and not _isclose(call_kg, accepted_kg):
        raise ValueError("species-call maximum is below accepted-event maximum")
    if call_kg > call_cap_kg and not _isclose(call_kg, call_cap_kg):
        raise ValueError("species-call maximum exceeds call ceiling")
    if diagnostic_total_kg < call_kg and not _isclose(diagnostic_total_kg, call_kg):
        raise ValueError("cumulative closure is below species-call maximum")
    if diagnostic_total_kg > run_cap_kg and not _isclose(
        diagnostic_total_kg, run_cap_kg
    ):
        raise ValueError("cumulative closure exceeds run ceiling")

    if not _isclose(diagnostic_total_kg, bounded_total_kg):
        raise ValueError(
            "diagnostic cumulative closure does not reconcile with bounded total"
        )
    if not _isclose(bounded_total_kg, production_total_kg):
        raise ValueError(
            "sizing bounded closure does not match production closure summary"
        )
    if not _isclose(run_cap_kg, production_run_cap_kg):
        raise ValueError("sizing run ceiling does not match production summary")

    return {
        "status": "PASS",
        "schema_version": 1,
        "max_attempted_event_kg": attempted_kg,
        "max_attempted": attempted,
        "max_accepted_event_kg": accepted_kg,
        "max_accepted": accepted,
        "max_species_call_kg": call_kg,
        "max_species_call": call,
        "diagnostic_cumulative_closure_kg": diagnostic_total_kg,
        "bounded_cumulative_closure_kg": bounded_total_kg,
        "event_max_kg": event_cap_kg,
        "call_max_kg": call_cap_kg,
        "run_max_kg": run_cap_kg,
        "reconciliation_absolute_tolerance_kg": ABS_TOLERANCE_KG,
        "reconciliation_relative_tolerance": REL_TOLERANCE,
    }


def validate_qck_sizing_summary(
    log_path: Path,
    expected_event_max_kg: float,
    expected_call_max_kg: float,
    expected_run_max_kg: float,
) -> dict[str, Any]:
    result = parse_qck_sizing_summary(log_path)
    for key, expected in {
        "event_max_kg": expected_event_max_kg,
        "call_max_kg": expected_call_max_kg,
        "run_max_kg": expected_run_max_kg,
    }.items():
        if not _isclose(float(result[key]), expected):
            raise ValueError(f"{key}={result[key]} does not match expected {expected}")
    return result


def compare_normalized_summaries(
    left: dict[str, Any], right: dict[str, Any]
) -> None:
    """Require thread/repeat equivalence after preregistered float normalization."""

    numeric_keys = (
        "max_attempted_event_kg",
        "max_accepted_event_kg",
        "max_species_call_kg",
        "diagnostic_cumulative_closure_kg",
        "bounded_cumulative_closure_kg",
        "event_max_kg",
        "call_max_kg",
        "run_max_kg",
    )
    for key in numeric_keys:
        if not _isclose(float(left[key]), float(right[key])):
            raise ValueError(f"normalized sizing summaries differ for {key}")
    for key in ("max_attempted", "max_accepted", "max_species_call"):
        if left[key] != right[key]:
            raise ValueError(f"normalized sizing summaries differ for {key}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--event-max-kg", type=float, required=True)
    parser.add_argument("--call-max-kg", type=float, required=True)
    parser.add_argument("--run-max-kg", type=float, required=True)
    parser.add_argument("--compare-log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = validate_qck_sizing_summary(
        args.log,
        args.event_max_kg,
        args.call_max_kg,
        args.run_max_kg,
    )
    if args.compare_log is not None:
        comparison = validate_qck_sizing_summary(
            args.compare_log,
            args.event_max_kg,
            args.call_max_kg,
            args.run_max_kg,
        )
        compare_normalized_summaries(result, comparison)
        result["normalized_comparison"] = "PASS"

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
