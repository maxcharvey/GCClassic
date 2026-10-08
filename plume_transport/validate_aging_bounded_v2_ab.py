#!/usr/bin/env python3
"""Validate the survey-free bounded-QCK v2 fixed-lifetime aging matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
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
AGING_SCHEMA = "plume-aging-ledger-v1"
AGING_FIELDS = (
    "schema_version", "run_id", "manifest_id", "model_date", "model_time",
    "elapsed_seconds", "chemistry_call_index", "omp_thread_count", "pair_index",
    "parent", "product", "parent_species_id", "product_species_id",
    "chemistry_timestep_s", "lifetime_s", "decay_factor", "parent_before_kg",
    "parent_after_kg", "product_before_kg", "product_after_kg",
    "analytic_transfer_kg", "realized_parent_loss_kg",
    "realized_product_gain_kg", "pair_closure_residual_kg",
)
AGING_INT_FIELDS = {
    "model_date", "model_time", "elapsed_seconds", "chemistry_call_index",
    "omp_thread_count", "pair_index", "parent_species_id", "product_species_id",
    "chemistry_timestep_s",
}
AGING_STRING_FIELDS = {"schema_version", "run_id", "manifest_id", "parent", "product"}
TPCORE_FILES = (
    "plume_tpcore_budget_v2.csv",
    "plume_tpcore_cell_events_v3.csv",
    "plume_tpcore_donor_events_v3.csv",
)
VALIDATOR_REPORTS = (
    "tpcore_budget_validation.json",
    "tpcore_cell_diagnostic_validation.json",
    "tpcore_donor_diagnostic_validation.json",
)
SURVEY_ENVIRONMENT = {
    "GC_QCK_BOTTOM_SURVEY",
    "GC_QCK_BOTTOM_SURVEY_RUN_ID",
    "GC_QCK_BOTTOM_SURVEY_FILE",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def close(left: float, right: float, floor: float = 1e-12) -> bool:
    return abs(left - right) <= max(
        floor, 64.0 * math.ulp(max(abs(left), abs(right), 1.0))
    )


def normalized_csv(path: Path, ignored: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            {key: value for key, value in row.items() if key not in ignored}
            for row in csv.DictReader(handle)
        ]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def exact_h5_payloads(left: Path, right: Path) -> bool:
    with h5py.File(left, "r") as first, h5py.File(right, "r") as second:
        first_names: list[str] = []
        second_names: list[str] = []
        first.visititems(
            lambda name, value: first_names.append(name)
            if isinstance(value, h5py.Dataset)
            else None
        )
        second.visititems(
            lambda name, value: second_names.append(name)
            if isinstance(value, h5py.Dataset)
            else None
        )
        return first_names == second_names and all(
            np.array_equal(first[name][()], second[name][()], equal_nan=True)
            for name in first_names
        )


def checkpoint_files(run_directory: Path) -> dict[str, Path]:
    files = sorted((run_directory / "OutputDir" / "PlumeCheckpoints").glob("*.nc4"))
    if len(files) != 14:
        raise ValueError(f"{run_directory}: expected 14 checkpoint files, found {len(files)}")
    result: dict[str, Path] = {}
    for path in files:
        try:
            label, timestamp = path.name.split("PlumeCheckpoint.", 1)[1].split(
                ".20190101_", 1
            )
        except IndexError as error:
            raise ValueError(f"{path}: unexpected checkpoint name") from error
        key = f"{label}.{timestamp.removesuffix('z.nc4')}"
        if key in result:
            raise ValueError(f"{run_directory}: duplicate checkpoint key {key}")
        result[key] = path
    return result


def mass_arrays(path: Path) -> dict[str, np.ndarray]:
    with h5py.File(path, "r") as handle:
        tag_names = handle["tag_id"].attrs.get("tag_names")
        if isinstance(tag_names, bytes):
            tag_names = tag_names.decode("utf-8")
        if str(tag_names) != ",".join(TAGS):
            raise ValueError(f"{path}: checkpoint does not carry all ten aging pools")
        global_mass = np.asarray(handle["global_plume_mass"][:], dtype=np.float64)
        if global_mass.shape != (len(TAGS),) or np.any(~np.isfinite(global_mass)):
            raise ValueError(f"{path}: invalid ten-pool global mass")
        arrays = {
            tag: np.asarray(handle[f"PlumeMass_{tag}"][:], dtype=np.float64)
            for tag in TAGS
        }
    reference_shape = arrays[PARENTS[0]].shape
    for tag, values in arrays.items():
        if values.shape != reference_shape or np.any(~np.isfinite(values)):
            raise ValueError(f"{path}: invalid {tag} checkpoint state")
        if np.any(values < 0.0):
            raise ValueError(f"{path}: negative {tag} checkpoint state")
    return arrays


def parse_aging_ledger(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != AGING_FIELDS:
            raise ValueError(f"{path}: aging ledger header drift")
        rows: list[dict[str, Any]] = []
        for line_number, raw in enumerate(reader, start=2):
            row: dict[str, Any] = dict(raw)
            for field in AGING_INT_FIELDS:
                row[field] = int(row[field])
            for field in set(AGING_FIELDS) - AGING_INT_FIELDS - AGING_STRING_FIELDS:
                row[field] = float(row[field])
                if not math.isfinite(row[field]):
                    raise ValueError(f"{path}:{line_number}: non-finite {field}")
            pair = row["pair_index"] - 1
            if row["schema_version"] != AGING_SCHEMA or pair not in range(len(PARENTS)):
                raise ValueError(f"{path}:{line_number}: aging schema or pair drift")
            if row["parent"] != PARENTS[pair] or row["product"] != PRODUCTS[pair]:
                raise ValueError(f"{path}:{line_number}: aging pair-name drift")
            if row["chemistry_timestep_s"] != 1200 or row["lifetime_s"] != 99360.0:
                raise ValueError(f"{path}:{line_number}: aging timestep or lifetime drift")
            expected_decay = math.exp(-1200.0 / 99360.0)
            if row["decay_factor"] != expected_decay:
                raise ValueError(f"{path}:{line_number}: aging decay-factor drift")
            if not close(row["realized_parent_loss_kg"], row["realized_product_gain_kg"]):
                raise ValueError(f"{path}:{line_number}: aging pair closure failed")
            if not close(
                row["pair_closure_residual_kg"],
                row["realized_parent_loss_kg"] - row["realized_product_gain_kg"],
            ):
                raise ValueError(f"{path}:{line_number}: aging residual identity failed")
            rows.append(row)
    if len(rows) != len(PARENTS) or [row["pair_index"] for row in rows] != list(
        range(1, len(PARENTS) + 1)
    ):
        raise ValueError(f"{path}: expected one ordered five-pair aging call")
    return rows


def validate_runtime_contract(run_directory: Path, aging_on: bool, threads: int) -> dict[str, Any]:
    record_path = run_directory / "OutputDir" / "runtime_environment.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("status") != "manifest-derived-runtime-environment":
        raise ValueError(f"{record_path}: invalid runtime-record status")
    selected = record.get("selected_environment")
    unset = set(record.get("unset_environment", ()))
    if not isinstance(selected, dict) or SURVEY_ENVIRONMENT.intersection(selected):
        raise ValueError(f"{record_path}: native survey runtime is not excluded")
    if not SURVEY_ENVIRONMENT.issubset(unset):
        raise ValueError(f"{record_path}: native survey unset contract is incomplete")
    expected = {
        "GC_PLUME_CHECKPOINT_AGED_POOLS": "1",
        "GC_RAS_SURFACE_REEVAP_LEDGER": "1",
        "GC_RAS_SURFACE_REEVAP_INCLUDE_AGED": "1",
        "GC_PLUME_AGING_LIFETIME_S": "99360",
        "GC_PLUME_AGING_FILE": "./OutputDir/plume_aging_v1.csv",
        "OMP_NUM_THREADS": str(threads),
    }
    for name, value in expected.items():
        if selected.get(name) != value:
            raise ValueError(f"{record_path}: runtime {name} differs from the contract")
    if "GC_PLUME_AGING" not in unset:
        raise ValueError(f"{record_path}: inherited aging gate was not cleared")
    if aging_on:
        if selected.get("GC_PLUME_AGING") != "1":
            raise ValueError(f"{record_path}: aging-on runtime gate is absent")
    elif "GC_PLUME_AGING" in selected:
        raise ValueError(f"{record_path}: aging-off runtime gate is present")
    return {
        "runtime_environment_sha256": sha256(record_path),
        "resolved_manifest_sha256_at_launch": record.get(
            "resolved_manifest_sha256_at_launch"
        ),
        "native_survey_environment": "unset",
    }


def validate_auxiliary_reports(run_directory: Path) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for name in VALIDATOR_REPORTS:
        path = run_directory / "OutputDir" / name
        report = json.loads(path.read_text(encoding="utf-8"))
        result[name] = report.get("status") in {"pass", "PASS"}
    if not all(result.values()):
        raise ValueError(f"{run_directory}: a per-run TPCORE validator did not pass")
    return result


def validate_operator(
    off_directory: Path, on_directory: Path, ledger: list[dict[str, Any]]
) -> dict[str, Any]:
    off = checkpoint_files(off_directory)
    on = checkpoint_files(on_directory)
    result: dict[str, Any] = {
        "off_noop_exact": True,
        "pre_aging_off_on_exact": True,
        "initial_product_pools_exact_zero": True,
        "on_pairs": {},
    }
    initial = mass_arrays(on["C0_PRE_TPCORE.000000"])
    result["initial_product_pools_exact_zero"] = all(
        bool(np.all(initial[tag] == 0.0)) for tag in PRODUCTS
    )
    decay = math.exp(-1200.0 / 99360.0)
    for heartbeat in ("000000", "001000"):
        c4_key = f"C4_POST_CONVECTION.{heartbeat}"
        c5_key = f"C5_POST_CHEMISTRY.{heartbeat}"
        off_c4, off_c5 = mass_arrays(off[c4_key]), mass_arrays(off[c5_key])
        on_c4, on_c5 = mass_arrays(on[c4_key]), mass_arrays(on[c5_key])
        if not all(np.array_equal(off_c4[tag], off_c5[tag]) for tag in TAGS):
            result["off_noop_exact"] = False
        if heartbeat == "000000" and not all(
            np.array_equal(off_c4[tag], on_c4[tag]) for tag in TAGS
        ):
            result["pre_aging_off_on_exact"] = False
        if heartbeat == "001000":
            if not all(np.array_equal(on_c4[tag], on_c5[tag]) for tag in TAGS):
                raise ValueError("unexpected second aging call")
            continue
        for pair, (parent, product) in enumerate(zip(PARENTS, PRODUCTS)):
            parent_error = float(np.max(np.abs(on_c5[parent] - on_c4[parent] * decay)))
            transfer_error = float(
                np.max(
                    np.abs(
                        (on_c5[product] - on_c4[product])
                        - (on_c4[parent] - on_c5[parent])
                    )
                )
            )
            pair_error = float(
                np.max(
                    np.abs(
                        (on_c5[parent] + on_c5[product])
                        - (on_c4[parent] + on_c4[product])
                    )
                )
            )
            parent_loss = float(on_c4[parent].sum() - on_c5[parent].sum())
            product_gain = float(on_c5[product].sum() - on_c4[product].sum())
            row = ledger[pair]
            passed = (
                parent_error <= 1e-12
                and transfer_error <= 1e-12
                and pair_error <= 1e-12
                and close(parent_loss, product_gain)
                and close(parent_loss, row["realized_parent_loss_kg"])
                and close(product_gain, row["realized_product_gain_kg"])
            )
            result["on_pairs"][parent] = {
                "parent_loss_kg": parent_loss,
                "product_gain_kg": product_gain,
                "fraction_transferred": 1.0 - decay,
                "max_parent_exponential_error_kg": parent_error,
                "max_cellwise_transfer_error_kg": transfer_error,
                "max_cellwise_pair_conservation_error_kg": pair_error,
                "passed": passed,
            }
    result["passed"] = (
        result["off_noop_exact"]
        and result["pre_aging_off_on_exact"]
        and result["initial_product_pools_exact_zero"]
        and all(pair["passed"] for pair in result["on_pairs"].values())
    )
    return result


def validate_chemistry_budget(
    run_directory: Path, ledger: list[dict[str, Any]]
) -> dict[str, Any]:
    path = run_directory / "OutputDir" / "GEOSChem.Budget.20190101_0000z.nc4"
    results: dict[str, Any] = {}
    with h5py.File(path, "r") as handle:
        for pair, (parent, product) in enumerate(zip(PARENTS, PRODUCTS)):
            parent_rate = np.asarray(handle[f"BudgetChemistryFull_{parent}"][:])
            product_rate = np.asarray(handle[f"BudgetChemistryFull_{product}"][:])
            parent_change = float(parent_rate.astype(np.float64).sum() * 1200.0)
            product_change = float(product_rate.astype(np.float64).sum() * 1200.0)
            tolerance = max(
                1e-6,
                64.0
                * 1200.0
                * float(
                    np.spacing(np.abs(parent_rate)).astype(np.float64).sum()
                    + np.spacing(np.abs(product_rate)).astype(np.float64).sum()
                ),
            )
            transfer = ledger[pair]["realized_parent_loss_kg"]
            passed = (
                abs(parent_change + product_change) <= tolerance
                and abs(-parent_change - transfer) <= tolerance
                and abs(product_change - transfer) <= tolerance
            )
            results[parent] = {
                "parent_change_kg": parent_change,
                "product_change_kg": product_change,
                "tolerance_kg": tolerance,
                "passed": passed,
            }
    return {"pairs": results, "passed": all(item["passed"] for item in results.values())}


def exact_directory_h5_payloads(left: Path, right: Path, directory: str) -> bool:
    left_files = sorted((left / directory).glob("*.nc4"))
    right_by_name = {path.name: path for path in (right / directory).glob("*.nc4")}
    return len(left_files) == len(right_by_name) and all(
        path.name in right_by_name and exact_h5_payloads(path, right_by_name[path.name])
        for path in left_files
    )


def validate_thread_pair(one: Path, eight: Path, aging_on: bool) -> dict[str, Any]:
    one_checkpoints = checkpoint_files(one)
    eight_checkpoints = checkpoint_files(eight)
    checkpoint_exact = one_checkpoints.keys() == eight_checkpoints.keys() and all(
        exact_h5_payloads(one_checkpoints[key], eight_checkpoints[key])
        for key in one_checkpoints
    )
    history_exact = exact_directory_h5_payloads(one, eight, "OutputDir")
    restart_exact = exact_directory_h5_payloads(one, eight, "Restarts")
    tpcore_exact = {
        name: normalized_csv(one / "OutputDir" / name, {"run_id", "manifest_id", "omp_thread_count"})
        == normalized_csv(eight / "OutputDir" / name, {"run_id", "manifest_id", "omp_thread_count"})
        for name in TPCORE_FILES
    }
    ras_one = one / "OutputDir" / "ras_surface_reevap.csv"
    ras_eight = eight / "OutputDir" / "ras_surface_reevap.csv"
    ras_rows = parse_ras_ledger(ras_one)
    ras_exact = normalized_csv(
        ras_one, {"run_id", "manifest_id", "omp_thread_count"}
    ) == normalized_csv(ras_eight, {"run_id", "manifest_id", "omp_thread_count"})
    expected_ras_tags = set(TAGS if aging_on else PARENTS)
    ras_contract = {row["tag"] for row in ras_rows} == expected_ras_tags and all(
        close(row["signed_wetloss_kg"], row["realized_signed_loss_kg"])
        for row in ras_rows
    )
    aging_exact = True
    if aging_on:
        aging_exact = normalized_csv(
            one / "OutputDir" / "plume_aging_v1.csv",
            {"run_id", "manifest_id", "omp_thread_count"},
        ) == normalized_csv(
            eight / "OutputDir" / "plume_aging_v1.csv",
            {"run_id", "manifest_id", "omp_thread_count"},
        )
    survey_absent = not any(
        (run / "OutputDir" / "qck_bottom_survey_v1.csv").exists()
        for run in (one, eight)
    )
    result: dict[str, Any] = {
        "checkpoint_exact": checkpoint_exact,
        "history_exact": history_exact,
        "restart_exact": restart_exact,
        "tpcore_ledger_exact": tpcore_exact,
        "ras_ledger_exact": ras_exact,
        "ras_formula_realized_and_pool_coverage": ras_contract,
        "aging_ledger_exact": aging_exact,
        "native_survey_artifact_absent": survey_absent,
    }
    result["passed"] = all(
        bool(value) if not isinstance(value, dict) else all(value.values())
        for value in result.values()
    )
    return result


def validate_matrix(off_one: Path, off_eight: Path, on_one: Path, on_eight: Path) -> dict[str, Any]:
    run_directories = {
        ("off", 1): off_one,
        ("off", 8): off_eight,
        ("on", 1): on_one,
        ("on", 8): on_eight,
    }
    runtime: dict[str, dict[str, Any]] = {}
    auxiliary: dict[str, dict[str, bool]] = {}
    for (arm, threads), run_directory in run_directories.items():
        exit_record = run_directory / "OutputDir" / "model_exit_code.txt"
        if exit_record.read_text(encoding="utf-8").strip() != "0":
            raise ValueError(f"{run_directory}: nonzero model exit")
        for path in checkpoint_files(run_directory).values():
            mass_arrays(path)
        runtime[f"{arm}_{threads}"] = validate_runtime_contract(
            run_directory, arm == "on", threads
        )
        auxiliary[f"{arm}_{threads}"] = validate_auxiliary_reports(run_directory)
    for run_directory in (off_one, off_eight):
        if (run_directory / "OutputDir" / "plume_aging_v1.csv").exists():
            raise ValueError("aging-off arm unexpectedly created an aging ledger")

    ledger_one = parse_aging_ledger(on_one / "OutputDir" / "plume_aging_v1.csv")
    parse_aging_ledger(on_eight / "OutputDir" / "plume_aging_v1.csv")
    operator = validate_operator(off_one, on_one, ledger_one)
    chemistry_budget = validate_chemistry_budget(on_one, ledger_one)
    threads = {
        "off": validate_thread_pair(off_one, off_eight, False),
        "on": validate_thread_pair(on_one, on_eight, True),
    }
    passed = (
        operator["passed"]
        and chemistry_budget["passed"]
        and all(item["passed"] for item in threads.values())
    )
    return {
        "schema_version": "stage1-aging-bounded-qck-v2-validation-v1",
        "status": "diagnostic_pass_bounded_qck_v2" if passed else "diagnostic_fail_bounded_qck_v2",
        "scientific_acceptance": False,
        "qck_policy": "survey-free bounded v2 microclosure with v3 cell/donor ledgers",
        "operator": operator,
        "budget_chemistry_crosscheck": chemistry_budget,
        "thread_determinism": threads,
        "runtime_environment": runtime,
        "per_run_tpcore_validator_status": auxiliary,
        "guardrail": (
            "The fixed 99360 s transfer is an engineering reference only; this result "
            "does not choose a scientific BrC aging lifetime or production configuration."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("off_one", type=Path)
    parser.add_argument("off_eight", type=Path)
    parser.add_argument("on_one", type=Path)
    parser.add_argument("on_eight", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = validate_matrix(args.off_one, args.off_eight, args.on_one, args.on_eight)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "diagnostic_pass_bounded_qck_v2" else 1


if __name__ == "__main__":
    raise SystemExit(main())
