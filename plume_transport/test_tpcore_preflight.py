#!/usr/bin/env python3
"""Focused tests for the pre-model full TPCORE contract gate."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from validate_tpcore_preflight import run_preflight


class TpcorePreflightTests(unittest.TestCase):
    def test_preflight_uses_full_validator_contract_and_checked_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.yml"
            manifest_path.write_text("case_id: test\n", encoding="utf-8")
            manifest = {
                "case_id": "test",
                "acceptance_contract": "stage1-tpcore-ledger-v1",
                "paths": {"run_directory": str(root)},
            }
            with (
                patch(
                    "validate_tpcore_preflight.load_validation_manifest",
                    return_value=manifest,
                ),
                patch(
                    "validate_tpcore_preflight.validate_operator_and_checkpoint_contract"
                ) as operator_check,
                patch(
                    "validate_tpcore_preflight.acceptance_tolerances",
                    return_value={"a": 1.0},
                ) as tolerance_check,
                patch(
                    "validate_tpcore_preflight.validate_checked_inputs",
                    return_value={"input": "sha256"},
                ) as input_check,
            ):
                result = run_preflight(manifest_path, "prebuild")

            operator_check.assert_called_once_with(manifest)
            tolerance_check.assert_called_once_with(manifest)
            input_check.assert_called_once_with(
                root.resolve(), manifest, require_executable=False
            )
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["phase"], "prebuild")
            self.assertEqual(result["controlled_inputs"], {"input": "sha256"})

    def test_missing_run_directory_is_fatal_before_checked_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing"
            manifest_path = root / "manifest.yml"
            manifest_path.write_text("case_id: test\n", encoding="utf-8")
            manifest = {
                "case_id": "test",
                "acceptance_contract": "stage1-tpcore-ledger-v1",
                "paths": {"run_directory": str(missing)},
            }
            with (
                patch(
                    "validate_tpcore_preflight.load_validation_manifest",
                    return_value=manifest,
                ),
                patch(
                    "validate_tpcore_preflight.validate_operator_and_checkpoint_contract"
                ),
                patch(
                    "validate_tpcore_preflight.acceptance_tolerances",
                    return_value={},
                ),
                patch(
                    "validate_tpcore_preflight.validate_checked_inputs"
                ) as input_check,
            ):
                with self.assertRaisesRegex(FileNotFoundError, "run directory is absent"):
                    run_preflight(manifest_path, "prebuild")
            input_check.assert_not_called()

    def test_postbuild_requires_executable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.yml"
            manifest_path.write_text("case_id: test\n", encoding="utf-8")
            manifest = {
                "case_id": "test",
                "acceptance_contract": "stage1-tpcore-ledger-v1",
                "paths": {"run_directory": str(root)},
            }
            with (
                patch(
                    "validate_tpcore_preflight.load_validation_manifest",
                    return_value=manifest,
                ),
                patch(
                    "validate_tpcore_preflight.validate_operator_and_checkpoint_contract"
                ),
                patch(
                    "validate_tpcore_preflight.acceptance_tolerances",
                    return_value={},
                ),
                patch(
                    "validate_tpcore_preflight.validate_checked_inputs",
                    return_value={},
                ) as input_check,
            ):
                result = run_preflight(manifest_path, "postbuild")
            input_check.assert_called_once_with(
                root.resolve(), manifest, require_executable=True
            )
            self.assertTrue(result["executable_identity_required"])

    def test_unknown_phase_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.yml"
            with self.assertRaisesRegex(ValueError, "prebuild or postbuild"):
                run_preflight(manifest_path, "unknown")


if __name__ == "__main__":
    unittest.main()
