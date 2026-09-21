from datetime import datetime
import tempfile
import unittest

import h5py
import numpy as np

from audit_brc_day import field, snapshot_time


class DayFieldsTests(unittest.TestCase):
    def test_time_origin_and_offset(self):
        with tempfile.TemporaryFile() as stream, h5py.File(stream, 'w') as nc:
            nc['time'] = [360.]
            nc['time'].attrs['units'] = 'minutes since 2019-07-01 00:00:00'
            self.assertEqual(snapshot_time(nc), datetime(2019, 7, 1, 6))
            nc['time'][0] = np.nan
            with self.assertRaises(ValueError):
                snapshot_time(nc)

    def test_missing_empty_fill_and_nonfinite_fail(self):
        with tempfile.TemporaryFile() as stream, h5py.File(stream, 'w') as nc:
            nc['ok'] = [1.]
            nc['empty'] = []
            nc['bad'] = [np.inf]
            nc['fill'] = [-999.]
            nc['fill'].attrs['_FillValue'] = -999.
            self.assertEqual(field(nc, 'ok')[0], 1.)
            for name in ('missing', 'empty', 'bad', 'fill'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    field(nc, name)


if __name__ == '__main__':
    unittest.main()
