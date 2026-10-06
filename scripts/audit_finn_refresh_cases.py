"""Read-only acceptance checks for isolated FINN daily-refresh repair cases."""
from pathlib import Path
import argparse, hashlib, json, re
import netCDF4 as nc
import numpy as np

GATE = 2e-6
NAMES = ['aug_ef', 'aug_rf', 'may_rf', 'repaired_aug', 'repaired_may',
         'repaired_fallback', 'repaired_legacy', 'repaired_supported', 'month_boundary', 'repaired_timezone', 'month_boundary_hours']


def array(v):
    a = v[:]
    assert not np.any(np.ma.getmaskarray(a)), v.name
    a = np.asarray(a, dtype=np.float64)
    assert np.all(np.isfinite(a)), v.name
    return a


def relative(a, b):
    assert np.all(a[b == 0] == 0), 'nonzero structural-zero cell'
    m = b > 0
    return float(np.max(np.abs(a[m]-b[m])/b[m])) if np.any(m) else 0.


def restart(run):
    info = json.loads((run/'STAGING.json').read_text())
    return run/'Restarts'/('GEOSChem.Restart.'+info['end'][0]+'_'+info['end'][1][:4]+'z.nc4')


def state_compare(a, b, must_equal=True):
    different = []
    with nc.Dataset(restart(a)) as x, nc.Dataset(restart(b)) as y:
        names = {n for n in x.variables if np.issubdtype(x[n].dtype, np.number)}
        assert names == {n for n in y.variables if np.issubdtype(y[n].dtype, np.number)}
        for n in sorted(names):
            x[n].set_auto_maskandscale(False); y[n].set_auto_maskandscale(False)
            p, q = np.asarray(x[n][:]), np.asarray(y[n][:])
            assert np.all(np.isfinite(p)) and np.all(np.isfinite(q)), n
            if p.shape != q.shape or p.dtype != q.dtype or p.tobytes() != q.tobytes():
                different.append(n)
    if must_equal: assert not different, different
    else: assert 'SpeciesRst_CO' in different, 'changed daily source not delivered to CO state'
    return {'numeric_fields': len(names), 'different_fields': different}


def audit_case(run):
    info = json.loads((run/'STAGING.json').read_text())
    pre = json.loads((run/'PRELAUNCH.json').read_text())
    assert (run/'GC.exitcode').read_text().strip() == '0', run.name
    assert 'E N D   O F   G E O S -- C H E M' in (run/'GC.log').read_text()
    for f, h in pre['files'].items():
        assert hashlib.sha256((run/f).read_bytes()).hexdigest() == h, (run.name, f)
    assert restart(run).exists(), restart(run)
    with nc.Dataset(restart(run)) as d:
        for n, v in d.variables.items():
            if np.issubdtype(v.dtype, np.number): array(v)
    species = info['species']
    assert len(species) == len(set(species)) == 39
    paths = sorted((run/'OutputDir').glob('HEMCO_diagnostics*.nc'))
    assert paths, run.name
    worst, fallback_mass, source_mass = 0., 0., 0.
    for p in paths:
        with nc.Dataset(p) as d:
            area = array(d['AREA'])
            for sp in species:
                layer = array(d['Emis'+sp+'_Fire'])
                col = array(d['Emis'+sp+'_FireColumn'])
                assert np.all(layer >= 0) and np.all(col >= 0), (run.name, sp)
                assert d['Emis'+sp+'_Fire'].units == 'kg/m2/s'
                total = layer.sum(axis=d['Emis'+sp+'_Fire'].dimensions.index('lev'))
                pairs = [(total, col)]
                if info['profile_enabled']:
                    src = array(d['FINNProfileSource_'+sp]); assert np.all(src >= 0)
                    pairs += [(total, src), (col, src)]
                    for metric in ['Fallback', 'Terrain', 'AbovePBL']:
                        a = array(d['FINNProfile'+metric+'_'+sp])
                        assert np.all(a >= 0) and np.all(a <= src*(1+GATE)), (sp, metric)
                    if sp == 'CO':
                        source_mass += float(np.sum(src*area))
                        fallback_mass += float(np.sum(array(d['FINNProfileFallback_CO'])*area))
                for a, b in pairs:
                    error = relative(a, b)
                    assert error <= GATE, (run.name, p.name, sp, error)
                    worst = max(worst, error)
    return {'status': 'PASS', 'hourly_files': len(paths),
            'max_closure_relative': worst,
            'CO_fallback_mass_fraction': fallback_mass/source_mass if source_mass else None}


