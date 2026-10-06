"""Independent selected-date, timezone-phase and prepared-GFAS shape oracle.

Reproduce categorical spherical-area timezone remap, floor/range/fallback
clock policy and the configured monthly timezone selection. Compare native
FINN CO with complete hourly diagnostics and GFAS normalized layer weights.
This verifies installed prepared profile transfer, not producer/height physics.
"""
from pathlib import Path
import argparse, json, re
import netCDF4 as nc
import numpy as np
import yaml
from audit_finn_daily_source import AVOGADRO, ORACLE_GATE, edges, overlaps
from test_fire_templates import selected_block


def maps(d, lat, lon):
    assert np.all(np.diff(d['lat'][:]) > 0) and np.all(np.diff(d['lon'][:]) > 0)
    y = overlaps(edges(d['lat'][:], True), np.r_[-90., np.arange(-89., 90., 2.), 90.], True)
    x = overlaps(edges(d['lon'][:]), np.r_[lon-1.25, lon[-1]+1.25])
    return y, x


def remap(raw, y, x):
    return (x @ (y @ raw).T).T


def clock_offsets(path, month, lat, lon):
    with nc.Dataset(path) as d:
        assert d['UTC_OFFSET'].dimensions == ('time', 'lat', 'lon')
        assert d['UTC_OFFSET'].units in ('minutes', 'hours')
        times = nc.num2date(d['time'][:], d['time'].units)
        ids = [i for i, t in enumerate(times) if t.year == 2017 and t.month == month and t.day == 1 and t.hour == 0]
        assert len(ids) == 1
        raw = np.asarray(np.ma.filled(d['UTC_OFFSET'][ids[0]], -1e36), dtype=np.float64)
        # The categorical selector is discontinuous at ties. Preserve the
        # production SP coordinate/fraction rounding policy while integrating
        # the overlaps independently in this oracle.
        source_y = np.asarray(np.sin(np.deg2rad(edges(d['lat'][:], True))), dtype=np.float32).astype(np.float64)
        target_y = np.asarray(np.sin(np.deg2rad(np.r_[-90., np.arange(-89., 90., 2.), 90.])), dtype=np.float32).astype(np.float64)
        y = overlaps(source_y, target_y)
        x = overlaps(np.asarray(edges(d['lon'][:]), dtype=np.float32).astype(np.float64), np.r_[lon-1.25, lon[-1]+1.25])
        # HEMCO's unique-index order is first appearance (longitude varies first).
        flat = raw.ravel(); values, indices = np.unique(flat, return_index=True)
        values = values[np.argsort(indices)]
        maximum = np.zeros((len(lat), len(lon)))
        selected = np.zeros_like(maximum)
        for value in values:
            horizontal = (x @ (raw == value).astype(np.float64).T).T.astype(np.float32).astype(np.float64)
            fraction = (y @ horizontal).astype(np.float32).astype(np.float64)
            use = fraction > maximum
            selected[use] = value; maximum[use] = fraction[use]
        floored = np.floor(selected)
        valid = (floored >= -12)&(floored <= 13)
        default = np.broadcast_to(np.floor((lon+180.)/15.)-12., selected.shape)
        offset = np.where(valid, floored, default).astype(np.int64)
        return offset, {'input_units': d['UTC_OFFSET'].units, 'selected_month': month,
            'file_slice_index': ids[0], 'longitude_fallback_cells': int((~valid).sum()),
            'unique_native_categories': len(values)}


