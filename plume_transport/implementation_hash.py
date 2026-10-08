#!/usr/bin/env python3
"""Compute the deterministic aggregate hash for the plume implementation."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GEOS_CHEM = ROOT / "src" / "GEOS-Chem"
CHECKPOINT_MODULE = GEOS_CHEM / "Interfaces" / "GCClassic" / "plume_checkpoint_mod.F90"
TPCORE_BUDGET_MODULE = GEOS_CHEM / "GeosCore" / "plume_tpcore_budget_mod.F90"
QCK_POSITIVITY_MODULE = GEOS_CHEM / "GeosCore" / "qck_positivity_mod.F90"
QCK_BOTTOM_SURVEY_MODULE = GEOS_CHEM / "GeosCore" / "qck_bottom_survey_mod.F90"
QCK_BOTTOM_REGRESSION = GEOS_CHEM / "test" / "qck_bottom_regression.F90"


def command_bytes(*args: str, directory: Path) -> bytes:
    return subprocess.run(
        args,
        cwd=directory,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def update_component(digest: hashlib._Hash, label: str, payload: bytes) -> None:
    encoded = label.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def included_tooling_files() -> list[Path]:
    files = []
    for path in (ROOT / "plume_transport").rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def main() -> None:
    digest = hashlib.sha256()
    update_component(
        digest,
        "top-level binary diff",
        command_bytes("git", "diff", "--binary", "HEAD", directory=ROOT),
    )
    update_component(
        digest,
        "full GEOS-Chem tracked binary diff",
        command_bytes("git", "diff", "--binary", "HEAD", directory=GEOS_CHEM),
    )
    for path in (
        CHECKPOINT_MODULE,
        TPCORE_BUDGET_MODULE,
        QCK_POSITIVITY_MODULE,
        QCK_BOTTOM_SURVEY_MODULE,
        QCK_BOTTOM_REGRESSION,
    ):
        update_component(digest, path.relative_to(ROOT).as_posix(), path.read_bytes())
    for path in included_tooling_files():
        update_component(digest, path.relative_to(ROOT).as_posix(), path.read_bytes())
    print(digest.hexdigest())


if __name__ == "__main__":
    main()
