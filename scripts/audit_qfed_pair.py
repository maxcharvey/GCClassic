#!/usr/bin/env python3
"""Check QFED BrC proxy-on closure and preservation of the proxy-off inventory."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from audit_fire_output import REQUIRED, _field, _column, _closure_error, audit


def compare(off, on):
    errors, metrics = [], {}
    if set(off) != set(REQUIRED) or set(on) != set(REQUIRED):
        return ['missing fire profile fields'], metrics
    shapes = {a.shape for a in (*off.values(), *on.values())}
    if len(shapes) != 1:
        return ['off/on profile shapes differ'], metrics
    for name, data in off.items():
        if not data.size or not np.all(np.isfinite(data)) or np.any(data < 0):
            errors.append(f'off {name}: empty, negative or nonfinite')
    for name, data in on.items():
        if not data.size or not np.all(np.isfinite(data)) or np.any(data < 0):
            errors.append(f'on {name}: empty, negative or nonfinite')
    if errors:
        return errors, metrics
    for species in ('FSOAP', 'DBRCPOA', 'NPBRCPOA', 'PBRCPOA'):
        if np.any(off[f'Emis{species}_Fire'] != 0):
            errors.append(f'proxy-off has nonzero {species} emissions')
    for species in ('CO', 'BCPI', 'BCPO'):
        name = f'Emis{species}_Fire'
        err = _closure_error(on[name], off[name])
        metrics[f'{species}_unchanged_relative_error'] = err
        if err > 2e-6 or not np.any(off[name] > 0):
            errors.append(f'{species}: off/on differs or inventory not exercised')
    oc_off = off['EmisOCPI_Fire'] + off['EmisOCPO_Fire']
    oc_on = sum(on[f'Emis{s}_Fire'] for s in ('OCPI', 'OCPO', 'NPBRCPOA', 'PBRCPOA'))
    metrics['OC_partition_relative_error'] = _closure_error(oc_on, oc_off)
    if metrics['OC_partition_relative_error'] > 2e-6 or not np.any(oc_off > 0):
        errors.append('OC inventory not conserved across residual OC + NP + PB')
    return errors, metrics


def audit_pair(off_path, on_path):
    result = audit(on_path, 'qfed2', require_elevated=True)
    errors = list(result['errors'])
    with h5py.File(off_path, 'r') as off_nc, h5py.File(on_path, 'r') as on_nc:
        try:
            off = {name: _field(off_nc[name]) for name in REQUIRED}
            on = {name: _field(on_nc[name]) for name in REQUIRED}
            for name, data in off.items():
                col = _column(off_nc[name.replace('_Fire', '_FireColumn')])
                if col.shape != data.shape[1:] or not np.all(np.isfinite(col)):
                    errors.append(f'off {name}: invalid column')
                elif _closure_error(col, data.sum(axis=0)) > 2e-6:
                    errors.append(f'off {name}: profile/column mismatch')
            failures, metrics = compare(off, on)
            errors.extend(failures)
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
            metrics = {}
    return {'status': 'FAIL' if errors else 'PASS', 'errors': errors,
            'on_audit': result, 'pair_metrics': metrics,
            'scope': 'QFED engineering proxy partition and unchanged CO/BC only; no inventory attribution or optics qualification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('off', type=Path)
    parser.add_argument('on', type=Path)
    args = parser.parse_args()
    result = audit_pair(args.off, args.on)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(result['status'] != 'PASS')
