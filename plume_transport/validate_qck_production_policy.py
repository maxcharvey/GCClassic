#!/usr/bin/env python3
"""Validate a proposed QCK_BOTTOM production ceiling policy.

This is a fail-closed pre-submission check.  It compares deterministic sizing
measurements from a completed diagnostic with the proposed production event,
species-call, and run ceilings.  It does not read or modify model state.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def validate_policy(
    *,
    measured_event_kg: float,
    measured_call_kg: float,
    measured_run_kg: float,
    event_cap_kg: float,
    call_cap_kg: float,
    run_cap_kg: float,
) -> dict[str, Any]:
    values = {
        "measured_event_kg": measured_event_kg,
        "measured_call_kg": measured_call_kg,
        "measured_run_kg": measured_run_kg,
        "event_cap_kg": event_cap_kg,
        "call_cap_kg": call_cap_kg,
        "run_cap_kg": run_cap_kg,
    }
    for name, value in values.items():
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and positive")

    if measured_call_kg < measured_event_kg:
        raise ValueError("measured call maximum cannot be below the event maximum")
    if call_cap_kg < event_cap_kg:
        raise ValueError("call ceiling cannot be below the event ceiling")

    checks = (
        ("measured event", measured_event_kg, event_cap_kg, "event"),
        ("measured call", measured_call_kg, call_cap_kg, "call"),
        ("measured run", measured_run_kg, run_cap_kg, "run"),
    )
    for label, measured, cap, cap_name in checks:
        if measured > cap:
            raise ValueError(
                f"{label} {measured:.17g} kg exceeds {cap_name} ceiling "
                f"{cap:.17g} kg"
            )

    return {
        "status": "PASS",
        **values,
        "event_headroom_kg": event_cap_kg - measured_event_kg,
        "call_headroom_kg": call_cap_kg - measured_call_kg,
        "run_headroom_kg": run_cap_kg - measured_run_kg,
        "event_headroom_percent_of_cap": (
            100.0 * (event_cap_kg - measured_event_kg) / event_cap_kg
        ),
        "event_headroom_percent_over_measured": (
            100.0 * (event_cap_kg - measured_event_kg) / measured_event_kg
        ),
        "call_headroom_percent_of_cap": (
            100.0 * (call_cap_kg - measured_call_kg) / call_cap_kg
        ),
        "call_headroom_percent_over_measured": (
            100.0 * (call_cap_kg - measured_call_kg) / measured_call_kg
        ),
        "run_headroom_percent_of_cap": (
            100.0 * (run_cap_kg - measured_run_kg) / run_cap_kg
        ),
        "run_headroom_percent_over_measured": (
            100.0 * (run_cap_kg - measured_run_kg) / measured_run_kg
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measured-event-kg", type=float, required=True)
    parser.add_argument("--measured-call-kg", type=float, required=True)
    parser.add_argument("--measured-run-kg", type=float, required=True)
    parser.add_argument("--event-cap-kg", type=float, required=True)
    parser.add_argument("--call-cap-kg", type=float, required=True)
    parser.add_argument("--run-cap-kg", type=float, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_policy(
            measured_event_kg=args.measured_event_kg,
            measured_call_kg=args.measured_call_kg,
            measured_run_kg=args.measured_run_kg,
            event_cap_kg=args.event_cap_kg,
            call_cap_kg=args.call_cap_kg,
            run_cap_kg=args.run_cap_kg,
        )
    except ValueError as exc:
        raise SystemExit(f"QCK production policy validation failed: {exc}") from exc

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
