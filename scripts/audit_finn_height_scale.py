#!/usr/bin/env python3
"""Audit a matched short-run accepted/default/identity/lower/higher matrix.

Checks physical output arrays, not build metadata, with the existing 2e-6
source-closure gate. Cumulative profiles must move down/up at every layer
interface. This ordering test is independent of the overlap implementation
and remains valid when diagnostics average multiple emission calls.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, set_chunk_cache

# Many compressed HISTORY/restart variables otherwise retain a separate large
# chunk cache. This reader touches each whole variable once; cache retention
# adds memory without improving the comparison.
set_chunk_cache(65536, 101, 0.0)


def configure_reader(nc):
    nc.set_auto_mask(False)
    for var in nc.variables.values():
        if isinstance(var.chunking(), list):
            var.set_var_chunk_cache(65536, 101, 0.0)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def numeric_identity(a, b):
    count = 0
    with Dataset(a) as left, Dataset(b) as right:
        configure_reader(left)
        configure_reader(right)
        assert set(left.variables) == set(right.variables), (a, b, 'variable roster')
        for name, var in left.variables.items():
            if np.dtype(var.dtype).kind not in 'fiu':
                continue
            x, y = np.asarray(var[:]), np.asarray(right[name][:])
            assert np.all(np.isfinite(x)) and np.all(np.isfinite(y)), (a, name, 'nonfinite')
            assert x.shape == y.shape and x.dtype == y.dtype, (a, name, 'layout')
            assert x.tobytes() == y.tobytes(), (a, b, name, 'identity differs')
            count += 1
    return count


def read_emissions(path):
    with Dataset(path) as nc:
        configure_reader(nc)
        fields = {name: np.asarray(var[:], dtype=np.float64)
                  for name, var in nc.variables.items()
                  if name.startswith(('Emis', 'FINNProfile'))}
        for name, x in fields.items():
            assert np.all(np.isfinite(x)) and np.all(x >= 0), (path, name, 'invalid emission')
        assert nc['EmisCO_Fire'].dimensions == ('time', 'lev', 'lat', 'lon')
        layout = {name: (nc[name].dimensions, nc[name].shape, str(nc[name].dtype),
                         getattr(nc[name], 'units', None)) for name in fields}
        coordinates = {name: np.asarray(nc[name][:]).tobytes()
                       for name in ('time', 'lon', 'lat', 'lev', 'hyam', 'hybm', 'P0', 'AREA')}
        coordinates['time_units'] = nc['time'].units
    return fields, layout, coordinates


def audit(root):
    cases = root / 'cases'
    names = ('accepted', 'default', 'identity', 'lower', 'higher')
    output = {'scope': 'Bounded implementation qualification; not seasonal or physical acceptance',
              'source_closure_gate': 2e-6, 'cases': {}, 'identity_numeric_fields': 0,
              'fallback_layer_fields_checked': 0, 'cumulative_order_gate': 2e-6}
    paths = {}
    for name in names:
        case = cases / name
        assert (case / 'GC.exitcode').read_text().strip() == '0', (name, 'model failed')
        assert 'E N D   O F   G E O S -- C H E M' in (case / 'GC.log').read_text(), name
        paths[name] = sorted((case / 'OutputDir').glob('HEMCO_diagnostics*.nc'))
        assert paths[name], (name, 'missing emissions')
        output['cases'][name] = {'binary_sha256': sha256(case / 'gcclassic'),
                                'config_sha256': sha256(case / 'HEMCO_Config.rc'),
                                'hemco_records': len(paths[name]), 'max_source_closure': 0.0}
    # Match each numeric output field, including the endpoint restart, against
    # the accepted executable. Ignore only global/variable metadata strings.
    files = sorted((cases / 'accepted' / 'OutputDir').glob('*.nc*'))
    files += sorted((cases / 'accepted' / 'Restarts').glob('*0100z.nc4'))
    assert files and any('Restart' in p.name for p in files), 'missing endpoint restart'
    for name in ('default', 'identity'):
        for old in files:
            new = cases / name / old.relative_to(cases / 'accepted')
            assert new.is_file(), (name, old.name)
            output['identity_numeric_fields'] += numeric_identity(old, new)
    for record, base_path in enumerate(paths['accepted']):
        base, base_layout, base_coordinates = read_emissions(base_path)
        species = sorted(name.removeprefix('FINNProfileSource_') for name in base
                         if name.startswith('FINNProfileSource_'))
        assert len(species) == 39, ('active FINN species', species)
        output['species_count'] = len(species)
        for name in names:
            assert len(paths[name]) == len(paths['accepted']), (name, 'record count')
            assert paths[name][record].name == base_path.name, (name, 'record filename')
            data, layout, coordinates = read_emissions(paths[name][record])
            assert layout == base_layout, (name, 'emission roster/dimensions/units')
            assert coordinates == base_coordinates, (name, 'time/grid coordinates')
            for spc in species:
                source_key = 'FINNProfileSource_' + spc
                source = data[source_key]
                assert np.array_equal(source, base[source_key]), (name, spc, 'source changed')
                flux = data[f'Emis{spc}_Fire']
                column = data[f'Emis{spc}_FireColumn']
                positive = source > 0
                assert np.all(flux.sum(axis=1)[~positive] == 0), (name, spc, 'zero-source emission')
                assert np.all(column[~positive] == 0), (name, spc, 'zero-source column emission')
                for actual in (flux.sum(axis=1), column):
                    error = np.max(np.abs(actual[positive] / source[positive] - 1), initial=0)
                    assert error <= output['source_closure_gate'], (name, spc, 'source closure', error)
                    output['cases'][name]['max_source_closure'] = max(
                        output['cases'][name]['max_source_closure'], float(error))
                fallback_key = 'FINNProfileFallback_' + spc
                assert np.array_equal(data[fallback_key], base[fallback_key]), (name, spc, 'fallback changed')
                fallback = base[fallback_key] > 0
                assert np.array_equal(flux.transpose(0, 2, 3, 1)[fallback],
                                      base[f'Emis{spc}_Fire'].transpose(0, 2, 3, 1)[fallback]), (
                                          name, spc, 'fallback layer placement changed')
                output['fallback_layer_fields_checked'] += 1
            if name in ('lower', 'higher'):
                source = base['FINNProfileSource_CO']
                support = (source > 0) & (base['FINNProfileFallback_CO'] == 0)
                # A startup diagnostic can precede the first emission call.
                # Its zero-source closure is checked above; placement needs
                # actual supported emission and is required below overall.
                if not np.any(support):
                    continue
                original = np.cumsum(base['EmisCO_Fire'], axis=1).transpose(0, 2, 3, 1)[support]
                changed = np.cumsum(data['EmisCO_Fire'], axis=1).transpose(0, 2, 3, 1)[support]
                delta = (changed - original) / source[support, None]
                violation = np.max(-delta if name == 'lower' else delta, initial=0)
                assert violation <= output['cumulative_order_gate'], (name, 'wrong height direction', violation)
                moved = np.max(np.abs(delta[:, :-1]), axis=1) > 1e-5
                assert np.any(moved), (name, 'no observable profile displacement')
                output['cases'][name]['supported_CO_column_records'] = (
                    output['cases'][name].get('supported_CO_column_records', 0) + int(support.sum()))
                output['cases'][name]['displaced_CO_column_records'] = (
                    output['cases'][name].get('displaced_CO_column_records', 0) + int(moved.sum()))
                output['cases'][name]['max_cumulative_order_violation'] = max(
                    output['cases'][name].get('max_cumulative_order_violation', 0), float(violation))
    for name in ('lower', 'higher'):
        assert output['cases'][name].get('displaced_CO_column_records', 0) > 0, (name, 'no placement qualification')
    output['status'] = 'PASS'
    return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root', type=Path)
    args = ap.parse_args()
    result = audit(args.root.resolve())
    (args.root / 'HEIGHT_SCALE_ACCEPTANCE.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
