"""Mechanical month integrity audit; no scientific attribution."""
from pathlib import Path
import json, sys, datetime, hashlib, re
import netCDF4, numpy as np
from workflow_common import ROOT
sys.path.insert(0, str(ROOT / 'analysis_tools'))
from audit_fire_output import audit as fire_audit
from compare_planeflight_profiles import read_log, schedule_points, PRINTED_PRECISION_TOLERANCE
from audit_restart_smoke import FLIGHT, TARGETS, sha

def audit(case):
    errors = []
    files = {}
    ranges = {}
    maxima = {}
    minima = {}

    def check(ok, msg):
        if not ok:
            errors.append(msg)
    freeze = json.loads((ROOT / 'RESTART_GATE_FREEZE_20260922.json').read_text())
    info = freeze['cases'][case.name]
    for n, h in info['configs'][case.name].items():
        check(sha(case / n) == h, 'config/executable changed ' + n)
    check((case / 'model_exit_code.txt').is_file() and (case / 'model_exit_code.txt').read_text().strip() == '0', 'model exit not0')
    log = (case / 'GC.log').read_text(errors='replace')
    check('E N D   O F   G E O S' in log, 'no normal end')
    fallbacks = {n: float(v) for n, v in re.findall('Species\\s+\\d+,\\s*(\\w+): not found in restart, setting to background =\\s*([\\d.Ee+-]+)', log)}
    check(set(fallbacks) == set(info['missing_union']), 'unexpected fallback species')
    for n, v in info['missing_backgrounds'].items():
        check(n in fallbacks and np.isclose(fallbacks[n], v, atol=0, rtol=1e-07), 'wrong background ' + n)
    base = datetime.datetime(2018, 8, 1)
    end = datetime.datetime(2018, 9, 1)
    for coll in info['active_collections']:
        paths = [case / 'Restarts/GEOSChem.Restart.20180901_0000z.nc4'] if coll == 'Restart' else sorted((case / 'OutputDir').glob('GEOSChem.' + coll + '.*.nc4'))
        daily = coll in ['BrCDiagnostics', 'RRTMG']
        check(len(paths) == (31 if daily else 1), 'wrong file count ' + coll)
        intervals = []
        for p in paths:
            if not p.is_file():
                errors.append('missing ' + str(p))
                continue
            files[str(p.relative_to(case))] = sha(p)
            with netCDF4.Dataset(p) as nc:
                t = nc['time']
                check(len(t) == 1, 'wrong time count ' + p.name)
                dt = netCDF4.num2date(t[:], t.units, calendar=getattr(t, 'calendar', 'standard'))
                if coll == 'Restart':
                    check(len(dt) == 1 and str(dt[0]) == '2018-09-01 00:00:00', 'wrong endpoint restart')
                else:
                    check(getattr(nc, 'simulation_start_date_and_time', '') == '2018-08-01 00:00:00z' and getattr(nc, 'simulation_end_date_and_time', '') == '2018-09-01 00:00:00z', 'wrong native run interval ' + p.name)
                    check(any((getattr(v, 'averaging_method', '') == 'time-averaged' for v in nc.variables.values())), 'missing averaging metadata ' + p.name)
                    start = datetime.datetime.strptime(str(dt[0]), '%Y-%m-%d %H:%M:%S')
                    stop = start + datetime.timedelta(days=1) if daily else end
                    intervals.append((str(start), str(stop)))
                    if 'time_bnds' in nc.variables:
                        bd = netCDF4.num2date(nc['time_bnds'][:].reshape(-1), t.units, calendar=getattr(t, 'calendar', 'standard'))
                        check(tuple((str(x) for x in bd)) == (str(start), str(stop)), 'explicit bounds disagree ' + p.name)
                for n, v in nc.variables.items():
                    if not np.issubdtype(v.dtype, np.number):
                        continue
                    vals = np.ma.compressed(v[:])
                    check(vals.size > 0 and np.isfinite(vals).all(), 'nonfinite/all masked ' + p.name + ':' + n)
                    if vals.size and v.ndim >= 2:
                        maxima[n] = max(maxima.get(n, -np.inf), float(np.max(vals)))
                        minima[n] = min(minima.get(n, np.inf), float(np.min(vals)))
                        if n.startswith('SpeciesConcVV_'):
                            check(np.min(vals) >= 0, 'negative species ' + p.name + ':' + n)
                        if n.startswith(('AODHyg', 'RadAOD', 'BrCDryAOD')):
                            check(np.min(vals) >= -1e-15, 'negative AOD ' + p.name + ':' + n)
        if coll != 'Restart':
            expected = [(str(base + datetime.timedelta(days=i)), str(base + datetime.timedelta(days=i + 1))) for i in range(31)] if daily else [(str(base), str(end))]
            check(sorted(intervals) == expected, 'wrong interval coverage ' + coll)
            ranges[coll] = intervals
    check(maxima.get('RadAOD550nm_BRC', 0) > 0 and maxima.get('RadAOD550nm_BRCT', 0) > 0, 'missing/nonpositive550nm RRTMG fields')
    check(maxima.get('AODHyg550nm_BRCSOA', 0) > 0, 'missing/nonpositive550nm aerosol field')
    for n in TARGETS:
        check(maxima.get('SpeciesConcVV_' + n, 0) > 0, 'missing/zero tracer ' + n)
    check(maxima.get('BrCDryAOD550nm', 0) > 0, 'missing/zero dry BrC AOD')
    for suffix in ['_BRC', '_BRCT']:
        check(any((n.startswith('RadAOD') and n.endswith(suffix) and (v > 0) for n, v in maxima.items())), 'missing/zero RRTMG AOD ' + suffix)
    for tracer in ['BRCSOA', 'NPBRCPOA', 'WTC']:
        check(any((n.startswith('AODHyg') and n.endswith('_' + tracer) and (v > 0) for n, v in maxima.items())), 'missing/zero aerosol AOD ' + tracer)
    check(any((n.startswith('Rad') and 'SW' in n and n.endswith('_BRC') and (max(abs(v), abs(minima[n])) > 0) for n, v in maxima.items())), 'no nonzero BRC SW flux')
    he = list((case / 'OutputDir').glob('HEMCO_diagnostics*.nc'))
    check(len(he) == 1, 'wrong monthly HEMCO count')
    fire = []
    for p in he:
        report = fire_audit(p, inventory='gfas', require_elevated=True)
        fire.append(report)
        check(report['status'] == 'PASS', 'monthly fire closure failed')
        files[str(p.relative_to(case))] = sha(p)
        with netCDF4.Dataset(p) as nc:
            check(all((n in nc.variables for n in ['EmisSOAP_Fire', 'EmisSOAP_FireColumn'])), 'missing SOAP pair')
            if all((n in nc.variables for n in ['EmisSOAP_Fire', 'EmisSOAP_FireColumn'])):
                pr = nc['EmisSOAP_Fire'][:]
                co = nc['EmisSOAP_FireColumn'][:]
                total = pr.sum(axis=1)
                err = float(np.max(np.abs(co - total) / np.maximum(np.abs(total), 1e-25)))
                check(np.isfinite(pr).all() and np.isfinite(co).all() and (np.min(pr) >= 0) and (np.max(pr) > 0) and (err <= 2e-06), 'SOAP finite/positive/closure')
            t = nc['time']
            dates = netCDF4.num2date(t[:], t.units, calendar=getattr(t, 'calendar', 'standard'))
            check(len(dates) == 1 and str(dates[0]) == '2018-08-01 00:00:00', 'wrong HEMCO month')
    points = {}
    for schedule in sorted(case.glob('Planeflight.dat.*')):
        date = schedule.name.rsplit('.', 1)[1]
        p = case / 'OutputDir' / ('plane.log.' + date)
        try:
            rows = read_log(p, FLIGHT, date)
            expected = schedule_points(schedule)
            check(set(rows) == set(expected), 'flight coverage ' + date)
            for k in rows.keys() & expected.keys():
                for n in ['LAT', 'LON', 'PRESS']:
                    check(abs(rows[k][n] - expected[k][n]) <= PRINTED_PRECISION_TOLERANCE, 'flight coordinates ' + date + str(k))
            points[date] = len(rows)
            files[str(p.relative_to(case))] = sha(p)
        except (OSError, ValueError) as e:
            errors.append(str(e))
    check(len(points) == 20, 'missing flight date')
    return {'status': 'FAIL' if errors else 'PASS', 'case': case.name, 'configuration_sha256': info['configs'][case.name], 'audit_script_sha256': sha(Path(__file__)), 'errors': errors, 'time_coverage': ranges, 'time_coverage_basis': 'Native global simulation start/end, interval-start timestamps, averaging_method and frozen HISTORY cadence; time_bnds not normally emitted', 'flight_points': points, 'fire': fire, 'output_sha256': files, 'scope': 'mechanical August comparison integrity only; no physical optics or forcing qualification'}
if __name__ == '__main__':
    try:
        r = audit(ROOT / sys.argv[1])
    except Exception as e:
        r = {'status': 'FAIL', 'errors': [repr(e)]}
    print(json.dumps(r, indent=2, allow_nan=False))
    sys.exit(0 if r['status'] == 'PASS' else 1)
