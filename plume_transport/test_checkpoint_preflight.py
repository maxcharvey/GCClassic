#!/usr/bin/env python3
"""Focused tests for manifested checkpoint-directory readiness."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from validate_checkpoint_preflight import check_checkpoint_directory


def manifest(directory: Path, *, enabled: bool = True) -> dict:
    return {
        "case_id": "checkpoint-preflight-test",
        "checkpoint_runtime": {"enabled": enabled},
        "paths": {"checkpoint_directory": str(directory)},
    }


class CheckpointPreflightTests(unittest.TestCase):
    def test_enabled_directory_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            with self.assertRaisesRegex(FileNotFoundError, "is absent"):
                check_checkpoint_directory(manifest(missing))

    def test_enabled_directory_must_be_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "checkpoints"
            directory.mkdir()
            (directory / "stale.nc4").write_bytes(b"stale")
            with self.assertRaisesRegex(ValueError, "is not empty"):
                check_checkpoint_directory(manifest(directory))

    def test_enabled_directory_must_be_writable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "checkpoints"
            directory.mkdir(mode=0o500)
            try:
                with self.assertRaisesRegex(PermissionError, "is not writable"):
                    check_checkpoint_directory(manifest(directory))
            finally:
                os.chmod(directory, 0o700)

    def test_enabled_empty_writable_directory_passes_and_remains_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "checkpoints"
            directory.mkdir()
            result = check_checkpoint_directory(manifest(directory))
            self.assertEqual(result["checkpoint_runtime"], "enabled_ready")
            self.assertEqual(list(directory.iterdir()), [])

    def test_disabled_runtime_is_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            result = check_checkpoint_directory(manifest(missing, enabled=False))
            self.assertEqual(
                result["checkpoint_runtime"], "disabled_not_applicable"
            )


if __name__ == "__main__":
    unittest.main()
