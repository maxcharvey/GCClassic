"""Independent daily FINN selection/remapping oracle for hourly hybrid outputs.

Integrate all 24 hourly source records for a complete UTC day, independently
select native input by its date variable, conservatively remap spherical cell
overlaps and apply recorded species MW/proxy factors. Daily diurnal mean is1.
The remapping oracle has a separate explicit 5e-5 spatial L1 gate; the actual
source/layer closure gate remains2e-6. This script never edits model outputs.
"""
from pathlib import Path
import argparse, datetime as dt, json, re, sys
import netCDF4 as nc
import numpy as np
from scipy.sparse import csr_matrix
import yaml
from test_fire_templates import selected_block

ORACLE_GATE = 5e-5
AVOGADRO = 6.022140857e23


def edges(mid, latitude=False):
    mid = np.asarray(mid, dtype=np.float64)
    edge = np.empty(len(mid)+1)
    edge[0] = mid[0]-(mid[1]-mid[0])/2
    if latitude:
        edge[0] = max(-90., edge[0])
    for k, centre in enumerate(mid):
        edge[k+1] = 2*centre-edge[k]
    return edge


def overlaps(source, target, latitude=False):
    rows, cols, values = [], [], []
    for i, (lo, hi) in enumerate(zip(target[:-1], target[1:])):
        for shift in ([0] if latitude else [-360, 0, 360]):
            left = np.maximum(lo, source[:-1]+shift)
            right = np.minimum(hi, source[1:]+shift)
            ids = np.flatnonzero(right > left)
            if latitude:
                w = (np.sin(np.deg2rad(right[ids]))-np.sin(np.deg2rad(left[ids])))
                w /= np.sin(np.deg2rad(hi))-np.sin(np.deg2rad(lo))
            else:
                w = (right[ids]-left[ids])/(hi-lo)
            rows.extend([i]*len(ids)); cols.extend(ids); values.extend(w)
    return csr_matrix((values, (rows, cols)), shape=(len(target)-1, len(source)-1))


