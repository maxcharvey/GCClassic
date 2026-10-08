#!/usr/bin/env python3
"""Regression test for layered source-validation manifests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from manifest_utils import sha256
from validate_source import load_source_manifest


class SourceManifestResolutionTests(unittest.TestCase):
    def test_source_validator_resolves_inherited_restart_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent.yml"
            parent.write_text(
                yaml.safe_dump(
                    {
                        "restart": {"seed": "/frozen/restart.nc4"},
                        "source": {"tags": ["PLUME_SFC"]},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            child = root / "child.yml"
            child.write_text(
                yaml.safe_dump(
                    {
                        "parent_manifest": parent.name,
                        "parent_manifest_sha256": sha256(parent),
                        "case_id": "fresh-child",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            manifest = load_source_manifest(child)

            self.assertEqual(manifest["case_id"], "fresh-child")
            self.assertEqual(manifest["restart"]["seed"], "/frozen/restart.nc4")
            self.assertEqual(manifest["source"]["tags"], ["PLUME_SFC"])


if __name__ == "__main__":
    unittest.main()
