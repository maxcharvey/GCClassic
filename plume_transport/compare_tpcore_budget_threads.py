#!/usr/bin/env python3
"""Compare the frozen one-thread and eight-thread PLUME-012 ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_tpcore_budget import FLOAT_FIELDS, INTEGER_FIELDS, read_ledger, sha256


def relative_difference(left: float, right: float, floor: float) -> float:
    scale = max(abs(left), abs(right), floor)
    return 0.0 if scale == 0.0 else abs(left - right) / scale


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("one_thread_ledger", type=Path)
    parser.add_argument("eight_thread_ledger", type=Path)
    parser.add_argument("--relative-tolerance", type=float, required=True)
    parser.add_argument("--absolute-tolerance-kg", type=float, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.relative_tolerance < 0.0 or args.absolute_tolerance_kg < 0.0:
        raise ValueError("thread-comparison tolerances must be non-negative")

    one = read_ledger(args.one_thread_ledger.resolve())
    eight = read_ledger(args.eight_thread_ledger.resolve())
    one_index = {(record.tpcore_call_index, record.tag, record.boundary): record for record in one}
    eight_index = {(record.tpcore_call_index, record.tag, record.boundary): record for record in eight}
    if len(one_index) != len(one) or len(eight_index) != len(eight):
        raise ValueError("thread ledger contains duplicate causal-boundary records")
    if set(one_index) != set(eight_index):
        raise ValueError("thread ledgers do not cover the same causal boundaries")
    if {record.omp_thread_count for record in one} != {1}:
        raise ValueError("first ledger is not a one-thread control")
    if {record.omp_thread_count for record in eight} != {8}:
        raise ValueError("second ledger is not an eight-thread control")
    if {record.schema_version for record in one} != {
        record.schema_version for record in eight
    }:
        raise ValueError("thread ledgers use different ledger schemas")

    maximum_relative_error = 0.0
    maximum_label = ""
    compared = 0
    for key in sorted(one_index):
        left = one_index[key]
        right = eight_index[key]
        for field in INTEGER_FIELDS - {"omp_thread_count"}:
            if getattr(left, field) != getattr(right, field):
                raise ValueError(f"{key}: integer field {field} differs across thread controls")
        for field in FLOAT_FIELDS:
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
        "one_thread_ledger": {
            "path": str(args.one_thread_ledger.resolve()),
            "sha256": sha256(args.one_thread_ledger),
        },
        "eight_thread_ledger": {
            "path": str(args.eight_thread_ledger.resolve()),
            "sha256": sha256(args.eight_thread_ledger),
        },
        "relative_tolerance": args.relative_tolerance,
        "absolute_tolerance_kg": args.absolute_tolerance_kg,
        "compared_floating_values": compared,
        "maximum_relative_error": maximum_relative_error,
        "maximum_relative_error_field": maximum_label,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
