#!/usr/bin/env python3
"""Validate the fixed-lifetime plume aging off/on and thread matrix."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from validate_ras_surface_reevap import parse_ledger as parse_ras_ledger

PARENTS = ("PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE")
PRODUCTS = tuple(f"{tag}_PI" for tag in PARENTS)
TAGS = PARENTS + PRODUCTS
SCHEMA = "plume-aging-ledger-v1"
LEDGER_FIELDS = (
    "schema_version", "run_id", "manifest_id", "model_date", "model_time",
    "elapsed_seconds", "chemistry_call_index", "omp_thread_count", "pair_index",
    "parent", "product", "parent_species_id", "product_species_id",
    "chemistry_timestep_s", "lifetime_s", "decay_factor", "parent_before_kg",
    "parent_after_kg", "product_before_kg", "product_after_kg",
    "analytic_transfer_kg", "realized_parent_loss_kg",
    "realized_product_gain_kg", "pair_closure_residual_kg",
)
INT_FIELDS = {
    "model_date", "model_time", "elapsed_seconds", "chemistry_call_index",
    "omp_thread_count", "pair_index", "parent_species_id", "product_species_id",
    "chemistry_timestep_s",
}
STRING_FIELDS = {"schema_version", "run_id", "manifest_id", "parent", "product"}


def close(a: float, b: float, floor: float = 1e-12) -> bool:
    return abs(a - b) <= max(floor, 64.0 * math.ulp(max(abs(a), abs(b), 1.0)))


def parse_ledger(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LEDGER_FIELDS:
            raise ValueError(f"{path}: aging ledger header drift")
        rows: list[dict[str, Any]] = []
        for line_number, raw in enumerate(reader, start=2):
            row: dict[str, Any] = dict(raw)
            for field in INT_FIELDS:
                row[field] = int(row[field])
            for field in set(LEDGER_FIELDS) - INT_FIELDS - STRING_FIELDS:
                row[field] = float(row[field])
                if not math.isfinite(row[field]):
                    raise ValueError(f"{path}:{line_number}: non-finite {field}")
            pair = row["pair_index"] - 1
            if row["schema_version"] != SCHEMA or pair not in range(5):
                raise ValueError(f"{path}:{line_number}: schema or pair drift")
            if row["parent"] != PARENTS[pair] or row["product"] != PRODUCTS[pair]:
                raise ValueError(f"{path}:{line_number}: pair-name drift")
            if row["chemistry_timestep_s"] != 1200 or row["lifetime_s"] != 99360.0:
                raise ValueError(f"{path}:{line_number}: timestep/lifetime drift")
            expected_decay = math.exp(-1200.0 / 99360.0)
            if row["decay_factor"] != expected_decay:
                raise ValueError(f"{path}:{line_number}: decay-factor drift")
            if not close(row["realized_parent_loss_kg"],
                         row["realized_product_gain_kg"]):
                raise ValueError(f"{path}:{line_number}: pair closure failed")
            if not close(
                row["pair_closure_residual_kg"],
                row["realized_parent_loss_kg"] - row["realized_product_gain_kg"],
            ):
                raise ValueError(f"{path}:{line_number}: residual identity failed")
            rows.append(row)
    if len(rows) != 5 or [row["pair_index"] for row in rows] != list(range(1, 6)):
        raise ValueError(f"{path}: expected exactly one ordered five-pair chemistry call")
    return rows


def normalized_csv(path: Path, ignored: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            {key: value for key, value in row.items() if key not in ignored}
            for row in csv.DictReader(handle)
        ]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def checkpoint_files(run_dir: Path) -> dict[str, Path]:
    files = sorted((run_dir / "OutputDir" / "PlumeCheckpoints").glob("*.nc4"))
    if len(files) != 14:
        raise ValueError(f"{run_dir}: expected 14 checkpoint files, found {len(files)}")
    return {path.name.split(".20190101_")[0].split("PlumeCheckpoint.")[1] +
            "." + path.name.split(".20190101_")[1].split("z.nc4")[0]: path
            for path in files}


def mass_arrays(path: Path) -> dict[str, np.ndarray]:
    with h5py.File(path, "r") as handle:
        return {tag: np.asarray(handle[f"PlumeMass_{tag}"][:], dtype=np.float64)
                for tag in TAGS}


def exact_h5_payloads(left: Path, right: Path) -> bool:
    with h5py.File(left, "r") as a, h5py.File(right, "r") as b:
        a_names: list[str] = []
        b_names: list[str] = []
        a.visititems(lambda name, obj: a_names.append(name) if isinstance(obj, h5py.Dataset) else None)
        b.visititems(lambda name, obj: b_names.append(name) if isinstance(obj, h5py.Dataset) else None)
        if a_names != b_names:
            return False
        return all(
            np.array_equal(a[name][()], b[name][()], equal_nan=True)
            for name in a_names
        )


def validate_operator(off_dir: Path, on_dir: Path, ledger: list[dict[str, Any]]) -> dict[str, Any]:
    off = checkpoint_files(off_dir)
    on = checkpoint_files(on_dir)
    result: dict[str, Any] = {"off_noop_exact": True, "on_pairs": {}}
    for heartbeat in ("000000", "001000"):
        c4_key = f"C4_POST_CONVECTION.{heartbeat}"
        c5_key = f"C5_POST_CHEMISTRY.{heartbeat}"
        off_c4, off_c5 = mass_arrays(off[c4_key]), mass_arrays(off[c5_key])
        if not all(np.array_equal(off_c4[tag], off_c5[tag]) for tag in TAGS):
            result["off_noop_exact"] = False
        on_c4, on_c5 = mass_arrays(on[c4_key]), mass_arrays(on[c5_key])
        if heartbeat == "001000":
            if not all(np.array_equal(on_c4[tag], on_c5[tag]) for tag in TAGS):
                raise ValueError("unexpected second aging call")
            continue
        decay = math.exp(-1200.0 / 99360.0)
        for pair, (parent, product) in enumerate(zip(PARENTS, PRODUCTS)):
            parent_error = float(np.max(np.abs(on_c5[parent] - on_c4[parent] * decay)))
            transfer_error = float(np.max(np.abs(
                (on_c5[product] - on_c4[product]) -
                (on_c4[parent] - on_c5[parent])
            )))
            parent_loss = float(on_c4[parent].sum() - on_c5[parent].sum())
            product_gain = float(on_c5[product].sum() - on_c4[product].sum())
            row = ledger[pair]
            passed = (
                parent_error <= 1e-12 and transfer_error <= 1e-12 and
                close(parent_loss, product_gain) and
                close(parent_loss, row["realized_parent_loss_kg"]) and
                close(product_gain, row["realized_product_gain_kg"])
            )
            result["on_pairs"][parent] = {
                "parent_loss_kg": parent_loss,
                "product_gain_kg": product_gain,
                "fraction_transferred": 1.0 - decay,
                "max_parent_exponential_error_kg": parent_error,
                "max_cellwise_transfer_error_kg": transfer_error,
                "passed": passed,
            }
    result["passed"] = result["off_noop_exact"] and all(
        pair["passed"] for pair in result["on_pairs"].values()
    )
    return result


def validate_budget(run_dir: Path, ledger: list[dict[str, Any]]) -> dict[str, Any]:
    path = run_dir / "OutputDir" / "GEOSChem.Budget.20190101_0000z.nc4"
    results: dict[str, Any] = {}
    with h5py.File(path, "r") as handle:
        for pair, (parent, product) in enumerate(zip(PARENTS, PRODUCTS)):
            p_rate = np.asarray(handle[f"BudgetChemistryFull_{parent}"][:])
            q_rate = np.asarray(handle[f"BudgetChemistryFull_{product}"][:])
            p_mass = float(p_rate.astype(np.float64).sum() * 1200.0)
            q_mass = float(q_rate.astype(np.float64).sum() * 1200.0)
            tolerance = max(
                1e-6,
                64.0 * 1200.0 * float(
                    np.spacing(np.abs(p_rate)).astype(np.float64).sum() +
                    np.spacing(np.abs(q_rate)).astype(np.float64).sum()
                ),
            )
            ledger_transfer = ledger[pair]["realized_parent_loss_kg"]
            passed = (abs(p_mass + q_mass) <= tolerance and
                      abs(-p_mass - ledger_transfer) <= tolerance and
                      abs(q_mass - ledger_transfer) <= tolerance)
            results[parent] = {"parent_change_kg": p_mass, "product_change_kg": q_mass,
                               "tolerance_kg": tolerance, "passed": passed}
    return {"pairs": results, "passed": all(item["passed"] for item in results.values())}


def validate_thread_pair(one: Path, eight: Path, aging_on: bool) -> dict[str, Any]:
    one_checkpoints = checkpoint_files(one)
    eight_checkpoints = checkpoint_files(eight)
    checkpoint_exact = one_checkpoints.keys() == eight_checkpoints.keys() and all(
        exact_h5_payloads(one_checkpoints[key], eight_checkpoints[key])
        for key in one_checkpoints
    )
    history_one = sorted((one / "OutputDir").glob("GEOSChem.*.nc4"))
    history_eight = {path.name: path for path in (eight / "OutputDir").glob("GEOSChem.*.nc4")}
    history_exact = all(path.name in history_eight and
                        exact_h5_payloads(path, history_eight[path.name])
                        for path in history_one) and len(history_one) == len(history_eight)
    qck_exact = normalized_csv(
        one / "OutputDir/qck_bottom_survey_v1.csv",
        {"run_id", "omp_thread_count"},
    ) == normalized_csv(
        eight / "OutputDir/qck_bottom_survey_v1.csv",
        {"run_id", "omp_thread_count"},
    )
    ras_exact = normalized_csv(
        one / "OutputDir/ras_surface_reevap.csv",
        {"run_id", "manifest_id", "omp_thread_count"},
    ) == normalized_csv(
        eight / "OutputDir/ras_surface_reevap.csv",
        {"run_id", "manifest_id", "omp_thread_count"},
    )
    ras_rows = parse_ras_ledger(one / "OutputDir/ras_surface_reevap.csv")
    ras_tags = {row["tag"] for row in ras_rows}
    expected_ras_tags = set(TAGS if aging_on else PARENTS)
    ras_contract = ras_tags == expected_ras_tags and all(
        close(row["signed_wetloss_kg"], row["realized_signed_loss_kg"])
        for row in ras_rows
    )
    aging_exact = True
    if aging_on:
        aging_exact = normalized_csv(
            one / "OutputDir/plume_aging_v1.csv",
            {"run_id", "manifest_id", "omp_thread_count"},
        ) == normalized_csv(
            eight / "OutputDir/plume_aging_v1.csv",
            {"run_id", "manifest_id", "omp_thread_count"},
        )
    result = {"checkpoint_exact": checkpoint_exact, "history_exact": history_exact,
              "qck_exact": qck_exact, "ras_ledger_exact": ras_exact,
              "ras_formula_realized_and_pool_coverage": ras_contract,
              "aging_ledger_exact": aging_exact}
    result["passed"] = all(result.values())
    return result


def validate_matrix(off_one: Path, off_eight: Path, on_one: Path,
                    on_eight: Path) -> dict[str, Any]:
    for path in (off_one, off_eight, on_one, on_eight):
        if (path / "model_exit_code.txt").read_text().strip() != "0":
            raise ValueError(f"{path}: nonzero model exit")
    if (off_one / "OutputDir/plume_aging_v1.csv").exists() or \
       (off_eight / "OutputDir/plume_aging_v1.csv").exists():
        raise ValueError("aging-off arm unexpectedly created an aging ledger")
    ledger_one = parse_ledger(on_one / "OutputDir/plume_aging_v1.csv")
    ledger_eight = parse_ledger(on_eight / "OutputDir/plume_aging_v1.csv")
    operator = validate_operator(off_one, on_one, ledger_one)
    budget = validate_budget(on_one, ledger_one)
    threads = {
        "off": validate_thread_pair(off_one, off_eight, False),
        "on": validate_thread_pair(on_one, on_eight, True),
    }
    status = "pass" if operator["passed"] and budget["passed"] and all(
        item["passed"] for item in threads.values()
    ) else "fail"
    return {"schema_version": "stage1-aging-validation-v1", "status": status,
            "scientific_acceptance": False, "operator": operator,
            "budget_chemistry_crosscheck": budget, "thread_determinism": threads,
            "ledger_thread_exact": ledger_one[0]["decay_factor"] ==
                                    ledger_eight[0]["decay_factor"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("off_one", type=Path)
    parser.add_argument("off_eight", type=Path)
    parser.add_argument("on_one", type=Path)
    parser.add_argument("on_eight", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = validate_matrix(args.off_one, args.off_eight, args.on_one, args.on_eight)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
