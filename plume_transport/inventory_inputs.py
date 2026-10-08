#!/usr/bin/env python3
"""Inventory and verify every ExtData file resolved by a GCClassic dry run."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from generate_source import sha256


OPEN_PATTERN = re.compile(r"^HEMCO: Opening\s+(.+?)\s*$")


def resolved_extdata_paths(log: Path) -> list[Path]:
    paths: set[Path] = set()
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = OPEN_PATTERN.match(line)
        if not match:
            continue
        path = Path(match.group(1)).resolve()
        if "/ExtData/" in str(path):
            paths.add(path)
    return sorted(paths, key=str)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("dryrun_log", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    with args.manifest.open(encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    declared_items = list(manifest["extdata_inventory"]["files"].values())
    declared = {Path(item["path"]).resolve(): item for item in declared_items}
    if len(declared) != len(declared_items):
        raise ValueError("manifest resolved-input paths are not unique")

    opened = resolved_extdata_paths(args.dryrun_log)
    if set(opened) != set(declared):
        missing = sorted(str(path) for path in set(declared) - set(opened))
        undeclared = sorted(str(path) for path in set(opened) - set(declared))
        raise ValueError(
            f"resolved ExtData inventory mismatch; missing={missing}, "
            f"undeclared={undeclared}"
        )

    checks = []
    for path in opened:
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256(path)
        expected = str(declared[path]["sha256"])
        if actual != expected:
            raise ValueError(f"{path}: SHA-256 {actual} != declared {expected}")
        checks.append(
            {
                "role": str(declared[path]["role"]),
                "path": str(path),
                "sha256": actual,
            }
        )

    report = {
        "status": "pass",
        "manifest": str(args.manifest.resolve()),
        "dryrun_log": str(args.dryrun_log.resolve()),
        "resolved_input_count": len(checks),
        "resolved_inputs": checks,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
