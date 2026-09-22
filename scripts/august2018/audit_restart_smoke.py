"""Version-neutral mechanical restart/startup gate; never writes model output."""
from pathlib import Path
import sys, json, re, hashlib, datetime
import netCDF4, numpy as np
from workflow_common import ROOT
SCRIPTS = ROOT / 'analysis_tools'
sys.path.insert(0, str(SCRIPTS))
from audit_fire_output import audit as fire_audit
from compare_planeflight_profiles import read_log, schedule_points, normalize_longitude, PRINTED_PRECISION_TOLERANCE
TARGETS = ('FFOCPI', 'FFOCPO', 'BRCSOA', 'NPBRCPOA', 'PBRCPOA', 'DBRCPOA', 'WTC', 'FSOAP', 'FSOAS')
FLIGHT = tuple('OCPI OCPO BCPI BCPO FSOAP FSOAS NPBRCPOA PBRCPOA DBRCPOA BRCSOA WTC FFOCPI FFOCPO CO'.split())

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def audit(case):
    errors = []
    metrics = {}
    artifacts = {}
    freeze = json.loads((ROOT / 'RESTART_GATE_FREEZE_20260922.json').read_text())
    info = next((v for v in freeze['cases'].values() if case.name in v['configs']))

    def check(ok, message):
        if not ok:
            errors.append(message)
    for f, digest in info['configs'][case.name].items():
        check(sha(case / f) == digest, 'identity changed: ' + f)
    exitfile = case / 'model_exit_code.txt'
    check(exitfile.exists() and exitfile.read_text().strip() == '0', 'model exit not0')
    log = (case / 'GC.log').read_text(errors='replace')
    check('E N D   O F   G E O S' in log, 'missing normal end')
    fallback = {n: float(v.replace('D', 'E')) for n, v in re.findall('Species\\s+\\d+,\\s*(\\w+): not found in restart, setting to background =\\s*([\\d.EeDd+-]+)', log)}
    check(set(fallback) == set(info['missing_union']), f'fallback mismatch: {fallback}')
    for n, v in info['missing_backgrounds'].items():
        check(n in fallback and np.isclose(fallback[n], v, atol=0, rtol=1e-07), 'wrong background: ' + n)
    metrics['fallback_backgrounds'] = fallback
    radiation_times = set()
    current_time = None
    for line in log.splitlines():
        match = re.search('---> DATE: (\\d{4}/\\d{2}/\\d{2})  UTC: (\\d{2}:\\d{2})', line)
        if match:
            current_time = ' '.join(match.groups())
        if 'Calling RRTMG to compute fluxes and optics:' in line and current_time:
            radiation_times.add(current_time)
    check(radiation_times == {'2018/08/01 00:00', '2018/08/01 00:20', '2018/08/01 00:40'}, 'wrong radiation call times: ' + str(sorted(radiation_times)))
    metrics['radiation_times'] = sorted(radiation_times)
    maxima = {}
    minima = {}
    timestamps = {}
    for collection in info['active_collections']:
        files = [case / 'Restarts/GEOSChem.Restart.20180801_0100z.nc4'] if collection == 'Restart' else sorted((case / 'OutputDir').glob('GEOSChem.' + collection + '.*.nc4'))
        check(len(files) == 1 and all((p.is_file() for p in files)), 'expected one output: ' + collection)
        for p in files:
            if not p.is_file():
                continue
            artifacts[str(p.relative_to(case))] = sha(p)
            with netCDF4.Dataset(p) as nc:
                t = nc['time']
                times = netCDF4.num2date(t[:], t.units, calendar=getattr(t, 'calendar', 'standard'))
                timestamps[collection] = [str(v) for v in times]
                check(len(times) == 1, 'wrong record count: ' + collection)
                check(all(('2018-08-01 00:00:00' <= str(v) <= '2018-08-01 01:00:00' for v in times)), 'out-of-window: ' + collection)
                if collection == 'Restart':
                    check(str(times[0]) == '2018-08-01 01:00:00', 'wrong endpoint restart date')
                if collection != 'Restart':
                    check(str(times[0]) == '2018-08-01 00:00:00', 'wrong interval timestamp: ' + collection)
                    check(getattr(nc, 'simulation_start_date_and_time', '') == '2018-08-01 00:00:00z' and getattr(nc, 'simulation_end_date_and_time', '') == '2018-08-01 01:00:00z', 'wrong native interval metadata: ' + collection)
                    check(any((getattr(v, 'averaging_method', '') == 'time-averaged' for v in nc.variables.values())), 'missing averaging metadata: ' + collection)
                if 'time_bnds' in nc.variables:
                    bounds = netCDF4.num2date(nc['time_bnds'][:].reshape(-1), t.units, calendar=getattr(t, 'calendar', 'standard'))
                    if collection != 'Restart':
                        check([str(v) for v in bounds] == ['2018-08-01 00:00:00', '2018-08-01 01:00:00'], 'bad averaging bounds: ' + collection)
                for n, v in nc.variables.items():
                    if not np.issubdtype(v.dtype, np.number):
                        continue
                    a = v[:]
                    valid = np.ma.compressed(a)
                    check(valid.size > 0 and np.isfinite(valid).all(), p.name + ': nonfinite or entirely masked ' + n)
                    if valid.size and v.ndim >= 2:
                        maxima[n] = float(np.max(valid))
                        minima[n] = float(np.min(valid))
    check(maxima.get('RadAOD550nm_BRC', 0) > 0 and maxima.get('RadAOD550nm_BRCT', 0) > 0, 'missing/nonpositive550nm RRTMG fields')
    check(maxima.get('AODHyg550nm_BRCSOA', 0) > 0, 'missing/nonpositive550nm aerosol field')
    for n in TARGETS:
        check(maxima.get('SpeciesConcVV_' + n, 0) > 0, 'missing/zero tracer: ' + n)
        check(minima.get('SpeciesConcVV_' + n, -1) >= 0, 'negative/missing tracer: ' + n)
    for n, v in minima.items():
        if n.startswith(('AODHyg', 'BrCDryAOD', 'RadAOD')):
            check(v >= -1e-15, 'negative AOD: ' + n)
    for n in ['BrCTauBleach', 'BrCKBleach', 'BrCEtaBBOA', 'BrCFluxFSOAP2FSOAS', 'BrCFluxFSOAS2BRC', 'BrCFluxBRC2WTC', 'BrCFluxNPBRC2WTC', 'BrCDryAOD550nm']:
        check(maxima.get(n, 0) > 0, 'missing/zero BrC diagnostic: ' + n)
    check(any((n.startswith('RadAOD') and n.endswith('_BRC') and (v > 0) for n, v in maxima.items())), 'no positive RRTMG BRC AOD')
    check(any((n.startswith('RadAOD') and n.endswith('_BRCT') and (v > 0) for n, v in maxima.items())), 'no positive RRTMG BRCT AOD')
    for tracer in ['BRCSOA', 'NPBRCPOA', 'WTC']:
        check(any((n.startswith('AODHyg') and n.endswith('_' + tracer) and (v > 0) for n, v in maxima.items())), 'missing/zero aerosol AOD: ' + tracer)
    check(any((n.startswith('Rad') and 'SW' in n and n.endswith('_BRC') and (max(abs(v), abs(minima[n])) > 0) for n, v in maxima.items())), 'no nonzero RRTMG BRC SW flux')
    metrics['timestamps'] = timestamps
    metrics['required_maxima'] = {n: v for n, v in maxima.items() if n.startswith('BrC') or n in ['SpeciesConcVV_' + s for s in TARGETS] or (n.startswith('RadAOD') and n.endswith(('_BRC', '_BRCT')))}
    hf = sorted((case / 'OutputDir').glob('HEMCO_diagnostics*.nc'))
    check(len(hf) == 1, 'expected one HEMCO output')
    metrics['fire'] = []
    for p in hf:
        r = fire_audit(p, inventory='gfas', require_elevated=True)
        metrics['fire'].append(r)
        check(r['status'] == 'PASS', 'fire emission audit failed')
        artifacts[str(p.relative_to(case))] = sha(p)
        with netCDF4.Dataset(p) as nc:
            t = nc['time']
            ts = netCDF4.num2date(t[:], t.units, calendar=getattr(t, 'calendar', 'standard'))
            check(len(ts) == 1 and str(ts[0]) == '2018-08-01 00:00:00', 'HEMCO wrong interval start')
            check(all((n in nc.variables for n in ['EmisSOAP_Fire', 'EmisSOAP_FireColumn'])), 'missing SOAP diagnostic pair')
            if all((n in nc.variables for n in ['EmisSOAP_Fire', 'EmisSOAP_FireColumn'])):
                profile = nc['EmisSOAP_Fire'][:]
                column = nc['EmisSOAP_FireColumn'][:]
                summed = profile.sum(axis=1)
                err = float(np.max(np.abs(column - summed) / np.maximum(np.abs(summed), 1e-25)))
                metrics['SOAP_profile_column_max_relative_error'] = err
                check(np.isfinite(profile).all() and np.isfinite(column).all() and (np.min(profile) >= 0) and (np.max(profile) > 0) and (err <= 2e-06), 'SOAP finite/positive/closure failure')
    logpath = case / 'OutputDir/plane.log.20180801'
    schedule = case / 'Planeflight.dat.20180801'
    try:
        rows = read_log(logpath, FLIGHT, '20180801')
        expected = {k: v for k, v in schedule_points(schedule).items() if int(k[2]) <= 50}
        check(set(rows) == set(expected), f'flight keys mismatch: actual{len(rows)} expected{len(expected)}')
        for k in rows.keys() & expected.keys():
            for n in ['LAT', 'LON', 'PRESS']:
                actual = normalize_longitude(rows[k][n]) if n == 'LON' else rows[k][n]
                check(abs(actual - expected[k][n]) <= PRINTED_PRECISION_TOLERANCE, 'flight coordinate mismatch ' + str((k, n)))
        metrics['flight_points'] = len(rows)
        metrics['flight_expected_flushed'] = len(expected)
        metrics['flight_endpoint_caveat'] = 'Native half-diagnostic-step sampling ends00:50;9 scheduled00:51-00:59 points are unflushed at01:00. Midnight endpoint flush applies to month. No rows fabricated.'
        metrics['time_coverage_basis'] = 'Native global start/end attributes, interval-start time, averaging_method and frozen HISTORY cadence; time_bnds not emitted.'
        artifacts[str(logpath.relative_to(case))] = sha(logpath)
    except (ValueError, FileNotFoundError) as e:
        errors.append(str(e))
    artifacts['GC.log'] = sha(case / 'GC.log')
    return {'status': 'FAIL' if errors else 'PASS', 'case': case.name, 'configuration_sha256': info['configs'][case.name], 'audit_script_sha256': sha(Path(__file__)), 'errors': errors, 'metrics': metrics, 'output_sha256': artifacts, 'scope': 'one-hour mechanical runtime/restart gate only; version/injection confounded and optics unqualified'}
if __name__ == '__main__':
    r = audit(ROOT / sys.argv[1])
    print(json.dumps(r, indent=2, allow_nan=False))
    raise SystemExit(0 if r['status'] == 'PASS' else 1)
