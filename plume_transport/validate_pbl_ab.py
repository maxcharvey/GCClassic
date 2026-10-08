#!/usr/bin/env python3
"""Validate Stage-1 full-PBL-mixing A/B controls under bounded QCK v2."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import yaml


TAGS = ("PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE")
TIMES = ("000000", "001000")
LABELS = (
    "C0_PRE_TPCORE",
    "C1_POST_TPCORE",
    "C2_FLUX_READY",
    "C3_POST_MIXING",
    "C4_POST_CONVECTION",
    "C5_POST_CHEMISTRY",
    "C6_POST_WETDEP",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checkpoint(run: Path, label: str, time: str) -> Path:
    path = (
        run
        / "OutputDir/PlumeCheckpoints"
        / f"GEOSChem.PlumeCheckpoint.{label}.20190101_{time}z.nc4"
    )
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def plume_mass(run: Path, label: str, time: str, tag: str) -> np.ndarray:
    with h5py.File(checkpoint(run, label, time), "r") as dataset:
        values = np.asarray(dataset[f"PlumeMass_{tag}"][:], dtype=np.float64)
    if values.shape != (72, 46, 72) or np.any(~np.isfinite(values)):
        raise ValueError(f"invalid checkpoint plume mass: {run.name} {label} {time} {tag}")
    return values


def load_config(run: Path) -> dict:
    return yaml.safe_load((run / "geoschem_config.yml").read_text(encoding="utf-8"))


def require_case_config(off: Path, on: Path) -> None:
    off_config = load_config(off)
    on_config = load_config(on)
    off_pbl = off_config["operations"]["pbl_mixing"]
    on_pbl = on_config["operations"]["pbl_mixing"]
    if off_pbl != {"activate": False, "use_non_local_pbl": False}:
        raise ValueError(f"{off}: unexpected PBL-off configuration")
    if on_pbl != {"activate": True, "use_non_local_pbl": False}:
        raise ValueError(f"{on}: unexpected PBL-on configuration")
    on_config["operations"]["pbl_mixing"]["activate"] = False
    if on_config != off_config:
        raise ValueError("PBL A/B configurations differ beyond pbl_mixing.activate")


def require_input_identity(runs: tuple[Path, ...]) -> dict[str, str]:
    paths = {
        "executable": Path("gcclassic"),
        "source": Path("PlumeSource.20190101_0000z.nc"),
        "initial_restart": Path("Restarts/GEOSChem.Restart.20190101_0000z.nc4"),
    }
    result: dict[str, str] = {}
    for role, relative in paths.items():
        hashes = {sha256(run / relative) for run in runs}
        if len(hashes) != 1:
            raise ValueError(f"{role} is not byte-identical across controls")
        result[f"{role}_sha256"] = hashes.pop()
    return result


def require_thread_identity(one: Path, eight: Path) -> dict[str, object]:
    checked = 0
    for time in TIMES:
        for label in LABELS:
            for tag in TAGS:
                left = plume_mass(one, label, time, tag)
                right = plume_mass(eight, label, time, tag)
                if not np.array_equal(left, right):
                    maximum = float(np.max(np.abs(left - right)))
                    raise ValueError(
                        f"thread mismatch: {one.name} {label} {time} {tag} ({maximum})"
                    )
                checked += 1
    return {"status": "pass", "arrays_checked": checked, "exactly_equal": True}


def require_inactive_boundaries(run: Path) -> None:
    for time in TIMES:
        for tag in TAGS:
            reference = plume_mass(run, "C3_POST_MIXING", time, tag)
            for label in ("C4_POST_CONVECTION", "C5_POST_CHEMISTRY", "C6_POST_WETDEP"):
                if not np.array_equal(reference, plume_mass(run, label, time, tag)):
                    raise ValueError(f"inactive operator changed {tag}: {run.name} {label} {time}")


def read_qck_v2_summary(run: Path) -> dict:
    output = run / "OutputDir"
    forbidden = (
        output / "qck_bottom_survey_v1.csv",
        output / "qck_bottom_survey_validation.json",
    )
    present = [str(path) for path in forbidden if path.exists()]
    if present:
        raise ValueError(f"native QCK survey artifacts are forbidden in v2 controls: {present}")

    required = {
        "budget": ("tpcore_budget_validation.json", "pass"),
        "cell": ("tpcore_cell_diagnostic_validation.json", "PASS"),
        "donor": ("tpcore_donor_diagnostic_validation.json", "PASS"),
    }
    reports: dict[str, dict] = {}
    for role, (name, expected_status) in required.items():
        path = output / name
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("status") != expected_status:
            raise ValueError(f"QCK v2 {role} validation did not pass: {run}")
        reports[role] = result

    cell = reports["cell"]
    donor = reports["donor"]
    if float(cell["microclosure_total_kg"]) != float(donor["microclosure_total_kg"]):
        raise ValueError(f"cell/donor microclosure totals differ: {run}")
    if cell["microclosure_by_tag_kg"] != donor["microclosure_by_tag_kg"]:
        raise ValueError(f"cell/donor per-tag microclosure totals differ: {run}")
    return {
        "status": "PASS",
        "event_count": int(cell["event_count"]),
        "microclosure_total_kg": float(cell["microclosure_total_kg"]),
        "microclosure_by_tag_kg": cell["microclosure_by_tag_kg"],
    }


def validate(off_one: Path, off_eight: Path, on_one: Path, on_eight: Path) -> dict:
    runs = (off_one, off_eight, on_one, on_eight)
    for run in runs:
        require_inactive_boundaries(run)
    require_case_config(off_one, on_one)
    require_case_config(off_eight, on_eight)

    conservation_tolerance_kg = 1.0e-9
    redistribution: dict[str, dict[str, dict[str, float | int]]] = {}
    changed_tags: set[str] = set()
    for time in TIMES:
        by_tag: dict[str, dict[str, float | int]] = {}
        for tag in TAGS:
            off_increment = (
                plume_mass(off_one, "C3_POST_MIXING", time, tag)
                - plume_mass(off_one, "C2_FLUX_READY", time, tag)
            )
            on_increment = (
                plume_mass(on_one, "C3_POST_MIXING", time, tag)
                - plume_mass(on_one, "C2_FLUX_READY", time, tag)
            )
            mixing_effect = on_increment - off_increment
            column_residual = mixing_effect.sum(axis=0, dtype=np.float64)
            global_residual = float(mixing_effect.sum(dtype=np.float64))
            column_l1 = float(np.abs(column_residual).sum(dtype=np.float64))
            redistribution_l1 = float(np.abs(mixing_effect).sum(dtype=np.float64))
            changed_cells = int(np.count_nonzero(mixing_effect))
            if abs(global_residual) > conservation_tolerance_kg:
                raise ValueError(f"PBL global conservation failure: {time} {tag}")
            if column_l1 > conservation_tolerance_kg:
                raise ValueError(f"PBL column conservation failure: {time} {tag}")
            if redistribution_l1 > 1.0e-12:
                changed_tags.add(tag)
            by_tag[tag] = {
                "off_source_increment_kg": float(off_increment.sum(dtype=np.float64)),
                "on_source_plus_pbl_increment_kg": float(on_increment.sum(dtype=np.float64)),
                "pbl_redistribution_l1_kg": redistribution_l1,
                "pbl_global_mass_residual_kg": global_residual,
                "pbl_column_residual_l1_kg": column_l1,
                "pbl_column_residual_max_abs_kg": float(np.max(np.abs(column_residual))),
                "changed_grid_cells": changed_cells,
            }
        redistribution[time] = by_tag

    expected_changed = {"PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_PROFILE"}
    if changed_tags != expected_changed:
        raise ValueError(f"unexpected PBL-sensitive tag set: {sorted(changed_tags)}")

    qck_off = read_qck_v2_summary(off_one)
    qck_on = read_qck_v2_summary(on_one)
    qck_off_mass = float(qck_off["microclosure_total_kg"])
    qck_on_mass = float(qck_on["microclosure_total_kg"])
    endpoints: dict[str, dict[str, float]] = {}
    for mode, run in (("pbl_off", off_one), ("pbl_on", on_one)):
        endpoints[mode] = {
            tag: float(plume_mass(run, "C6_POST_WETDEP", "001000", tag).sum(dtype=np.float64))
            for tag in TAGS
        }

    return {
        "status": "diagnostic_pass_bounded_qck_v2",
        "scientific_acceptance": False,
        "qck_policy": "conservative full-column QCK_BOTTOM with bounded v2 microclosure",
        "operator_under_test": "native full PBL mixing (non-local scheme disabled)",
        "input_identity": require_input_identity(runs),
        "thread_determinism": {
            "pbl_off": require_thread_identity(off_one, off_eight),
            "pbl_on": require_thread_identity(on_one, on_eight),
        },
        "acceptance": {
            "pbl_mass_conservation_tolerance_kg": conservation_tolerance_kg,
            "expected_pbl_sensitive_tags": sorted(expected_changed),
        },
        "pbl_redistribution": redistribution,
        "qck_microclosure": {
            "pbl_off_kg": qck_off_mass,
            "pbl_on_kg": qck_on_mass,
            "pbl_on_minus_off_kg": qck_on_mass - qck_off_mass,
            "pbl_off_event_count": int(qck_off["event_count"]),
            "pbl_on_event_count": int(qck_on["event_count"]),
            "pbl_off_by_tag_kg": qck_off["microclosure_by_tag_kg"],
            "pbl_on_by_tag_kg": qck_on["microclosure_by_tag_kg"],
        },
        "endpoint_airborne_mass_kg": endpoints,
        "guardrail": (
            "PBL operator behavior is validated only as a diagnostic A/B result; "
            "production and scientific interpretation remain blocked; bounded v2 "
            "is a diagnostic policy, not scientific acceptance."
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
