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
            f["BrCDryAOD527.1nm"] = np.full((1, 2, 1, 1), dry)
            f["AODHyg527.1nm_DBRCPOA"] = np.full((1, 2, 1, 1), parent)
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


if __name__ == "__main__":
    unittest.main()
