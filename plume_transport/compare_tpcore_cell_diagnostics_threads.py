#!/usr/bin/env python3
"""Compare one- and eight-thread per-cell TPCORE diagnostic ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_tpcore_budget import sha256
from validate_tpcore_cell_diagnostics import FLOAT_COLUMNS, INTEGER_COLUMNS, read_events


def relative_difference(left: float, right: float, floor: float) -> float:
    scale = max(abs(left), abs(right), floor)
    return 0.0 if scale == 0.0 else abs(left - right) / scale


def event_key(event: object) -> tuple[int, str, str, int, int, int]:
    return (
        event.tpcore_call_index,
        event.tag,
        event.event_type,
        event.i_tpcore,
        event.j_tpcore,
        event.k_tpcore,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("one_thread_events", type=Path)
    parser.add_argument("eight_thread_events", type=Path)
    parser.add_argument("--relative-tolerance", type=float, required=True)
    parser.add_argument("--absolute-tolerance-kg", type=float, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.relative_tolerance < 0.0 or args.absolute_tolerance_kg < 0.0:
        raise ValueError("thread-comparison tolerances must be non-negative")

    one = read_events(args.one_thread_events.resolve())
    eight = read_events(args.eight_thread_events.resolve())
    one_index = {event_key(event): event for event in one}
    eight_index = {event_key(event): event for event in eight}
    if len(one_index) != len(one) or len(eight_index) != len(eight):
        raise ValueError("cell-event ledger contains duplicate event coordinates")
    if set(one_index) != set(eight_index):
        raise ValueError("thread event ledgers do not cover the same event coordinates")
    if {event.omp_thread_count for event in one} != {1}:
        raise ValueError("first event ledger is not a one-thread control")
    if {event.omp_thread_count for event in eight} != {8}:
        raise ValueError("second event ledger is not an eight-thread control")

    maximum_relative_error = 0.0
    maximum_label = ""
    compared = 0
    for key in sorted(one_index):
        left = one_index[key]
        right = eight_index[key]
        for field in (
            "schema_version",
            "correction_policy",
            "correction_outcome",
        ):
            if getattr(left, field) != getattr(right, field):
                raise ValueError(f"{key}: {field} differs across thread controls")
        for field in INTEGER_COLUMNS - {"omp_thread_count"}:
            if getattr(left, field) != getattr(right, field):
                raise ValueError(f"{key}: integer field {field} differs across thread controls")
        for field in FLOAT_COLUMNS:
            left_value = getattr(left, field)
            right_value = getattr(right, field)
            difference = abs(left_value - right_value)
            relative = relative_difference(
                left_value, right_value, args.absolute_tolerance_kg
            )
            if difference > args.absolute_tolerance_kg and relative > args.relative_tolerance:
                raise ValueError(
                    f"{key}: {field} differs across thread controls "
                    f"(relative_error={relative:.17e})"
                )
            if relative > maximum_relative_error:
                maximum_relative_error = relative
                maximum_label = f"{key}:{field}"
            compared += 1

    report = {
        "status": "pass",
        "one_thread_events": {
            "path": str(args.one_thread_events.resolve()),
            "sha256": sha256(args.one_thread_events),
        },
        "eight_thread_events": {
            "path": str(args.eight_thread_events.resolve()),
            "sha256": sha256(args.eight_thread_events),
        },
        "relative_tolerance": args.relative_tolerance,
        "absolute_tolerance_kg": args.absolute_tolerance_kg,
        "compared_floating_values": compared,
        "maximum_relative_error": maximum_relative_error,
        "maximum_relative_error_field": maximum_label,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
