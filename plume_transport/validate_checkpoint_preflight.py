#!/usr/bin/env python3
"""Validate runtime readiness of a manifested plume checkpoint directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from manifest_utils import load_manifest


def check_checkpoint_directory(manifest: dict) -> dict[str, object]:
    runtime = manifest["checkpoint_runtime"]
    if runtime["enabled"] is not True:
        return {
            "status": "pass",
            "checkpoint_runtime": "disabled_not_applicable",
            "case_id": manifest["case_id"],
        }

    directory = Path(manifest["paths"]["checkpoint_directory"]).resolve()
    if not directory.exists():
        raise FileNotFoundError(f"checkpoint directory is absent: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"checkpoint path is not a directory: {directory}")
    if next(directory.iterdir(), None) is not None:
        raise ValueError(f"checkpoint directory is not empty: {directory}")

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".checkpoint-preflight-",
            dir=directory,
        ) as probe:
            probe.write(b"checkpoint-preflight\n")
            probe.flush()
    except OSError as error:
        raise PermissionError(
            f"checkpoint directory is not writable: {directory}"
        ) from error

    if next(directory.iterdir(), None) is not None:
        raise RuntimeError(f"checkpoint write probe left an artifact: {directory}")
    return {
        "status": "pass",
        "checkpoint_runtime": "enabled_ready",
        "case_id": manifest["case_id"],
        "checkpoint_directory": str(directory),
        "exists": True,
        "empty": True,
        "writable_probe": "pass",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = check_checkpoint_directory(load_manifest(args.manifest))
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
    result["manifest"] = str(args.manifest.resolve())
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
