"""Read-only, fail-closed August recipe preflight, including full restart union."""
from pathlib import Path
import argparse
import json
import re
import netCDF4
import numpy as np
import yaml
from workflow_common import ROOT, CASES, SMOKE_SUFFIX, FREEZE, DATES, MISSING, require, sha, load, verify_hashes, check_empty
from pair_configuration_contract import check_pair


def check_restart(path, transport, kpp, missing, dimensions=None):
    require(Path(path).is_file(), f'Missing restart: {path}')
    with netCDF4.Dataset(path) as nc:
        t = nc['time']
        dates = netCDF4.num2date(t[:], t.units, calendar=getattr(t, 'calendar', 'standard'))
        require(len(dates) == 1 and str(dates[0]) == '2018-08-01 00:00:00', 'Wrong restart date')
        expected_dims = dimensions or {'lat': 91, 'lon': 144, 'lev': 47}
        for key in ('lat', 'lon', 'lev'):
            require(len(nc.dimensions[key]) == expected_dims[key], f'Wrong restart dimension: {key}')
        available = {n[len('SpeciesRst_'):] for n in nc.variables if n.startswith('SpeciesRst_')}
        union = set(transport) | set(kpp)
        require(union - available == set(missing), f'Unexpected missing species: {sorted(union - available)}')
        for name in union & available:
            a = nc['SpeciesRst_' + name][:]
            require(a.shape[-3:] == tuple(expected_dims[k] for k in ('lev', 'lat', 'lon')), f'Wrong species shape: {name}')
            require(not np.ma.getmaskarray(a).any() and np.isfinite(a).all(), f'Invalid restart species: {name}')
    return str(dates[0])


def check_cadence(config_text, history, hemco, collections, smoke):
    # Decimal parsing avoids PyYAML 1.1 treating 010000 as octal 4096.
    tokens = re.search(r'end_date:\s*\[(\d+),\s*(\d+)\]', config_text)
    require(tokens is not None, 'Missing end date')
    require(tuple(map(int, tokens.groups())) == ((20180801, 10000) if smoke else (20180901, 0)), 'Wrong endpoint')
    for coll in collections:
        for kind in ('frequency', 'duration'):
            match = re.search(r'^\s*' + re.escape(coll) + r'\.' + kind + r':\s*(\d{8}\s+\d{6})', history, re.M)
            expected = '00000000 010000' if smoke else ('00000001 000000' if coll in ('RRTMG', 'BrCDiagnostics') else '00000100 000000')
            require(match is not None and match[1] == expected, f'Wrong {coll}.{kind}')
    frequency = re.search(r'^DiagnFreq:\s*(\w+)', hemco, re.M)
    require(frequency is not None and frequency[1] == ('Hourly' if smoke else 'Monthly'), 'Wrong HEMCO cadence')


def preflight(case_name, root=ROOT):
    require(case_name in CASES + tuple(n + SMOKE_SUFFIX for n in CASES), 'Unknown recipe case')
    case = root / case_name
    smoke = case_name.endswith(SMOKE_SUFFIX)
    check_pair(smoke)
    freeze = load(root / FREEZE)
    info = next(v for v in freeze['cases'].values() if case_name in v['configs'])
    check_empty(case)
    verify_hashes(case, info['configs'][case_name])
    inputs = load(root / 'inputs/GFAS/v2026-06/download_manifest.json')
    require(len(inputs['files']) == 32, 'Expected 32 GFAS files')
    verify_hashes(root, {e['path']: e['sha256'] for e in inputs['files']})
    rst = case / 'Restarts/GEOSChem.Restart.20180801_0000z.nc4'
    require(sha(rst) == freeze['restart_sha256'], 'Restart changed')
    cfg_text = (case / 'geoschem_config.yml').read_text()
    cfg = yaml.safe_load(cfg_text)
    require(cfg['simulation']['start_date'] == [20180801, 0], 'Wrong start date')
    require(set(cfg['operations']['transport']['transported_species']) == set(info['transport_species']), 'Transport species changed')
    expected_missing = MISSING[0 if '_147_' in case_name else 1]
    require(set(info['missing_union']) == expected_missing, 'Recipe missing-species allowlist changed')
    stamp = check_restart(rst, info['transport_species'], info['kpp_species'], expected_missing, freeze['dimensions'])
    h = (case / 'HEMCO_Config.rc').read_text()
    require(not re.search(r'^\(\(\(.*\.and\.', h, re.M), 'Unsupported HEMCO .and. guard')
    if '_147_' in case_name:
        require('(((GFAS\n(((GFAS_EXTENSION_INJECTION\n(((GFAS_BRC_HARMONIZED_SENSITIVITY' in h, 'Missing nested GFAS guard')
        require(len(re.findall(r'^166 GFAS_INJECT_', h, re.M)) == 31, 'Incomplete legacy GFAS mapping')
    spc = [l for l in h.splitlines() if l.startswith('* SPC_')]
    require(len(spc) == 1 and spc[0].split()[5] == 'EY', 'Unsupported restart flag')
    require('BackgroundVV:' not in (case / 'species_database.yml').read_text(), 'Misspelled background key')
    check_cadence(cfg_text, (case / 'HISTORY.rc').read_text(), h, info['active_collections'], smoke)
    require({p.name for p in case.glob('Planeflight.dat.*')} == {'Planeflight.dat.' + d for d in DATES}, 'Wrong flight dates')
    return {'status': 'PASS', 'case': case_name, 'configuration_sha256': info['configs'][case_name], 'freeze_sha256': sha(root / FREEZE), 'missing_species': sorted(expected_missing), 'restart_timestamp': stamp, 'all_present_union_fields_finite': True, 'frozen_hashes': 'PASS', 'cadence': 'PASS'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case')
    args = parser.parse_args()
    try:
        report = preflight(args.case)
    except Exception as exc:
        report = {'status': 'FAIL', 'errors': [str(exc)]}
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
