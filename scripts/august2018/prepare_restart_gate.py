"""Apply the named August recipe to unused, already staged 14.7/14.8 GFAS cases.

Requires EXECUTABLE_FREEZE.json, matching binary/source pins, 32 GFAS files,
and 20 flight schedules per case. Does not create inventories or choose physics.
"""
from pathlib import Path
import argparse
import copy
import datetime
import json
import re
import shutil
import subprocess
import yaml
from workflow_common import ROOT, CASES, SMOKE_SUFFIX, FREEZE, CONFIGS, DATES, MISSING, RADIATION, TIMESTEPS, require, sha, load, write_new, check_empty, verify_hashes
from preflight_restart_gate import check_restart

COLLECTIONS = ['Restart', 'SpeciesConc', 'Aerosols', 'Budget', 'RRTMG', 'StateMet', 'BrCDiagnostics']


def dump_config(cfg):
    text = yaml.safe_dump(cfg, sort_keys=False)
    for key in ('start_date', 'end_date'):
        day, clock = cfg['simulation'][key]
        text, count = re.subn(r'(?m)^(  ' + key + r':)\n  - \d+\n  - \d+', lambda m: f'{m[1]} [{day}, {clock:06d}]', text)
        require(count == 1, f'Cannot serialize {key}')
    return text


def nested_gfas(text):
    """Repair only the two known legacy compound guards; preserve data rows."""
    for old, keys in (
        ('GFAS.and.not.GFAS_EXTENSION_INJECTION', ['GFAS', '.not.GFAS_EXTENSION_INJECTION']),
        ('GFAS.and.GFAS_EXTENSION_INJECTION.and.GFAS_BRC_HARMONIZED_SENSITIVITY', ['GFAS', 'GFAS_EXTENSION_INJECTION', 'GFAS_BRC_HARMONIZED_SENSITIVITY']),
    ):
        if '(((' + old in text:
            require(text.count('(((' + old + '\n') == text.count(')))' + old + '\n') == 1, 'Ambiguous GFAS guard')
            text = text.replace('(((' + old + '\n', ''.join('(((' + k + '\n' for k in keys))
            text = text.replace(')))' + old + '\n', ''.join(')))' + k + '\n' for k in reversed(keys)))
    require(not re.search(r'^\(\(\(.*\.and\.', text, re.M), 'Unsupported HEMCO condition remains')
    return text


def history_cadence(text, smoke=False):
    active = re.findall(r"^\s*(?:COLLECTIONS:\s*)?'([^']+)'", text.split('::', 1)[0], re.M)
    require(set(active) == set(COLLECTIONS), 'Unexpected active HISTORY collections')
    for coll in active:
        cadence = '00000000 010000' if smoke else ('00000001 000000' if coll in ('RRTMG', 'BrCDiagnostics') else '00000100 000000')
        text, count = re.subn(r'(^\s*' + coll + r'\.(?:frequency|duration):\s*)\d{8}\s+\d{6}', lambda m: m[1] + cadence, text, flags=re.M)
        require(count == 2, f'Missing cadence: {coll}')
    return text


def fire_diagnostics(text, legacy):
    """Replace named Fire pairs only; retain all other diagnostic rows."""
    text = '\n'.join(l for l in text.splitlines() if not re.match(r'^Emis\w+_Fire(?:Column)?\s', l)) + '\n'
    extension = 166 if legacy else 112
    for species in 'CO BCPI BCPO OCPI OCPO SOAP FSOAP DBRCPOA NPBRCPOA PBRCPOA'.split():
        for suffix, dim in [('Fire', 3), ('FireColumn', 2)]:
            text += f'Emis{species}_{suffix} {species} {extension} -1 -1 {dim} kg/m2/s {species}_fire_flux\n'
    return text