def pairs(root):
    result = {}
    result['precision_only_state_invariance'] = state_compare(root/'aug_rf', root/'repaired_aug')
    result['forced_fallback_state_equivalence'] = state_compare(root/'repaired_fallback', root/'repaired_legacy')
    result['daily_refresh_changes_delivered_state'] = state_compare(root/'aug_ef', root/'aug_rf', False)
    paths = {n: sorted((root/n/'OutputDir').glob('HEMCO_diagnostics*.nc'))[0]
             for n in ['repaired_aug', 'repaired_supported', 'repaired_fallback', 'repaired_legacy']}
    species = json.loads((root/'repaired_aug/STAGING.json').read_text())['species']
    supported = {}
    with nc.Dataset(paths['repaired_aug']) as a, nc.Dataset(paths['repaired_supported']) as b:
        for sp in species:
            src, fall = array(a['FINNProfileSource_'+sp]), array(a['FINNProfileFallback_'+sp])
            mask = (src > 0) & (fall == 0)
            x, y = array(a['Emis'+sp+'_Fire']), array(b['Emis'+sp+'_Fire'])
            m = np.broadcast_to(np.expand_dims(mask, a['Emis'+sp+'_Fire'].dimensions.index('lev')), x.shape)
            assert x[m].tobytes() == y[m].tobytes(), sp
            supported[sp] = int(mask.sum())
        assert supported['CO'] > 0
        assert np.any(array(a['FINNProfileFallback_CO']) > 0), 'natural unsupported case missing'
    result['supported_profile_cells_unchanged'] = supported
    with nc.Dataset(paths['repaired_fallback']) as a, nc.Dataset(paths['repaired_legacy']) as b:
        worst = 0.
        for sp in species:
            src = array(a['FINNProfileSource_'+sp])
            assert np.array_equal(src, array(a['FINNProfileFallback_'+sp])), sp
            # The new opt-in accumulator changes rounding of published fields;
            # exact atmospheric equivalence is tested independently above.
            x, y = array(a['Emis'+sp+'_Fire']), array(b['Emis'+sp+'_Fire'])
            err = relative(x, y); assert err <= GATE, (sp, err)
            worst = max(worst, err)
    result['forced_fallback_39_layer_fields_max_relative'] = worst
    phase_worst = 0.
    original = sorted((root/'repaired_supported/OutputDir').glob('HEMCO_diagnostics*.nc'))[0]
    hours = sorted((root/'repaired_timezone/OutputDir').glob('HEMCO_diagnostics*.nc'))[0]
    with nc.Dataset(original) as a, nc.Dataset(hours) as b:
        for sp in species:
            p, q = array(a['FINNProfileSource_'+sp]), array(b['FINNProfileSource_'+sp])
            assert np.array_equal(p > 0, q > 0), sp
            x, y = array(a['Emis'+sp+'_Fire']), array(b['Emis'+sp+'_Fire'])
            axis = a['Emis'+sp+'_Fire'].dimensions.index('lev')
            pn, qn = np.expand_dims(p, axis), np.expand_dims(q, axis)
            wx = np.divide(x, pn, out=np.zeros_like(x), where=pn > 0)
            wy = np.divide(y, qn, out=np.zeros_like(y), where=qn > 0)
            # Absolute L1 error in normalized per-column allocation weights.
            error = float(np.max(np.sum(np.abs(wx-wy), axis=axis)))
            assert error <= GATE, (sp, error)
            phase_worst = max(phase_worst, error)
        assert not np.array_equal(array(a['FINNProfileSource_CO']), array(b['FINNProfileSource_CO']))
    result['timezone_phase_only_39_profile_weights_max_L1'] = phase_worst
    result['timezone_phase_changes_atmospheric_state'] = state_compare(root/'repaired_supported', root/'repaired_timezone', False)
    expected = {'MDL', 'FFOCPI', 'FFOCPO', 'PBRCPOA', 'PSO4MP', 'PHMSAQ', 'PHMSMP', 'LHMSAQ', 'LHMSMP'}
    for name in ['may_rf', 'repaired_may']:
        missing = {m.group(1): float(m.group(2)) for m in re.finditer(
            r'Species\s+\d+,\s*(\w+): not found in restart, setting to background =\s*([\d.Ee+-]+)',
            (root/name/'GC.log').read_text())}
        assert set(missing) == expected, missing
        for name2, value in missing.items():
            target = 1e-18 if name2 == 'PBRCPOA' else 1e-20
            assert abs(value/target-1) < 1e-6
        result[name+'_declared_backgrounds'] = missing
    rejected = root/'read_once_rejected'
    assert (rejected/'GC.exitcode').read_text().strip() != '0'
    assert 'daily input uses read-once time flag' in (rejected/'GC.log').read_text()
    result['stale_configuration_rejected'] = True
    missing = root/'missing_profile_rejected'
    assert (missing/'GC.exitcode').read_text().strip() != '0'
    log = (missing/'GC.log').read_text()
    assert 'Cannot find the FINNV25_GFAS_REFERENCE field' in log
    assert 'GFAS_DOES_NOT_EXIST' in log
    assert '---> DATE:' not in log, 'Missing required profile must stop before integration'
    result['missing_required_RFY_profile_rejected'] = True
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    assert not args.output.exists(), args.output
    result = {'status': 'PASS', 'gate': GATE,
              'scope': 'Engineering acceptance; historical season remains FAIL, atmospheric validation pending.',
              'cases': {n: audit_case(args.root/n) for n in NAMES},
              'pairs': pairs(args.root)}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print('PASS')
