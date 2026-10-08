#!/usr/bin/env python3
"""Launch a prepared wet/aging control from its resolved child manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from manifest_utils import load_manifest, resolved_manifest_sha256
from prepare_run import (
    AGING_PREPARATION_CONTRACT,
    WET_DEPOSITION_PREPARATION_CONTRACT,
    validate_aging_runtime_contract,
    validate_bounded_qck_v2_runtime_contract,
    validate_ras_surface_reevap_runtime_contract,
)


def _add_environment(
    selected: dict[str, str], mapping: object, label: str
) -> None:
    if not isinstance(mapping, dict):
        raise ValueError(f"{label} must be an environment mapping")
    for name, raw_value in mapping.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"{label} contains an invalid environment name")
        value = str(raw_value)
        previous = selected.get(name)
        if previous is not None and previous != value:
            raise ValueError(f"{label} conflicts for {name}")
        selected[name] = value


def select_runtime_environment(manifest: dict[str, Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return the only environment allowed for a resolved wet/aging child."""

    contract = manifest.get("preparation_contract")
    if contract not in {
        WET_DEPOSITION_PREPARATION_CONTRACT,
        AGING_PREPARATION_CONTRACT,
    }:
        raise ValueError("runtime launcher supports only wet-deposition or aging contracts")
    validate_bounded_qck_v2_runtime_contract(manifest, str(contract))
    validate_ras_surface_reevap_runtime_contract(manifest, str(contract))
    if contract == AGING_PREPARATION_CONTRACT:
        validate_aging_runtime_contract(manifest, str(contract))

    selected: dict[str, str] = {}
    _add_environment(
        selected,
        manifest.get("checkpoint_runtime", {}).get("environment"),
        "checkpoint runtime",
    )
    _add_environment(
        selected,
        manifest.get("tpcore_budget_runtime", {}).get("environment"),
        "TPCORE budget runtime",
    )
    runtime_contract = manifest["runtime_contract"]
    for key in (
        "microclosure_environment",
        "cell_diagnostics_environment",
        "donor_diagnostics_environment",
    ):
        _add_environment(selected, runtime_contract.get(key), key)
    _add_environment(
        selected,
        manifest["ras_surface_reevap_runtime"].get("environment"),
        "RAS surface re-evaporation runtime",
    )
    aging_clear: tuple[str, ...] = ()
    if contract == AGING_PREPARATION_CONTRACT:
        aging_runtime = manifest["aging_runtime"]
        _add_environment(
            selected,
            aging_runtime.get("environment"),
            "aging runtime",
        )
        aging_clear = tuple(str(name) for name in aging_runtime["clear_environment"])

    omp_threads = int(runtime_contract["omp_num_threads"])
    if omp_threads <= 0 or omp_threads != int(manifest["run"]["omp_threads"]):
        raise ValueError("OMP thread contract differs from the declared run")
    selected["OMP_NUM_THREADS"] = str(omp_threads)
    if "omp_stacksize" in runtime_contract:
        selected["OMP_STACKSIZE"] = str(runtime_contract["omp_stacksize"])

    native_survey_unset = tuple(
        str(name) for name in runtime_contract["unset_environment"]
    )
    unset = native_survey_unset + aging_clear
    if len(set(unset)) != len(unset) or set(native_survey_unset).intersection(selected):
        raise ValueError("native survey unset contract conflicts with selected environment")
    return dict(sorted(selected.items())), unset


def runtime_record(
    manifest_path: Path,
    manifest: dict[str, Any],
    selected: dict[str, str],
    unset: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "case_id": manifest["case_id"],
        "manifest_path": str(manifest_path.resolve()),
        "resolved_manifest_sha256_at_launch": resolved_manifest_sha256(manifest),
        "selected_environment": selected,
        "status": "manifest-derived-runtime-environment",
        "unset_environment": list(unset),
    }


def launch(
    manifest_path: Path,
    run_directory: Path,
    record_path: Path,
    *,
    dry_run: bool,
) -> int:
    manifest = load_manifest(manifest_path)
    run_directory = run_directory.resolve()
    if run_directory != Path(manifest["paths"]["run_directory"]).resolve():
        raise ValueError("run directory differs from the resolved child manifest")
    executable = run_directory / "gcclassic"
    if not executable.is_file():
        raise FileNotFoundError(f"run-directory executable is absent: {executable}")
    selected, unset = select_runtime_environment(manifest)
    record = runtime_record(manifest_path, manifest, selected, unset)
    if dry_run:
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0

    output_directory = run_directory / "OutputDir"
    record_path = record_path.resolve()
    if record_path.parent != output_directory.resolve():
        raise ValueError("runtime record must be written directly in OutputDir")
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    environment = os.environ.copy()
    for name in unset:
        environment.pop(name, None)
    environment.update(selected)
    completed = subprocess.run(
        ["./gcclassic"], cwd=run_directory, env=environment, check=False
    )
    (output_directory / "model_exit_code.txt").write_text(
        f"{completed.returncode}\n", encoding="utf-8"
    )
    return completed.returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    record = args.record or args.run_directory / "OutputDir" / "runtime_environment.json"
    raise SystemExit(launch(args.manifest, args.run_directory, record, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