def check_case_paths(case, restart):
    check_empty(case)
    require(not case.is_symlink(), f'Case directory is a symlink: {case}')
    for filename in ('geoschem_config.yml', 'species_database.yml', 'HEMCO_Config.rc', 'HISTORY.rc', 'HEMCO_Diagn.rc'):
        require(not (case / filename).is_symlink(), f'Mutable config is a symlink: {case / filename}')
    require(not (case / 'Restarts').is_symlink(), 'Restarts must be case-local')
    require(not (case / 'OutputDir').is_symlink(), 'OutputDir must be case-local')
    existing_restart = case / 'Restarts/GEOSChem.Restart.20180801_0000z.nc4'
    if existing_restart.exists() or existing_restart.is_symlink():
        require(existing_restart.resolve() == restart, 'Existing restart link differs')


def prepare(restart, sources, root=ROOT):
    require(not (root / FREEZE).exists(), 'Already frozen; use a new staging root')
    require(not (root / 'PREPARATION_STARTED.json').exists(), 'Previous preparation exists; inspect it before retrying')
    require(not (root / 'OPTICAL_INPUT_FREEZE_20260922.json').exists(), 'Existing optics freeze')
    binaries = load(root / 'EXECUTABLE_FREEZE.json')['cases']
    require(set(binaries) == set(CASES), 'Wrong executable cases')
    inputs = load(root / 'inputs/GFAS/v2026-06/download_manifest.json')['files']
    require(len(inputs) == 32, 'Expected 32 GFAS inputs')
    verify_hashes(root, {e['path']: e['sha256'] for e in inputs})
    restart = restart.resolve()
    planned = []
    optics = {}
    # Inspect BOTH cases and the full restart union before allowing EY or writing.
    for index, name in enumerate(CASES):
        case = root / name
        check_case_paths(case, restart)
        require(not (root / (name + SMOKE_SUFFIX)).exists(), 'Smoke directory already exists')
        require(not (case / 'before_august_recipe').exists(), 'Preparation backup exists')
        require({p.name for p in case.glob('Planeflight.dat.*')} == {'Planeflight.dat.' + d for d in DATES}, 'Wrong flight schedule dates')
        require(sha(case / 'gcclassic') == binaries[name]['executable_sha256'], 'Executable changed')
        cfg = yaml.safe_load((case / 'geoschem_config.yml').read_text())
        require(cfg['simulation']['start_date'] == [20180801, 0] and cfg['simulation']['end_date'] == [20180901, 0], 'Expected staged August month')
        adv = cfg['operations']['transport']['transported_species']
        pin = binaries[name]['build_sources']['geos-chem']['commit']
        monitor = subprocess.check_output(['git', '-C', str(sources[index] / 'src/GEOS-Chem'), 'show', pin + ':KPP/fullchem/gckpp_Monitor.F90'], text=True)
        chunks = re.findall(r'SPC_NAMES_\d+\s*=\s*\(/(.*?)/\)', monitor, re.S)
        kpp = {n.strip() for chunk in chunks for n in re.findall(r"'([^']+)'", chunk)}
        require(len(kpp) == (356 if index == 0 else 362), 'Unexpected KPP species count')
        check_restart(restart, adv, kpp, MISSING[index])
        cfg['operations']['rrtmg_rad_transfer_model'] = copy.deepcopy(RADIATION)
        cfg['timesteps'] = dict(TIMESTEPS)
        db = (case / 'species_database.yml').read_text().replace('BackgroundVV:', 'Background_VV:')
        backgrounds = yaml.safe_load(db)
        h = (case / 'HEMCO_Config.rc').read_text()
        h, count = re.subn(r'(^\* SPC_\s+[^\n]+\s)(?:EFYO|EY)(\s+xyz)', r'\1EY\2', h, flags=re.M)
        require(count == 1, 'Expected one supported restart row')
        h, count = re.subn(r'^(DiagnFreq:\s*)\w+', r'\1Monthly', h, flags=re.M)
        require(count == 1, 'Missing HEMCO cadence')
        if index == 0:
            h = nested_gfas(h)
            require(len(re.findall(r'^166 GFAS_INJECT_', h, re.M)) == 31, 'Incomplete legacy mapping')
        hist = history_cadence((case / 'HISTORY.rc').read_text())
        diag = fire_diagnostics((case / 'HEMCO_Diagn.rc').read_text(), index == 0)
        payload = {'geoschem_config.yml': dump_config(cfg), 'species_database.yml': db, 'HEMCO_Config.rc': h, 'HISTORY.rc': hist, 'HEMCO_Diagn.rc': diag}
        info = dict(source_checkout=str(sources[index].resolve()), build_core_pin=pin, transport_count=len(adv), kpp_count=len(kpp), union_count=len(set(adv) | kpp), missing_union=sorted(MISSING[index]), missing_backgrounds={n: float(backgrounds[n].get('Background_VV', 1e-20)) for n in sorted(MISSING[index])}, transport_species=adv, kpp_species=sorted(kpp), active_collections=COLLECTIONS, configs={})
        for directory in (cfg['aerosols']['optics']['input_dir'], cfg['operations']['photolysis']['cloud-j']['cloudj_input_dir']):
            tables = list(Path(directory).glob('*.dat'))
            require(bool(tables), f'Missing optical tables: {directory}')
            for p in tables:
                optics[str(p.resolve())] = {'sha256': sha(p), 'size': p.stat().st_size}
        planned.append((case, cfg, payload, info))
    require(planned[0][2]['HISTORY.rc'] == planned[1][2]['HISTORY.rc'], 'HISTORY must be matched before preparation')
    write_new(root / 'PREPARATION_STARTED.json', {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'restart': str(restart)})
    report = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), restart=str(restart), restart_sha256=sha(restart), restart_internal_date='2018-08-01 00:00:00', dimensions={'lat': 91, 'lon': 144, 'lev': 47}, cases={})
    for case, cfg, payload, info in planned:
        backup = case / 'before_august_recipe'
        backup.mkdir()
        for filename, text in payload.items():
            shutil.copy2(case / filename, backup / filename)
            (case / filename).write_text(text)
        (case / 'Restarts').mkdir(exist_ok=True)
        link = case / 'Restarts/GEOSChem.Restart.20180801_0000z.nc4'
        if link.exists() or link.is_symlink():
            require(link.resolve() == restart, 'Existing restart link differs')
        else:
            link.symlink_to(restart)
        (case / 'OutputDir').mkdir(exist_ok=True)
        smoke = root / (case.name + SMOKE_SUFFIX)
        shutil.copytree(case, smoke, symlinks=True, ignore=shutil.ignore_patterns('before_august_recipe'))
        smoke_cfg = copy.deepcopy(cfg)
        smoke_cfg['simulation']['end_date'] = [20180801, 10000]
        (smoke / 'geoschem_config.yml').write_text(dump_config(smoke_cfg))
        (smoke / 'HISTORY.rc').write_text(history_cadence(payload['HISTORY.rc'], True))
        (smoke / 'HEMCO_Config.rc').write_text(re.sub(r'^(DiagnFreq:\s*)Monthly', r'\1Hourly', payload['HEMCO_Config.rc'], flags=re.M))
        info['smoke_dir'] = str(smoke)
        info['configs'] = {d.name: {f: sha(d / f) for f in CONFIGS} for d in (case, smoke)}
        report['cases'][case.name] = info
    write_new(root / 'OPTICAL_INPUT_FREEZE_20260922.json', {'scope': 'All configured .dat optical tables', 'files': optics})
    write_new(root / FREEZE, report)
    from pair_configuration_contract import check_pair
    check_pair(False)
    check_pair(True)
    return {'status': 'PREPARED_NOT_RUNTIME_ACCEPTED', 'freeze': str(root / FREEZE)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart', required=True, type=Path)
    parser.add_argument('--legacy-source', required=True, type=Path)
    parser.add_argument('--native-source', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.restart, (args.legacy_source, args.native_source)), indent=2))


if __name__ == '__main__':
    main()
