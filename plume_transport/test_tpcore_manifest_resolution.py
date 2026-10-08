#!/usr/bin/env python3
"""Regression tests for full-validator child-manifest resolution."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from manifest_utils import sha256
from validate_tpcore import TAGS, load_validation_manifest


class TpcoreManifestResolutionTests(unittest.TestCase):
    def test_reviewed_parent_is_resolved_before_full_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent.yml"
            parent.write_text(
                yaml.safe_dump(
                    {
                        "case_id": "parent",
                        "source": {"tags": list(TAGS), "duration_s": 1200},
                        "paths": {"run_directory": "/parent"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            child = root / "child.yml"
            child.write_text(
                yaml.safe_dump(
                    {
                        "case_id": "child",
                        "parent_manifest": parent.name,
                        "parent_manifest_sha256": sha256(parent),
                        "paths": {"run_directory": "/child"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            resolved = load_validation_manifest(child)

            self.assertEqual(resolved["case_id"], "child")
            self.assertEqual(tuple(resolved["source"]["tags"]), TAGS)
            self.assertEqual(resolved["paths"]["run_directory"], "/child")

    def test_parent_hash_mismatch_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent.yml"
            parent.write_text(
                yaml.safe_dump({"source": {"tags": list(TAGS)}}),
                encoding="utf-8",
            )
            child = root / "child.yml"
            child.write_text(
                yaml.safe_dump(
                    {
                        "parent_manifest": parent.name,
                        "parent_manifest_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "parent manifest hash differs"):
                load_validation_manifest(child)


if __name__ == "__main__":
    unittest.main()
