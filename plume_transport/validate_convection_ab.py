#!/usr/bin/env python3
"""Validate fresh survey-free bounded-QCK v2 Stage-1 convection A/B controls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import validate_pbl_ab as common


def require_case_config(off: Path, on: Path) -> None:
    off_config = common.load_config(off)
    on_config = common.load_config(on)
    for run, config in ((off, off_config), (on, on_config)):
        if config["operations"]["pbl_mixing"] != {
            "activate": True,
            "use_non_local_pbl": False,
        }:
            raise ValueError(f"{run}: full PBL mixing is not held on")
    if off_config["operations"]["convection"] != {"activate": False}:
        raise ValueError(f"{off}: unexpected convection-off configuration")
    if on_config["operations"]["convection"] != {"activate": True}:
        raise ValueError(f"{on}: unexpected convection-on configuration")
    on_config["operations"]["convection"]["activate"] = False
    if on_config != off_config:
        raise ValueError("convection A/B configurations differ beyond convection.activate")


def require_inactive_post_convection(run: Path) -> None:
    for time in common.TIMES:
        for tag in common.TAGS:
            reference = common.plume_mass(run, "C4_POST_CONVECTION", time, tag)
            for label in ("C5_POST_CHEMISTRY", "C6_POST_WETDEP"):
                if not np.array_equal(reference, common.plume_mass(run, label, time, tag)):
                    raise ValueError(f"inactive operator changed {tag}: {run.name} {label} {time}")


def require_expected_active_tags(active_tags: set[str]) -> None:
    expected = set(common.TAGS)
    if active_tags != expected:
        raise ValueError(
            "unexpected convection-sensitive tag set: "
            f"expected {sorted(expected)}, got {sorted(active_tags)}"
        )


def validate(off_one: Path, off_eight: Path, on_one: Path, on_eight: Path) -> dict:
    runs = (off_one, off_eight, on_one, on_eight)
    require_case_config(off_one, on_one)
    require_case_config(off_eight, on_eight)
    for run in runs:
        require_inactive_post_convection(run)

    tolerance_kg = 1.0e-9
    activity_threshold_kg = 1.0e-12
    effects: dict[str, dict[str, dict[str, float | int]]] = {}
    active_tags: set[str] = set()
    for time in common.TIMES:
        by_tag: dict[str, dict[str, float | int]] = {}
        for tag in common.TAGS:
            off_increment = (
                common.plume_mass(off_one, "C4_POST_CONVECTION", time, tag)
                - common.plume_mass(off_one, "C3_POST_MIXING", time, tag)
            )
            if np.any(off_increment != 0.0):
                raise ValueError(f"convection-off boundary is nonzero: {time} {tag}")
            on_increment = (
                common.plume_mass(on_one, "C4_POST_CONVECTION", time, tag)
                - common.plume_mass(on_one, "C3_POST_MIXING", time, tag)
            )
            column_residual = on_increment.sum(axis=0, dtype=np.float64)
            global_residual = float(on_increment.sum(dtype=np.float64))
            column_l1 = float(np.abs(column_residual).sum(dtype=np.float64))
            redistribution_l1 = float(np.abs(on_increment).sum(dtype=np.float64))
            if abs(global_residual) > tolerance_kg:
                raise ValueError(f"convection global conservation failure: {time} {tag}")
            if column_l1 > tolerance_kg:
                raise ValueError(f"convection column conservation failure: {time} {tag}")
            if redistribution_l1 > activity_threshold_kg:
                active_tags.add(tag)
            by_tag[tag] = {
                "convection_redistribution_l1_kg": redistribution_l1,
                "convection_global_mass_residual_kg": global_residual,
                "convection_column_residual_l1_kg": column_l1,
                "convection_column_residual_max_abs_kg": float(
                    np.max(np.abs(column_residual))
                ),
                "changed_grid_cells": int(np.count_nonzero(on_increment)),
            }
        effects[time] = by_tag

    require_expected_active_tags(active_tags)
    qck = {
        "convection_off_1thread": common.read_qck_v2_summary(off_one),
        "convection_off_8thread": common.read_qck_v2_summary(off_eight),
        "convection_on_1thread": common.read_qck_v2_summary(on_one),
        "convection_on_8thread": common.read_qck_v2_summary(on_eight),
    }
    qck_off = qck["convection_off_1thread"]
    qck_on = qck["convection_on_1thread"]
    qck_off_mass = float(qck_off["microclosure_total_kg"])
    qck_on_mass = float(qck_on["microclosure_total_kg"])

    return {
        "status": "diagnostic_pass_bounded_qck_v2",
        "scientific_acceptance": False,
        "active_convection_response": True,
        "active_tags": sorted(active_tags),
        "qck_policy": "conservative full-column QCK_BOTTOM with bounded v2 microclosure",
        "operator_under_test": "native convection with full PBL mixing held on",
        "input_identity": common.require_input_identity(runs),
        "thread_determinism": {
            "convection_off": common.require_thread_identity(off_one, off_eight),
            "convection_on": common.require_thread_identity(on_one, on_eight),
        },
        "acceptance": {
            "convection_mass_conservation_tolerance_kg": tolerance_kg,
            "active_response_threshold_l1_kg": activity_threshold_kg,
            "convection_off_boundary_exactly_zero": True,
            "expected_convection_sensitive_tags": sorted(common.TAGS),
        },
        "convection_effect": effects,
        "qck_microclosure": {
            "convection_off_kg": qck_off_mass,
            "convection_on_kg": qck_on_mass,
            "convection_on_minus_off_kg": qck_on_mass - qck_off_mass,
            "convection_off_event_count": int(qck_off["event_count"]),
            "convection_on_event_count": int(qck_on["event_count"]),
            "all_controls": qck,
        },
        "guardrail": (
            "Convection behavior is diagnostic only; production and scientific "
            "interpretation remain blocked; bounded v2 is a diagnostic policy, "
            "not scientific acceptance."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("off_one", type=Path)
    parser.add_argument("off_eight", type=Path)
    parser.add_argument("on_one", type=Path)
    parser.add_argument("on_eight", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.off_one, args.off_eight, args.on_one, args.on_eight)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
