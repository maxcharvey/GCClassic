#!/usr/bin/env python3
"""Run full TPCORE contract and controlled-input checks before execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_tpcore import (
    acceptance_tolerances,
    load_validation_manifest,
    validate_checked_inputs,
    validate_operator_and_checkpoint_contract,
)


def run_preflight(manifest_path: Path, phase: str) -> dict[str, object]:
    if phase not in {"prebuild", "postbuild"}:
        raise ValueError("preflight phase must be prebuild or postbuild")
    manifest = load_validation_manifest(manifest_path)
    validate_operator_and_checkpoint_contract(manifest)
    tolerances = acceptance_tolerances(manifest)
    run_directory = Path(manifest["paths"]["run_directory"]).resolve()
    if not run_directory.is_dir():
        raise FileNotFoundError(f"run directory is absent: {run_directory}")
    checked_inputs = validate_checked_inputs(
        run_directory,
        manifest,
        require_executable=(phase == "postbuild"),
    )
    return {
        "status": "pass",
        "case_id": manifest["case_id"],
        "manifest": str(manifest_path.resolve()),
        "run_directory": str(run_directory),
        "phase": phase,
        "executable_identity_required": phase == "postbuild",
        "controlled_inputs": checked_inputs,
        "acceptance_contract": manifest["acceptance_contract"],
        "tolerance_count": len(tolerances),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--phase", choices=("prebuild", "postbuild"), required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = run_preflight(args.manifest, args.phase)
    except Exception as error:
        result = {
            "status": "fail",
            "manifest": str(args.manifest.resolve()),
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        if args.report:
            args.report.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        raise
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
