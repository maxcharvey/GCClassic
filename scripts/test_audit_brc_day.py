from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

from audit_brc_day import audit, field, snapshot_time, REQUIRED_GROUPS


class DayFieldsTests(unittest.TestCase):
    def test_complete_day_with_expanded_wavelength_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'day' / 'OutputDir'
            output.mkdir(parents=True)
            (root / 'matrix_manifest.json').write_text(json.dumps({'cases': [{
                'run_id': 'day', 'hours': 24, 'start': '2019-07-01T00:00:00Z', 'hashes': {}}]}))
            start = datetime(2019, 7, 1)
            for hour in (6, 12, 18, 24):
                stamp = (start + timedelta(hours=hour)).strftime('%Y%m%d_%H%Mz')
                for collection, names in REQUIRED_GROUPS.items():
                    with h5py.File(output / f'GEOSChem.{collection}.{stamp}.nc4', 'w') as nc:
                        nc['time'] = [hour * 60.]
                        nc['time'].attrs['units'] = 'minutes since 2019-07-01 00:00:00'
                        for name in names:
                            nc[name] = np.ones((1, 2, 2)) * (2 if name.endswith('_PM') else 1)
                        if collection == 'RRTMG':
                            for mask in ('BASE', 'BRC', 'BRCT', 'PM', 'DU'):
                                nc[f'RadAllSkySWTOA_{mask}'] = np.ones((1, 2, 2))
            with patch('audit_brc_day.check_run', side_effect=lambda *args: {'errors': []}):
                self.assertEqual(audit(root)['status'], 'PASS')
                # A HISTORY placeholder must not be mistaken for a netCDF name.
                path = output / 'GEOSChem.RRTMG.20190701_0600z.nc4'
                with h5py.File(path, 'a') as nc:
                    nc.move('RadAOD550nm_DU', 'RadAODWL2_DU')
                report = audit(root)
                self.assertEqual(report['status'], 'FAIL')
                self.assertTrue(any('missing RadAOD550nm_DU' in e for e in report['errors']))
                with h5py.File(path, 'a') as nc:
                    nc.move('RadAODWL2_DU', 'RadAOD550nm_DU')
                    nc['time'][0] = 720.
                report = audit(root)
                self.assertEqual(report['status'], 'FAIL')
                self.assertTrue(any('snapshot times' in e for e in report['errors']))

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
