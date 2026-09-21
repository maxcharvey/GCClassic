#!/usr/bin/env python3
"""Check five same-executable runtime schemes; does not qualify parameters."""
import argparse
import json
from pathlib import Path
import re

import h5py
import numpy as np

from prepare_brc_engineering_matrix import sha256, replace_once


def check_rates(scheme, tau, rate, brc_flux, npbrc_flux):
    errors = []
    arrays = (tau, rate, brc_flux, npbrc_flux)
    if any(a.size == 0 for a in arrays):
        return ['Empty bleaching diagnostics']
    if len({a.shape for a in arrays}) != 1:
        return ['Bleaching diagnostics have mismatched shapes']
    if any(not np.all(np.isfinite(a)) for a in arrays):
        return ['Nonfinite bleaching diagnostics']
    if any(np.any(a < 0) for a in arrays):
        errors.append('Negative bleaching diagnostics')
    if scheme == 0:
        if any(np.any(a != 0) for a in (rate, brc_flux, npbrc_flux)):
            errors.append('Scheme 0 is not exact zero bleaching')
        if not np.allclose(tau, 1e8, rtol=2e-6):
            errors.append('Scheme 0 tau differs from the diagnostic cap')
    else:
        if not np.allclose(rate * tau, 1., rtol=2e-6, atol=0.):
            errors.append('Rate is not reciprocal lifetime')
        if not any(np.any(a > 0) for a in (brc_flux, npbrc_flux)):
            errors.append('Bleaching was not exercised with initialized BrC')
        if scheme == 1 and not np.allclose(tau, 86400., rtol=2e-6):
            errors.append('Scheme 1 lifetime is not one day')
        if scheme == 2:
            low = np.isclose(tau, 86400., rtol=2e-6)
            high = np.isclose(tau, 1e8, rtol=2e-6)
            if not np.all(low | high) or not (np.any(low) and np.any(high)):
                errors.append('Scheme 2 must exercise one-day and capped lifetime regimes')
        if scheme in (3, 4):
            if np.any(tau < 21600. * (1 - 2e-6)) or np.any(tau > 1e8 * (1 + 2e-6)):
                errors.append('Viscosity lifetime outside existing bounds')
            if float(np.ptp(tau)) == 0:
                errors.append('Viscosity lifetime has no spatial response')
    return errors


def audit(root):
    errors, cases, rates, configs, hashes = [], {}, {}, [], []
    manifest = json.loads((root / 'matrix_manifest.json').read_text())
    entries = {entry['run_id']: entry for entry in manifest['cases']}
    for scheme in range(5):
        run = root / f'BRC_BASE_GFED_ONLINE_SCHEME{scheme}_20260921'
        entry = entries[run.name]
        if (entry['bleach_scheme'], entry['hours'], entry['ft_fraction'], entry['ft_levels']) != (scheme, 6, 0, 0):
            errors.append(f'Scheme {scheme}: invalid manifest settings')
        local_entry = json.loads((run / 'input_manifest.json').read_text())
        if local_entry != entry:
            errors.append(f'Scheme {scheme}: local and matrix manifests differ')
        for name, digest in entry['hashes'].items():
            if sha256(run / name) != digest:
                errors.append(f'Scheme {scheme}: changed artifact {name}')
        if sha256(run / manifest['restart_path']) != manifest['restart_sha256']:
            errors.append(f'Scheme {scheme}: changed initialized restart')
        history = (run / 'HISTORY.rc').read_text()
        if not re.search(r"^BrCDiagnostics.mode:\s*'instantaneous'\s*$", history, re.MULTILINE):
            errors.append(f'Scheme {scheme}: reciprocal-rate check requires instantaneous diagnostics')
        config = (run / 'geoschem_config.yml').read_text()
        configs.append(replace_once(config, r'^    bleach_scheme: [0-4]\s*$', '    bleach_scheme: SCHEME'))
        hashes.append(tuple(sha256(run / name) for name in (
            'gcclassic', 'HEMCO_Config.rc', 'HEMCO_Diagn.rc', 'HISTORY.rc',
            'HEMCO_Config.rc.gmao_metfields', 'species_database.yml',
            manifest['restart_path'])))
        log = (run / 'GC.log').read_text(errors='replace')
        if 'E N D   O F   G E O S' not in log:
            errors.append(f'Scheme {scheme}: no normal end')
        if not re.search(rf'BrC bleaching scheme\s*:\s*{scheme}\b', log):
            errors.append(f'Scheme {scheme}: selection not printed')
        drylog = (run / 'dryrun.log').read_text(errors='replace')
        if ('GEOS-CHEM IS IN DRY-RUN MODE!' not in drylog or
                not re.search(rf'BrC bleaching scheme\s*:\s*{scheme}\b', drylog)):
            errors.append(f'Scheme {scheme}: acknowledged dry-run did not print selection')
        paths = sorted((run / 'OutputDir').glob('GEOSChem.BrCDiagnostics.*.nc4'))
        if len(paths) != 1:
            errors.append(f'Scheme {scheme}: expected one six-hour snapshot, got {len(paths)}')
            continue
        with h5py.File(paths[0], 'r') as nc:
            names = ('BrCTauBleach', 'BrCKBleach', 'BrCFluxBRC2WTC', 'BrCFluxNPBRC2WTC')
            data = []
            for name in names:
                ds = nc[name]
                arr = np.asarray(ds[...], dtype=float)
                if arr.ndim != 4 or arr.shape[0] != 1:
                    errors.append(f'Scheme {scheme}: {name} must have shape (1,lev,lat,lon)')
                for attr in ('_FillValue', 'missing_value'):
                    for fill in np.asarray(ds.attrs.get(attr, [])).ravel():
                        arr[arr == fill] = np.nan
                data.append(arr)
        failures = check_rates(scheme, *data)
        errors.extend(f'Scheme {scheme}: {e}' for e in failures)
        rates[scheme] = data[1]
        cases[scheme] = {name: {'min': float(a.min()), 'max': float(a.max())}
                         for name, a in zip(names, data) if np.all(np.isfinite(a))}
    if len(set(configs)) != 1 or len(set(hashes)) != 1:
        errors.append('Scheme runs differ in more than runtime bleach_scheme')
    if 3 in rates and 4 in rates:
        if np.array_equal(rates[3], rates[4]):
            errors.append('Fixed/local ozone viscosity schemes have identical rates')
    return {'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'cases': cases,
            'scope': 'Runtime selection and expected existing rate behavior only; no parameter promotion. '
                     'Scheme 2 retains the existing finite 1e8 s cap above 1 km, not exact zero.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    result = audit(args.root)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(result['status'] != 'PASS')
