"""Independent native daily CO oracle for the May–September2018 replacement season.

All39 species are independently checked in the bounded daily suite; this
seasonal oracle additionally verifies actual monthly CO against every daily
native source slice, preserving the hourly diurnal factor's daily mean of1.
"""
from pathlib import Path
import argparse, calendar, json, re
import netCDF4 as nc
import numpy as np
import yaml
from audit_finn_daily_source import AVOGADRO, ORACLE_GATE, edges, overlaps
from test_fire_templates import selected_block


def audit(run):
    text = (run/'HEMCO_Config.rc').read_text()
    assert re.search(r'^DiagnFreq:\s+Monthly\s*$', text, re.M)
    assert not re.search(r'EmisScale_', text)
    timestamp = re.search(r'^DiagnTimeStamp:\s+(\w+)', text, re.M)
    assert timestamp is None or timestamp[1].lower() == 'start'
    cfg = yaml.load((run/'geoschem_config.yml').read_text(), Loader=yaml.BaseLoader)['simulation']
    assert [int(v, 10) for v in cfg['start_date']] == [20180501, 0]
    assert [int(v, 10) for v in cfg['end_date']] == [20181001, 0]
    assert re.search(r'^165\s+FINNv25_Inject\s*:\s*on\s', text, re.M)
    assert re.search(r'FINNV25_BRC_HARMONIZED_SENSITIVITY\s*:\s*true', text)
    tz = re.search(r'^\*\s+TIMEZONES\s+(\S+)\s+UTC_OFFSET\s+2017/1-12/1/0\s+C\s+xy\s+count', text, re.M)
    assert tz and '$YYYY' not in tz[1] and '$MM' not in tz[1] and '$DD' not in tz[1], 'Fixed monthly TIMEZONES configuration required'
    root_data = re.search(r'^ROOT:\s+(\S+)', text, re.M)[1]
    with nc.Dataset(run/tz[1].replace('$ROOT', root_data.rstrip('/'))) as timezone:
        assert timezone['UTC_OFFSET'].units == 'hours'
        assert timezone['UTC_OFFSET'].dimensions == ('time', 'lat', 'lon')
        assert len(timezone.dimensions['time']) == 12
        dates_tz = nc.num2date(timezone['time'][:], timezone['time'].units)
        assert [(t.year, t.month, t.day, t.hour) for t in dates_tz] == [(2017, m, 1, 0) for m in range(1, 13)]

    row = next(r for r in selected_block(text, 'FINNv25', {
        'FINNv25_Inject': True, 'FINNV25_BRC_HARMONIZED_SENSITIVITY': True}) if r[8] == 'CO')
    assert row[5] == 'RF' and row[9] == '75', row
    tod = re.search(r'^75\s+QFED2_TOD\s+(\S+)', text, re.M)[1]
    assert abs(np.mean([float(x) for x in tod.split('/')])-1.) < 1e-12
    mw = yaml.safe_load((run/'species_database.yml').read_text())['CO']['MW_g']
    result = {'status': 'PASS', 'oracle_gate': ORACLE_GATE, 'species': 'CO',
              'scope': 'Native daily selection and monthly mass/spatial pattern; no atmospheric validation.', 'months': {}}
    with nc.Dataset(run/row[2].replace('$YYYY', '2018')) as source:
        var = source[row[3]]
        assert var.units == 'molecules/cm^2/s' and var.dimensions == ('time', 'lat', 'lon')
        dates = np.asarray(source['date'][:])
        maps = None
        for month in range(5, 10):
            p = run/'OutputDir'/f'HEMCO_diagnostics.2018{month:02d}010000.nc'
            with nc.Dataset(p) as d:
                assert d['FINNProfileSource_CO'].units == 'kg/m2/s'
                assert len(d['time']) == 1
                stamp = nc.num2date(d['time'][0], d['time'].units)
                assert stamp.strftime('%Y%m%d%H%M%S') == f'2018{month:02d}01000000'
                lat, lon, area = np.asarray(d['lat'][:]), np.asarray(d['lon'][:]), np.asarray(d['AREA'][:], dtype=np.float64)
                assert np.array_equal(lat, np.r_[-89.5, np.arange(-88., 89., 2.), 89.5])
                assert np.array_equal(lon, np.arange(-180., 180., 2.5))
                actual = np.asarray(d['FINNProfileSource_CO'][0], dtype=np.float64)
                assert np.all(np.isfinite(actual)) and np.all(actual >= 0)
            if maps is None:
                y = overlaps(edges(source['lat'][:], True), np.r_[-90., np.arange(-89., 90., 2.), 90.], True)
                x = overlaps(edges(source['lon'][:]), np.r_[lon-1.25, lon[-1]+1.25])
                maps = y, x
            count = calendar.monthrange(2018, month)[1]
            expected = np.zeros_like(actual)
            for day in range(1, count+1):
                ids = np.flatnonzero(dates == 20180000+month*100+day)
                assert len(ids) == 1
                raw = np.asarray(np.ma.filled(var[ids[0]], 0), dtype=np.float64)
                assert np.all(np.isfinite(raw)) and np.all(raw >= 0)
                expected += (x @ (y @ raw).T).T/count
            expected *= mw*1e-3/AVOGADRO*1e4
            den = float(np.sum(np.abs(expected)*area))
            error = float(np.sum(np.abs(actual-expected)*area))/den
            region = (lat[:,None] >= 30)&(lat[:,None] <= 55)&(lon[None,:] >= -130)&(lon[None,:] <= -100)
            result['months'][str(month)] = {'daily_slices': count, 'spatial_mass_L1_relative': error,
                'global_CO_kg_s': float(np.sum(actual*area)), 'oracle_global_CO_kg_s': float(np.sum(expected*area)),
                'western_US_CO_kg_s': float(np.sum(actual*area*region)),
                'oracle_western_US_CO_kg_s': float(np.sum(expected*area*region)),
                'status': 'PASS' if error <= ORACLE_GATE else 'FAIL'}
            print(month, error, flush=True)
    if any(v['status'] != 'PASS' for v in result['months'].values()): result['status'] = 'FAIL'
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    assert not args.output.exists()
    report = audit(args.run)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    raise SystemExit(0 if report['status'] == 'PASS' else 1)
