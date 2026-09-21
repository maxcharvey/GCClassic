import unittest
import numpy as np
from audit_fire_output import REQUIRED
from audit_qfed_pair import compare


class QfedPairTests(unittest.TestCase):
    def fixture(self):
        off = {k: np.ones((3, 2, 2)) for k in REQUIRED}
        for s in ('FSOAP', 'DBRCPOA', 'NPBRCPOA', 'PBRCPOA'):
            off[f'Emis{s}_Fire'][:] = 0
        on = {k: v.copy() for k, v in off.items()}
        for s in ('OCPI', 'OCPO'):
            on[f'Emis{s}_Fire'] *= .5
        on['EmisNPBRCPOA_Fire'][:] = .75
        on['EmisPBRCPOA_Fire'][:] = .25
        return off, on

    def test_partition_passes(self):
        self.assertEqual(compare(*self.fixture())[0], [])

    def test_each_contract_failure(self):
        for kind in ('missing', 'shape', 'co', 'oc', 'off_proxy', 'nonfinite', 'empty'):
            off, on = self.fixture()
            if kind == 'missing':
                del off['EmisCO_Fire']
            elif kind == 'shape':
                on['EmisCO_Fire'] = np.ones((2, 2))
            elif kind == 'co':
                on['EmisCO_Fire'] *= 2
            elif kind == 'oc':
                on['EmisOCPI_Fire'] *= 2
            elif kind == 'off_proxy':
                off['EmisFSOAP_Fire'][:] = 1
            elif kind == 'nonfinite':
                off['EmisCO_Fire'][0] = np.nan
            elif kind == 'empty':
                off = {k: np.empty((0, 0, 0)) for k in REQUIRED}
                on = {k: v.copy() for k, v in off.items()}
            with self.subTest(kind=kind):
                self.assertTrue(compare(off, on)[0])


if __name__ == '__main__':
    unittest.main()
