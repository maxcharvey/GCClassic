#!/usr/bin/env python3
"""Validate the bounded QCK closure summary from a production candidate."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


SUMMARY_RE = re.compile(
    r"^QCK_BOTTOM bounded-production run closure summary:\s*"
    r"closure_kg=\s*([+\-0-9.eEdD]+),\s*"
    r"run_max_kg=\s*([+\-0-9.eEdD]+)\s*$",
    re.MULTILINE,
)
END_BANNER = "E N D   O F   G E O S -- C H E M"


def _number(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def validate_log(
    text: str,
    *,
    expected_closure_kg: float,
    expected_run_cap_kg: float,
    absolute_tolerance_kg: float = 1.0e-12,
    relative_tolerance: float = 1.0e-10,
) -> dict[str, Any]:
    for name, value in {
        "expected closure": expected_closure_kg,
        "expected run cap": expected_run_cap_kg,
        "absolute tolerance": absolute_tolerance_kg,
        "relative tolerance": relative_tolerance,
    }.items():
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if expected_run_cap_kg <= 0.0:
        raise ValueError("expected run cap must be positive")

    if text.count(END_BANNER) != 1:
        raise ValueError("expected exactly one clean GEOS-Chem end banner")
    if "QCK_BOTTOM_SIZING_" in text:
        raise ValueError("sizing diagnostics appeared in a production log")

    matches = SUMMARY_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one bounded-production closure summary; "
            f"found {len(matches)}"
        )
    closure_kg, run_cap_kg = map(_number, matches[0])
    if not math.isfinite(closure_kg) or closure_kg < 0.0:
        raise ValueError("production closure must be finite and nonnegative")
    if not math.isfinite(run_cap_kg) or run_cap_kg <= 0.0:
        raise ValueError("reported run cap must be finite and positive")
    if closure_kg > run_cap_kg:
        raise ValueError("production closure exceeds the reported run ceiling")
    if not math.isclose(
        run_cap_kg,
        expected_run_cap_kg,
        abs_tol=absolute_tolerance_kg,
        rel_tol=relative_tolerance,
    ):
        raise ValueError("reported run ceiling differs from the reviewed policy")
    if not math.isclose(
        closure_kg,
        expected_closure_kg,
        abs_tol=absolute_tolerance_kg,
        rel_tol=relative_tolerance,
    ):
        raise ValueError(
            "production closure differs from the quarantined diagnostic "
            "corroboration value"
        )

    return {
        "status": "PASS",
        "production_closure_kg": closure_kg,
        "expected_diagnostic_closure_kg": expected_closure_kg,
        "closure_difference_kg": closure_kg - expected_closure_kg,
        "run_cap_kg": run_cap_kg,
        "absolute_tolerance_kg": absolute_tolerance_kg,
        "relative_tolerance": relative_tolerance,
        "sizing_diagnostics_absent": True,
        "clean_end_banner_count": 1,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected-closure-kg", type=float, required=True)
    parser.add_argument("--expected-run-cap-kg", type=float, required=True)
    parser.add_argument("--absolute-tolerance-kg", type=float, default=1.0e-12)
    parser.add_argument("--relative-tolerance", type=float, default=1.0e-10)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_log(
            args.log.read_text(encoding="utf-8"),
            expected_closure_kg=args.expected_closure_kg,
            expected_run_cap_kg=args.expected_run_cap_kg,
            absolute_tolerance_kg=args.absolute_tolerance_kg,
            relative_tolerance=args.relative_tolerance,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"QCK production closure validation failed: {exc}") from exc

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