def audit(run):
    config = (run/'HEMCO_Config.rc').read_text()
    assert re.search(r'^DiagnFreq:\s+00000000\s+010000\s*$', config, re.M)
    timestamp = re.search(r'^DiagnTimeStamp:\s+(\w+)', config, re.M)
    assert timestamp is None or timestamp[1].lower() == 'start'
    assert not re.search(r'EmisScale_', config)
    assert re.search(r'^165\s+FINNv25_Inject\s*:\s*on\s', config, re.M)
    assert re.search(r'FINNV25_BRC_HARMONIZED_SENSITIVITY\s*:\s*true', config)
    rows = selected_block(config, 'FINNv25', {'FINNv25_Inject': True,
        'FINNV25_BRC_HARMONIZED_SENSITIVITY': True})
    co = next(r for r in rows if r[8] == 'CO'); assert co[9] == '75' and co[5] == 'RF'
    gfas = next(line.split() for line in config.splitlines() if line.startswith('165 FINNV25_GFAS_REFERENCE '))
    assert gfas[5] in ('EFY', 'RFY') and gfas[9] == '-'
    # Archived midnight controls retain EFY; corrected daily-mean access uses RFY.
    tzrow = re.search(r'^\*\s+TIMEZONES\s+(\S+)\s+UTC_OFFSET\s+2017/1-12/1/0\s+C\s+xy\s+count\s+\*\s+-', config, re.M)
    assert tzrow
    root = re.search(r'^ROOT:\s+(\S+)', config, re.M)[1]
    tzpath = run/tzrow[1].replace('$ROOT', root)
    tod = np.asarray([float(v) for v in re.search(r'^75\s+QFED2_TOD\s+(\S+)', config, re.M)[1].split('/')])
    assert len(tod) == 24 and abs(tod.mean()-1.) < 1e-12
    mw = yaml.safe_load((run/'species_database.yml').read_text())['CO']['MW_g']
    cfg = yaml.load((run/'geoschem_config.yml').read_text(), Loader=yaml.BaseLoader)['simulation']
    def date(parts): return ''.join([f'{int(parts[0],10):08d}', f'{int(parts[1],10):06d}'])
    start, end = date(cfg['start_date']), date(cfg['end_date'])
    import datetime as dt
    first = dt.datetime.strptime(start, '%Y%m%d%H%M%S')
    if first.hour != 0: assert gfas[5] == 'RFY'
    finish = dt.datetime.strptime(end, '%Y%m%d%H%M%S')
    assert first.minute == first.second == finish.minute == finish.second == 0
    expected_stamps = []
    while first < finish:
        expected_stamps.append(first.strftime('%Y%m%d%H%M%S')); first += dt.timedelta(hours=1)
    records, tzcache, basecache, gcache = {}, {}, {}, {}
    observations = []
    for p in sorted((run/'OutputDir').glob('HEMCO_diagnostics*.nc')):
        with nc.Dataset(p) as d:
            assert len(d['time']) == 1
            stamp = nc.num2date(d['time'][0], d['time'].units)
            key = stamp.strftime('%Y%m%d%H%M%S'); assert key not in records
            day, month, hour = stamp.strftime('%Y%m%d'), stamp.month, stamp.hour
            assert key in expected_stamps
            lat, lon, area = np.asarray(d['lat'][:]), np.asarray(d['lon'][:]), np.asarray(d['AREA'][:], dtype=np.float64)
            assert np.array_equal(lat, np.r_[-89.5, np.arange(-88., 89., 2.), 89.5])
            assert np.array_equal(lon, np.arange(-180., 180., 2.5))
            assert d['FINNProfileSource_CO'].units == 'kg/m2/s'
            actual = np.asarray(d['FINNProfileSource_CO'][0], dtype=np.float64)
            fall = np.asarray(d['FINNProfileFallback_CO'][0], dtype=np.float64)
            layer = np.asarray(d['EmisCO_Fire'][0], dtype=np.float64)
        if month not in tzcache: tzcache[month] = clock_offsets(tzpath, month, lat, lon)
        offset, tzinfo = tzcache[month]
        if day not in basecache:
            with nc.Dataset(run/co[2].replace('$YYYY', day[:4])) as d:
                assert d[co[3]].units == 'molecules/cm^2/s'
                ids = np.flatnonzero(np.asarray(d['date'][:]) == int(day)); assert len(ids) == 1
                raw = np.asarray(np.ma.filled(d[co[3]][ids[0]], 0), dtype=np.float64)
                y, x = maps(d, lat, lon)
                basecache[day] = remap(raw, y, x)*mw*1e-3/AVOGADRO*1e4
        expected = basecache[day]*tod[(hour+offset)%24]
        den = float(np.sum(expected*area)); assert den > 0
        error = float(np.sum(np.abs(actual-expected)*area))/den
        assert np.all(actual[expected == 0] == 0)
        gpath = gfas[2].replace('$YYYY', day[:4]).replace('$MM', day[4:6]).replace('$DD', day[6:8])
        if day not in gcache:
            with nc.Dataset(run/gpath) as d:
                assert nc.num2date(d['time'][0], d['time'].units).strftime('%Y%m%d') == day
                assert d['cofire_3d'].units == 'kg/m2/s' and len(d['lev']) == 36
                assert d['cofire_3d'].dimensions == ('time', 'lev', 'lat', 'lon')
                assert len(d['time']) == 1 and np.array_equal(d['lev'][:], np.arange(1.,37.))
                y, x = maps(d, lat, lon)
                ref = np.zeros((47, len(lat), len(lon)))
                for lev in range(36):
                    raw = np.asarray(np.ma.filled(d['cofire_3d'][0,lev], 0), dtype=np.float64)
                    assert np.all(np.isfinite(raw)) and np.all(raw >= 0)
                    ref[lev] = remap(raw, y, x)
                total = ref.sum(axis=0)
                weights = np.divide(ref, total, out=np.zeros_like(ref), where=total > 0)
                gcache[day] = total, weights
        total, weights = gcache[day]
        supported = (actual > 0)&(total > 0)
        unsupported = (actual > 0)&(total == 0)
        assert np.all(fall[supported] == 0) and np.array_equal(fall[unsupported], actual[unsupported])
        allocated = np.divide(layer, actual, out=np.zeros_like(layer), where=actual > 0)
        shape_den = float(np.sum(actual[supported]*area[supported]))
        shape_error = float(np.sum(np.abs(allocated[:,supported]-weights[:,supported])*actual[supported]*area[supported]))/shape_den if shape_den else 0.
        observations.append((day, actual, tod[(hour+offset)%24], area, den))
        records[key] = {'source_spatial_mass_L1_relative': error, 'GFAS_supported_shape_mass_L1_relative': shape_error,
            'CO_source_kg_s': float(np.sum(actual*area)), 'oracle_CO_source_kg_s': den,
            'supported_positive_cells': int(supported.sum()), 'unsupported_positive_cells': int(unsupported.sum()),
            'timezone': tzinfo, 'GFAS_file': str((run/gpath).resolve()),
            'status': 'PASS' if max(error, shape_error) <= ORACLE_GATE else 'FAIL'}
    assert sorted(records) == expected_stamps, (sorted(records), expected_stamps)
    log = (run/'GC.log').read_text()
    for day in basecache: assert 'GFAS-smoke-'+day+'.nc' in log
    stale = {}
    if len(basecache) > 1:
        for retained_day, base in sorted(basecache.items()):
            num = sum(float(np.sum(np.abs(a-base*factor)*area)) for _, a, factor, area, _ in observations)
            den = sum(d for _, _, _, _, d in observations)
            stale[retained_day] = num/den
            assert stale[retained_day] > ORACLE_GATE, ('stale-date alternative not discriminated', retained_day)
    return {'stale_date_alternative_spatial_mass_L1': stale, 'status': 'PASS' if all(v['status'] == 'PASS' for v in records.values()) else 'FAIL',
        'records': records, 'diurnal_mean': float(tod.mean()),
        'scope': 'Installed selected-date/phase/profile fidelity only; prepared GFAS producer/datum and atmospheric skill remain unqualified.'}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('runs', nargs='+', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args(); assert not args.output.exists()
    result = {'status': 'FAIL', 'oracle_gate': ORACLE_GATE, 'runs': {r.name: audit(r) for r in args.runs}}
    result['status'] = 'PASS' if all(r['status'] == 'PASS' for r in result['runs'].values()) else 'FAIL'
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(result['status']); raise SystemExit(0 if result['status'] == 'PASS' else 1)
