#!/usr/bin/env python3
"""Stage (do not submit) a new FAST-JX fixture from the published smoke donor."""
import argparse
import json
from pathlib import Path
import shutil

from prepare_brc_engineering_matrix import sha256, replace_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('donor', type=Path)
    parser.add_argument('new_run', type=Path)
    args = parser.parse_args()
    run, donor = args.new_run.resolve(), args.donor.resolve()
    run.mkdir(parents=True, exist_ok=False)
    (run / 'OutputDir').mkdir()
    (run / 'Restarts').mkdir()
    restart = donor / 'Restarts/GEOSChem.Restart.20190701_0000z.nc4'
    shutil.copy2(restart, run / 'Restarts' / restart.name)
    configs = ('geoschem_config.yml', 'HEMCO_Config.rc', 'HEMCO_Config.rc.gmao_metfields',
               'HEMCO_Diagn.rc', 'HISTORY.rc', 'species_database.yml')
    for name in configs:
        text = (donor / name).read_text()
        if name == 'geoschem_config.yml':
            text = replace_once(text, r'^    overhead_O3:',
                                '    fast-jx:\n      fastjx_input_dir: /cluster/work/climate/GEOS-Chem/ExtData/CHEM_INPUTS/FAST_JX/v2024-05/\n    overhead_O3:')
        if name == 'HISTORY.rc':
            text = replace_once(text, r"^    'SpeciesConc',$", "    'SpeciesConc',\n    'JValues',")
            text += "\nJValues.template: '%y4%m2%d2_%h2%n2z.nc4',\nJValues.frequency: 00000000 010000\nJValues.duration: 00000000 010000\nJValues.mode: 'instantaneous'\nJValues.fields: 'Jval_?PHO?',\n    'JvalO3O1D',\n    'JvalO3O3P',\n::\n"
        (run / name).write_text(text)
    record = {'scope': 'FAST-JX organic BrC compatibility, dry DBRC RH=0; not physical optical qualification',
              'donor': str(donor), 'source': 'PENDING clean integration pin and FASTJX+RRTMG build',
              'start': '2019-07-01T00:00:00Z', 'end': '2019-07-01T01:00:00Z',
              'preflight': 'PENDING', 'hashes': {n: sha256(run / n) for n in configs},
              'restart_sha256': sha256(restart)}
    (run / 'input_manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(run)


if __name__ == '__main__':
    main()