def audit(run):
    text = (run/'HEMCO_Config.rc').read_text()
    rows = selected_block(text, 'FINNv25', {
        'FINNv25_Inject': True, 'FINNV25_BRC_HARMONIZED_SENSITIVITY': True})
    assert re.search(r'^165\s+FINNv25_Inject\s*:\s*on\s', text, re.M)
    assert re.search(r'FINNV25_BRC_HARMONIZED_SENSITIVITY\s*:\s*true', text)
    assert re.search(r'^DiagnFreq:\s+00000000\s+010000\s*$', text, re.M)
    timestamp = re.search(r'^DiagnTimeStamp:\s+(\w+)', text, re.M)
    assert timestamp is None or timestamp[1].lower() == 'start'
    config = yaml.load((run/'geoschem_config.yml').read_text(), Loader=yaml.BaseLoader)['simulation']
    def date(parts):
        return dt.datetime.strptime(f'{int(parts[0],10):08d}{int(parts[1],10):06d}', '%Y%m%d%H%M%S')
    start, end = date(config['start_date']), date(config['end_date'])
    first = start.replace(hour=0, minute=0, second=0)
    if first < start: first += dt.timedelta(days=1)
    expected_days = []
    while first+dt.timedelta(days=1) <= end:
        expected_days.append(first.strftime('%Y%m%d'))
        first += dt.timedelta(days=1)
    assert expected_days, 'No complete UTC day configured'
    assert not re.search(r"EmisScale_", text), "Universal species scaling not implemented by oracle"
    scales = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) == 9 and f[0].isdigit() and f[4] == '-' and f[6] == 'xy':
            try: scales[f[0]] = np.asarray([float(x) for x in f[2].split('/')])
            except ValueError: pass
    # Source row pFe inherits preceding SO2 data; data-unit conversion uses
    # the parent file's species before the SO2-to-Fe mass-ratio scale.
    species = yaml.safe_load((run/'species_database.yml').read_text())
    hourly = {}
    for p in sorted((run/'OutputDir').glob('HEMCO_diagnostics*.nc')):
        with nc.Dataset(p) as d:
            dates = nc.num2date(d['time'][:], d['time'].units)
            for k, stamp in enumerate(dates):
                assert stamp.minute == stamp.second == 0, (p, stamp)
                key = stamp.strftime('%Y%m%d')
                hourly.setdefault(key, []).append((p, k, stamp.hour))
    result = {}
    for day in expected_days:
        records = hourly.get(day, [])
        assert len(records) == 24 and sorted(v[2] for v in records) == list(range(24)), (day, len(records))
        actual = {}
        for path, k, _ in records:
            with nc.Dataset(path) as d:
                for row in rows:
                    sp = row[8]
                    assert d['FINNProfileSource_'+sp].units == 'kg/m2/s'
                    a = np.asarray(d['FINNProfileSource_'+sp][k], dtype=np.float64)
                    actual[sp] = actual.get(sp, np.zeros_like(a))+a/24
                lat, lon = np.asarray(d['lat'][:]), np.asarray(d['lon'][:])
                area = np.asarray(d['AREA'][:], dtype=np.float64)
        assert np.array_equal(lat, np.r_[-89.5, np.arange(-88., 89., 2.), 89.5])
        assert np.array_equal(lon, np.arange(-180., 180., 2.5))
        target_lat = np.r_[-90., np.arange(-89., 90., 2.), 90.]
        target_lon = np.r_[lon-1.25, lon[-1]+1.25]
        cache, metrics = {}, {}
        inherited = None
        for row in rows:
            sp = row[8]
            path, var, mw = row[2], row[3], float(species[sp]['MW_g'])
            if path == '-':
                path, var, mw = inherited
            elif '.nc' in path:
                inherited = (path, var, mw)
            factor = 1.
            for scale in row[9].split('/'):
                if scale == '-': continue
                coeff = scales[scale]
                if scale == '75':
                    assert len(coeff) == 24 and abs(coeff.mean()-1) < 1e-12
                    continue
                assert len(coeff) == 1, (sp, scale)
                factor *= coeff[0]
            if path == '0':
                expected = np.zeros_like(actual[sp])
            else:
                path = path.replace('$YYYY', day[:4])
                key = (path, var)
                if key not in cache:
                    with nc.Dataset(run/path) as d:
                        assert d[var].dimensions == ('time', 'lat', 'lon'), (path, var, d[var].dimensions)
                        assert d[var].units == 'molecules/cm^2/s', (path, var, d[var].units)
                        ids = np.flatnonzero(np.asarray(d['date'][:]) == int(day))
                        assert len(ids) == 1, (path, day)
                        raw = np.asarray(np.ma.filled(d[var][ids[0]], 0), dtype=np.float64)
                        assert np.all(np.isfinite(raw)) and np.all(raw >= 0)
                        y = overlaps(edges(d['lat'][:], True), target_lat, True)
                        x = overlaps(edges(d['lon'][:]), target_lon)
                        cache[key] = (x @ (y @ raw).T).T
                expected = cache[key]*mw*1e-3/AVOGADRO*1e4*factor
            denominator = float(np.sum(np.abs(expected)*area))
            difference = float(np.sum(np.abs(actual[sp]-expected)*area))
            error = difference/denominator if denominator else 0.
            if not denominator: assert np.all(actual[sp] == 0), sp
            metrics[sp] = {'spatial_mass_L1_relative': error,
                           'actual_kg_s': float(np.sum(actual[sp]*area)),
                           'oracle_kg_s': float(np.sum(expected*area)),
                           'status': 'PASS' if error <= ORACLE_GATE else 'FAIL'}
        result[day] = metrics
    assert result, 'No complete24-hour source window'
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run_dirs', nargs='+', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    assert not args.output.exists(), args.output
    report = {'status': 'FAIL', 'oracle_gate': ORACLE_GATE, 'runs': {}}
    for run in args.run_dirs:
        report['runs'][run.name] = audit(run)
    report['status'] = 'PASS' if all(v['status'] == 'PASS'
        for r in report['runs'].values() for d in r.values() for v in d.values()) else 'FAIL'
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(report['status'], flush=True)
    sys.exit(0 if report['status'] == 'PASS' else 1)
