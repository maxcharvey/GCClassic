import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from audit_fire_output import audit


class FireOutputTests(unittest.TestCase):
    def make_file(self, bad=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "HEMCOdiag.nc"
        shape = (3, 2, 2)
        co = np.full(shape, 1e-10)
        pb = np.full(shape, 2e-10)
        bc = np.full(shape, 1e-10)
        with h5py.File(path, "w") as f:
            vals = {
                "EmisCO_Fire": co, "EmisBCPI_Fire": bc, "EmisBCPO_Fire": bc,
                "EmisOCPI_Fire": np.full(shape, 7e-10),
                "EmisOCPO_Fire": np.full(shape, 1e-10), "EmisFSOAP_Fire": .013 * co,
                "EmisNPBRCPOA_Fire": 3 * pb, "EmisPBRCPOA_Fire": pb,
                "EmisDBRCPOA_Fire": 4 * (bc + bc),
            }
            vals["EmisFSOAP_Fire"][0] += 0.0 if not bad else 1e-11
            for name, value in vals.items():
                f[name] = value
                f[name.replace("_Fire", "_FireColumn")] = value.sum(axis=0)
        return path

    def test_gfas_closures(self):
        self.assertEqual(audit(self.make_file())['status'], 'PASS')

    def test_gfed_surface_only_closures(self):
        path = self.make_file()
        with h5py.File(path, "a") as f:
            for name in list(f):
                if name.endswith("_Fire"):
                    f[name][1:] = 0
                    f[name.replace("_Fire", "_FireColumn")][...] = f[name][...].sum(axis=0)
        self.assertEqual(audit(path, "gfed")["status"], "PASS")
        self.assertTrue(audit(path, "gfed")["scope"].startswith("GFED "))
        self.assertEqual(audit(path, "gfas")["status"], "FAIL")

    def test_empty_gfed_fails(self):
        path = self.make_file()
        with h5py.File(path, "a") as f:
            for field in f.values():
                field[...] = 0
        self.assertEqual(audit(path, "gfed")["status"], "FAIL")

    def test_bad_fsoap_fails(self):
        self.assertEqual(audit(self.make_file(True))['status'], 'FAIL')

    def test_bad_npb_column_fails(self):
        path = self.make_file()
        with h5py.File(path, "a") as f:
            f["EmisNPBRCPOA_FireColumn"][0, 0] *= 1.1
        self.assertEqual(audit(path)['status'], 'FAIL')

    def test_negative_column_fails(self):
        path = self.make_file()
        with h5py.File(path, "a") as f:
            f["EmisCO_FireColumn"][0, 0] = -1e-10
        self.assertEqual(audit(path)['status'], 'FAIL')

    def test_rank_and_shape_contracts_fail(self):
        path = self.make_file()
        with h5py.File(path, "a") as f:
            del f["EmisCO_Fire"]
            f["EmisCO_Fire"] = np.ones((2, 2))
        self.assertEqual(audit(path)['status'], 'FAIL')

    def test_nonfinite_fails(self):
        path = self.make_file()
        with h5py.File(path, "a") as f:
            f["EmisCO_Fire"][1, 0, 0] = np.nan
        self.assertEqual(audit(path)['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
