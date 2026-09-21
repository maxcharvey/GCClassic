"""Tiny synthetic fixtures for the read-only smoke-output auditor."""
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from audit_brc_smoke import check_run


class SmokeAuditTests(unittest.TestCase):
    def fixture(self, dry=0.01, parent=0.01):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "OutputDir").mkdir()
        (root / "GC.log").write_text("E N D   O F   G E O S -- C H E M")
        with h5py.File(root / "OutputDir/GEOSChem.Aerosols.test.nc4", "w") as f:
            for wl in ("470nm", "527.1nm", "660nm"):
                f[f"BrCDryAOD{wl}"] = np.full((1, 2, 1, 1), dry)
                f[f"AODHyg{wl}_DBRCPOA"] = np.full((1, 2, 1, 1), parent)
            f["BrCAbsMass"] = np.full((1, 2, 1, 1), 0.1)
            f["BrCTotMass"] = np.full((1, 2, 1, 1), 0.2)
            f["BrCAbsMass"].attrs["units"] = "kgC m-3"
            f["BrCTotMass"].attrs["units"] = "kgC m-3"
        return root

    def test_enabled_nonzero_closure(self):
        self.assertEqual(check_run(self.fixture(), "on")["status"], "PASS")

    def test_disabled_zero_closure(self):
        self.assertEqual(check_run(self.fixture(0, 0), "off")["status"], "PASS")

    def test_interpolation_mismatch_fails(self):
        self.assertEqual(check_run(self.fixture(0.01, 0.012), "on")["status"], "FAIL")

    def test_nan_fails(self):
        self.assertEqual(check_run(self.fixture(np.nan, np.nan), "on")["status"], "FAIL")

    def test_false_zero_enabled_fails(self):
        self.assertEqual(check_run(self.fixture(0, 0), "on")["status"], "FAIL")

    def test_nonzero_disabled_fails(self):
        self.assertEqual(check_run(self.fixture(), "off")["status"], "FAIL")

    def test_disabled_brc_with_rrtmg_nonzero_brc_rad_aod_fails(self):
        root = self.fixture(0, 0)
        with h5py.File(root / "OutputDir/GEOSChem.RRTMG.test.nc4", "w") as f:
            f["RadAOD_BRC"] = np.ones((1, 1, 1))
        self.assertEqual(check_run(root, "off", "on")["status"], "FAIL")

    def test_missing_carbon_field_fails(self):
        root = self.fixture()
        with h5py.File(root / "OutputDir/GEOSChem.Aerosols.test.nc4", "a") as f:
            del f["BrCAbsMass"]
        self.assertEqual(check_run(root, "on")["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
