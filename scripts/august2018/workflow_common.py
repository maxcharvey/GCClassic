"""Shared guards for the explicitly scoped August 2018 comparison recipe."""
from pathlib import Path
import hashlib
import json
import os

ROOT = Path(os.environ.get('BRC_AUGUST_ROOT', Path(__file__).resolve().parent)).resolve()
CASES = ('BRC_147_GFAS_FIXED30_L15_20260921', 'BRC_148_GFAS_NATIVE3D_20260921')
SMOKE_SUFFIX = '_SMOKE1H_20260922'
FREEZE = 'RESTART_GATE_FREEZE_20260922.json'
ACCEPTANCE = 'SMOKE_ACCEPTANCE_20260922.json'
DATES = tuple('20180801 20180802 20180803 20180804 20180806 20180807 20180808 20180809 20180810 20180813 20180814 20180815 20180816 20180820 20180821 20180823 20180824 20180826 20180827 20180828'.split())
CONFIGS = ('gcclassic', 'geoschem_config.yml', 'HEMCO_Config.rc', 'HEMCO_Diagn.rc', 'HISTORY.rc', 'species_database.yml', 'HEMCO_Config.rc.gmao_metfields')
RADIATION = dict(activate=True, aod_wavelengths_in_nm=[550], longwave_fluxes=True, shortwave_fluxes=True, clear_sky_flux=True, all_sky_flux=True, fixed_dyn_heating=False, seasonal_fdh=False, read_dyn_heating=False, co2_ppmv=390.0)
TIMESTEPS = dict(transport_timestep_in_s=600, chemistry_timestep_in_s=1200, radiation_timestep_in_s=1200)
MISSING = ({'FFOCPI', 'FFOCPO', 'PBRCPOA'}, {'FFOCPI', 'FFOCPO', 'PBRCPOA', 'MDL', 'LHMSAQ', 'LHMSMP', 'PHMSAQ', 'PHMSMP', 'PSO4MP'})


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def write_new(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def verify_hashes(root, entries):
    for name, digest in entries.items():
        require(sha(root / name) == digest, f'Changed file: {name}')


def check_empty(case):
    require(not (case / 'GC.log').exists(), f'Already executed: {case}')
    require(not list((case / 'OutputDir').glob('*.nc*')), f'Existing outputs: {case}')
    require(not list((case / 'OutputDir').glob('plane.log.*')), f'Existing flight outputs: {case}')
    restarts = list((case / 'Restarts').glob('GEOSChem.Restart.*'))
    require(all(p.name == 'GEOSChem.Restart.20180801_0000z.nc4' for p in restarts), f'Existing endpoint restart: {case}')


def verify_optics_pair(root, configs):
    """Accept relocated paths only with frozen, byte-identical common tables."""
    records = load(root / 'OPTICAL_INPUT_FREEZE_20260922.json')['files']
    verify_hashes(root, {p: d['sha256'] for p, d in records.items()})
    directories = []
    for config in configs:
        directory = Path(config['aerosols']['optics']['input_dir'])
        tables = {p.name: p.resolve() for p in directory.glob('*.dat')}
        require(bool(tables), f'No optical tables: {directory}')
        for path in tables.values():
            require(str(path) in records, f'Unfrozen optical table: {path}')
        directories.append(tables)
        cloud = Path(config['operations']['photolysis']['cloud-j']['cloudj_input_dir'])
        cloud_tables = list(cloud.glob('*.dat'))
        require(bool(cloud_tables), f'No Cloud-J tables: {cloud}')
        for path in cloud_tables:
            require(str(path.resolve()) in records, f'Unfrozen Cloud-J table: {path}')
    require(configs[1]['aerosols']['carbon'].get('brc_optics') == 'organic', 'Native optics must remain organic')
    # Native organic mode reads org.dat for all six BrC bins. Its optional
    # dedicated brc.dat is frozen above but is not selected by this recipe.
    for name in ('so4.dat', 'soot.dat', 'org.dat', 'ssa.dat', 'ssc.dat', 'h2so4.dat', 'dust.dat'):
        require(name in directories[0] and name in directories[1], f'Missing base optical table: {name}')
        require(sha(directories[0][name]) == sha(directories[1][name]), f'Optical table differs: {name}')
    for name in ('brc.dat', 'pbrc.dat', 'dbrc.dat'):
        require(name in directories[0], f'Missing legacy BrC table: {name}')
        require(sha(directories[0][name]) == sha(directories[1]['org.dat']), f'Legacy organic-copy table differs: {name}')


def verify_acceptance(root=ROOT):
    gate = load(root / ACCEPTANCE)
    require(gate['status'] == 'PASS' and gate['independent_auditor'] == 'PASS', 'Unaccepted smoke pair')
    for group in ('reports_sha256', 'tools_and_inputs_sha256'):
        require(bool(gate[group]), f'Empty acceptance hash group: {group}')
        verify_hashes(root, gate[group])
    return gate
