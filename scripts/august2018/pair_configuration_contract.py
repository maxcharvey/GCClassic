from pathlib import Path
import yaml, json
from workflow_common import ROOT
MISSING = '__MISSING__'

def check_pair(smoke):
    suffix = '_SMOKE1H_20260922' if smoke else ''
    dirs = [ROOT / ('BRC_147_GFAS_FIXED30_L15_20260921' + suffix), ROOT / ('BRC_148_GFAS_NATIVE3D_20260921' + suffix)]
    configs = [yaml.safe_load((d / 'geoschem_config.yml').read_text()) for d in dirs]
    a, b = configs
    from workflow_common import verify_optics_pair
    verify_optics_pair(ROOT, configs)
    expected = {'activate': True, 'aod_wavelengths_in_nm': [550], 'longwave_fluxes': True, 'shortwave_fluxes': True, 'clear_sky_flux': True, 'all_sky_flux': True, 'fixed_dyn_heating': False, 'seasonal_fdh': False, 'read_dyn_heating': False, 'co2_ppmv': 390.0}
    for c in configs:
        if not c['operations']['rrtmg_rad_transfer_model'] == expected:
            raise ValueError('radiation contract')
        if not c['timesteps'] == {'transport_timestep_in_s': 600, 'chemistry_timestep_in_s': 1200, 'radiation_timestep_in_s': 1200}:
            raise ValueError('timestep contract')
    allowed = {'aerosols.carbon.brc_optics': [MISSING, 'organic'], 'aerosols.optics.input_dir': [a['aerosols']['optics']['input_dir'], b['aerosols']['optics']['input_dir']], 'operations.photolysis.cloud-j.brc_optics': [MISSING, 'organic'], 'operations.photolysis.cloud-j.verbose': [MISSING, False], 'simulation.read_restart_as_real8': [True, False]}
    def value(config, path):
        for key in path.split('.'):
            if not isinstance(config, dict) or key not in config:
                return MISSING
            config = config[key]
        return config
    for path, expected_pair in allowed.items():
        if [value(a, path), value(b, path)] != expected_pair:
            raise ValueError(('recipe version contract', path))
    left_species = a['operations']['transport']['transported_species']
    right_species = b['operations']['transport']['transported_species']
    if right_species.count('MDL') != 1 or [n for n in right_species if n != 'MDL'] != left_species:
        raise ValueError('MDL must be the only added native transported species')
    differences = {}

    def walk(x, y, p=''):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                walk(x.get(k, MISSING), y.get(k, MISSING), (p + '.' + k).lstrip('.'))
        elif x != y:
            if p == 'operations.transport.transported_species':
                if not ([n for n in y if n != 'MDL'] == x and y.count('MDL') == 1):
                    raise ValueError((p, 'unexpected transport difference'))
                differences[p] = 'MDL added in14.8; otherwise same ordered list'
            else:
                if not (p in allowed and [x, y] == allowed[p]):
                    raise ValueError((p, x, y))
                differences[p] = [x, y]
    walk(a, b)
    if not (dirs[0] / 'HISTORY.rc').read_bytes() == (dirs[1] / 'HISTORY.rc').read_bytes():
        raise ValueError('HISTORY mismatch')
    return {'status': 'PASS', 'radiation_wavelength_nm': 550, 'radiation_timestep_s': 1200, 'allowed_version_differences': differences}
if __name__ == '__main__':
    print(json.dumps({'month': check_pair(False), 'smoke': check_pair(True)}, indent=2))
