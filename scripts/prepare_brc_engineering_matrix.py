#!/usr/bin/env python3
"""Stage new issue-acceptance runs from the completed July 2019 retry fixture.

Never changes the donor or runs a model. Uses its archived, source-pinned
executable and its original midnight cold restart, not a spun-up scientific
initial condition. Midnight lies on the MERRA2 I3 time grid; the one-hour
restart cannot safely initialize the canonical NEXTDAY meteorology lookup.
Independent pre-flight is still required.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replace_once(text, pattern, replacement):
    text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f'Expected one match, got {count}: {pattern}')
    return text


def prepare(donor, root):
    donor, root = donor.resolve(), root.resolve()
    provenance = json.loads((donor / 'forcing_provenance.json').read_text())
    expected = next(a['sha256'] for a in provenance['artifacts'] if a['role'] == 'executable')
    if sha256(donor / 'gcclassic') != expected:
        raise ValueError('Donor executable no longer matches its archived provenance')
    restart = donor / 'Restarts/GEOSChem.Restart.20190701_0000z.nc4'
    if not restart.is_file():
        raise ValueError('Missing common initialized restart')
    root.mkdir(parents=True, exist_ok=False)
    config_names = ('geoschem_config.yml', 'HEMCO_Config.rc',
                    'HEMCO_Config.rc.gmao_metfields', 'HEMCO_Diagn.rc',
                    'HISTORY.rc', 'species_database.yml')
    cases = [('BRC_BASE_GFED_ONLINE_INJECTION_20260921', 4, 1, .30, 10)]
    cases += [(f'BRC_BASE_GFED_ONLINE_SCHEME{s}_20260921', s, 6, 0., 0) for s in range(5)]
    cases += [('BRC_BASE_GFED_ONLINE_24H_20260921', 4, 24, 0., 0)]
    manifest = {'scope': 'Engineering acceptance only; current optics/parameters unchanged',
                'donor': str(donor), 'executable_source_provenance': provenance,
                'restart_path': 'Restarts/' + restart.name,
                'restart_sha256': sha256(restart), 'cases': []}
    for name, scheme, hours, fraction, levels in cases:
        run = root / name
        run.mkdir()
        (run / 'OutputDir').mkdir()
        (run / 'Restarts').mkdir()
        shutil.copy2(donor / 'gcclassic', run / 'gcclassic')
        shutil.copytree(donor / 'build_info', run / 'build_info')
        shutil.copy2(restart, run / 'Restarts' / restart.name)
        hemco_restart = donor / 'Restarts/HEMCO_restart.201907010000.nc'
        if hemco_restart.exists():
            shutil.copy2(hemco_restart, run / 'Restarts' / hemco_restart.name)
        for filename in config_names:
            text = (donor / filename).read_text()
            if filename == 'geoschem_config.yml':
                text = replace_once(text, r'^  start_date: .*$', '  start_date: [20190701, 000000]')
                end = '[20190702, 000000]' if hours == 24 else f'[20190701, {hours:02d}0000]'
                text = replace_once(text, r'^  end_date: .*$', f'  end_date: {end}')
                text = replace_once(text, r'^    bleach_scheme: .*$', f'    bleach_scheme: {scheme}')
            elif filename == 'HEMCO_Config.rc':
                for key, value in [('fraction', fraction), ('levels', levels)]:
                    text = replace_once(text, rf'^(    --> GFED_vertical_injection_{key}\s*:) .*$',
                                        rf'\g<1> {value}')
            elif filename == 'HISTORY.rc':
                cadence = '00000000 060000' if hours >= 6 else '00000000 010000'
                text = text.replace('00000000 010000', cadence)
                text = text.replace('# One-hour integration smoke diagnostics; do not use this cadence for production.',
                                    '# Short issue-acceptance diagnostics; not month-scale output settings.')
            (run / filename).write_text(text)
        artifacts = config_names + ('gcclassic', 'Restarts/' + restart.name)
        if hemco_restart.exists():
            artifacts += ('Restarts/' + hemco_restart.name,)
        entry = {'run_id': name, 'start': '2019-07-01T00:00:00Z',
                 'hours': hours, 'bleach_scheme': scheme, 'ft_fraction': fraction,
                 'ft_levels': levels, 'omp_threads': 8, 'omp_stacksize': '500M',
                 'seed': None, 'sample_count': 1, 'preflight': 'PENDING',
                 'hashes': {p: sha256(run / p) for p in artifacts}}
        (run / 'input_manifest.json').write_text(json.dumps(entry, indent=2) + '\n')
        manifest['cases'].append(entry)
    (root / 'matrix_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('donor', type=Path)
    parser.add_argument('new_root', type=Path)
    args = parser.parse_args()
    result = prepare(args.donor, args.new_root)
    print(json.dumps({'staged': len(result['cases']), 'root': str(args.new_root)}, indent=2))
