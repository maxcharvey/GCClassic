#!/usr/bin/env python3
"""Audit the four six-hour snapshots in the 24-hour BrC engineering case."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path

import h5py
import numpy as np

from audit_brc_smoke import check_run
from prepare_brc_engineering_matrix import sha256


def field(nc, name):
    if name not in nc:
        raise ValueError(f'missing {name}')
    ds = nc[name]
    arr = np.asarray(ds[...], dtype=float)
    if not arr.size or not np.all(np.isfinite(arr)):
        raise ValueError(f'{name}: empty or nonfinite')
    for attr in ('_FillValue', 'missing_value'):
        if np.any(np.isin(arr, np.asarray(ds.attrs.get(attr, [])).ravel())):
            raise ValueError(f'{name}: fill values present')
    return arr


def snapshot_time(nc):
    arr = field(nc, 'time')
    unit = nc['time'].attrs.get('units', '')
    if isinstance(unit, bytes):
        unit = unit.decode()
    if arr.shape != (1,) or not unit.startswith('minutes since '):
        raise ValueError('expected one time coordinate in minutes since origin')
    return datetime.fromisoformat(unit.removeprefix('minutes since ')) + timedelta(minutes=float(arr[0]))


def audit(root):
    manifest = json.loads((root / 'matrix_manifest.json').read_text())
    entries = [e for e in manifest['cases'] if e['hours'] == 24]
    if len(entries) != 1:
        return {'status': 'FAIL', 'errors': ['expected exactly one 24-hour case']}
    entry = entries[0]
    run = root / entry['run_id']
    report = check_run(run, 'on', 'on')
    errors, maxima = report['errors'], {}
    for name, digest in entry['hashes'].items():
        if sha256(run / name) != digest:
            errors.append(f'input hash changed: {name}')
    start = datetime.fromisoformat(entry['start'].removesuffix('Z'))
    expected = {start + timedelta(hours=h) for h in (6, 12, 18, 24)}
    groups = {
        'SpeciesConc': ('SpeciesConcVV_FFOCPI', 'SpeciesConcVV_FFOCPO', 'ProdFFOCPIfromFFOCPO'),
        'RRTMG': tuple(f'RadAODWL{wl}_{mask}' for wl in (1, 2, 3) for mask in ('BRC', 'BRCT', 'PM', 'DU')),
        'Aerosols': tuple('AODHygWL1_' + sp for sp in ('BRCSOA', 'NPBRCPOA', 'PBRCPOA', 'WTC', 'FSOAS')),
        'BrCDiagnostics': ('BrCAbsMass', 'BrCTotMass'),
    }
    distinct = False
    for collection, required in groups.items():
        paths = sorted((run / 'OutputDir').glob(f'GEOSChem.{collection}.*.nc4'))
        times = []
        if len(paths) != 4:
            errors.append(f'{collection}: expected four six-hour snapshots, found {len(paths)}')
        for path in paths:
            try:
                with h5py.File(path, 'r') as nc:
                    times.append(snapshot_time(nc))
                    for name in required:
                        arr = field(nc, name)
                        if arr.ndim < 3 or arr.shape[0] != 1 or np.any(arr < 0):
                            raise ValueError(f'{name}: invalid shape or negative values')
                        maxima[name] = max(maxima.get(name, 0.), float(arr.max()))
                    if collection == 'RRTMG':
                        pm, brc = field(nc, 'RadAODWL2_PM'), field(nc, 'RadAODWL2_BRC')
                        distinct |= pm.shape == brc.shape and not np.array_equal(pm, brc)
                        for mask in ('BASE', 'BRC', 'BRCT', 'PM', 'DU'):
                            field(nc, f'RadAllSkySWTOA_{mask}')
            except (ValueError, KeyError, OSError) as exc:
                errors.append(f'{path.name}: {exc}')
        if set(times) != expected or len(times) != len(set(times)):
            errors.append(f'{collection}: missing, duplicated, or unexpected snapshot times')
    for names in groups.values():
        for name in names:
            if maxima.get(name, 0.) <= 0:
                errors.append(f'{name}: no positive value over the test day')
    if not distinct:
        errors.append('PM and BRC AOD masks were not distinct')
    report.update(status='FAIL' if errors else 'PASS', day_field_maxima=maxima,
                  pm_brc_aod_distinct=distinct,
                  scope='24-hour runtime, finite diagnostics, active FFOC and shifted dust-mask checks; not physical forcing validation')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    result = audit(parser.parse_args().root)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(result['status'] != 'PASS')
