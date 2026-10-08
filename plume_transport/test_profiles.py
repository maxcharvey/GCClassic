#!/usr/bin/env python3
"""Small deterministic tests for plume profile construction."""

from __future__ import annotations

import argparse
from pathlib import Path
import unittest

import numpy as np

from generate_source import TAGS, build_profiles
from manifest_utils import load_manifest


MANIFEST: Path | None = None


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if MANIFEST is None:
            raise RuntimeError("manifest path was not initialized")
        cls.manifest = load_manifest(MANIFEST)
        cls.profiles, cls.metadata = build_profiles(cls.manifest)

    def test_all_profiles_are_normalized_and_nonnegative(self) -> None:
        for tag in TAGS:
            profile = self.profiles[tag]
            self.assertTrue(np.all(np.isfinite(profile)), tag)
            self.assertTrue(np.all(profile >= 0.0), tag)
            self.assertAlmostEqual(float(profile.sum(dtype=np.float64)), 1.0, places=14)

    def test_surface_and_fixed_level_are_exact(self) -> None:
        self.assertEqual(int(np.count_nonzero(self.profiles["PLUME_SFC"])), 1)
        self.assertEqual(int(np.argmax(self.profiles["PLUME_SFC"])) + 1, 1)
        self.assertEqual(int(np.count_nonzero(self.profiles["PLUME_LEV"])), 1)
        self.assertEqual(int(np.argmax(self.profiles["PLUME_LEV"])) + 1, 20)

    def test_pbl_fraction_and_free_troposphere_bounds(self) -> None:
        self.assertEqual(self.metadata["pbl_top_layer_one_based"], 9)
        self.assertEqual(self.metadata["ft_levels_one_based"], [10, 19])
        pbl = self.profiles["PLUME_PBL"]
        mix = self.profiles["PLUME_6535"]
        self.assertTrue(np.all(pbl[9:] == 0.0))
        self.assertAlmostEqual(float(mix[:9].sum(dtype=np.float64)), 0.65, places=14)
        self.assertAlmostEqual(float(mix[9:19].sum(dtype=np.float64)), 0.35, places=14)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args, remaining = parser.parse_known_args()
    MANIFEST = args.manifest
    unittest.main(argv=[__file__, *remaining])
