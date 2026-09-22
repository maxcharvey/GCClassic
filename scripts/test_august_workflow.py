"""Failure-driven tests for the bounded August comparison workflow."""
from pathlib import Path
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import netCDF4
import numpy as np
import yaml

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'august2018'))
import workflow_common as common
import pair_configuration_contract as pair
import preflight_restart_gate as preflight
import prepare_restart_gate as prepare
import accept_smoke_pair as acceptance
import submit_month_pair as submitter
from install_august_workflow import install


class AugustWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_json(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
        return p

    def pair_fixture(self):
        optical = self.root / 'optics'
        optical.mkdir()
        for name in ('so4', 'soot', 'org', 'ssa', 'ssc', 'h2so4', 'dust', 'brc', 'pbrc', 'dbrc'):
            (optical / (name + '.dat')).write_text('same scientific table')
        self.write_json('OPTICAL_INPUT_FREEZE_20260922.json', {'files': {str(p): {'sha256': common.sha(p)} for p in optical.glob('*.dat')}})
        config = {'simulation': {'read_restart_as_real8': True}, 'timesteps': dict(common.TIMESTEPS), 'aerosols': {'carbon': {}, 'optics': {'input_dir': str(optical)}}, 'operations': {'transport': {'transported_species': ['CO']}, 'rrtmg_rad_transfer_model': copy.deepcopy(common.RADIATION), 'photolysis': {'cloud-j': {'cloudj_input_dir': str(optical)}}}}
        for i, name in enumerate(common.CASES):
            c = copy.deepcopy(config)
            if i:
                c['simulation']['read_restart_as_real8'] = False
                c['operations']['transport']['transported_species'].append('MDL')
                c['aerosols']['carbon']['brc_optics'] = 'organic'
                c['operations']['photolysis']['cloud-j'].update(brc_optics='organic', verbose=False)
            p = self.root / name
            p.mkdir()
            (p / 'geoschem_config.yml').write_text(yaml.safe_dump(c))
            (p / 'HISTORY.rc').write_text('same diagnostics')
        return self.root / common.CASES[1] / 'geoschem_config.yml'

    def test_matched_pair_and_radiation_regressions(self):
        p = self.pair_fixture()
        original = yaml.safe_load(p.read_text())
        with patch.object(pair, 'ROOT', self.root):
            self.assertEqual(pair.check_pair(False)['status'], 'PASS')
            for key, value in [('longwave_fluxes', False), ('aod_wavelengths_in_nm', [527.1, 550]), ('all_sky_flux', False)]:
                bad = copy.deepcopy(original)
                bad['operations']['rrtmg_rad_transfer_model'][key] = value
                p.write_text(yaml.safe_dump(bad))
                with self.assertRaises(ValueError):
                    pair.check_pair(False)
            bad = copy.deepcopy(original)
            bad['timesteps']['radiation_timestep_in_s'] = 10800
            p.write_text(yaml.safe_dump(bad))
            with self.assertRaises(ValueError):
                pair.check_pair(False)

    def test_optics_drift_rejected(self):
        self.pair_fixture()
        (self.root / 'optics/org.dat').write_text('changed table')
        with patch.object(pair, 'ROOT', self.root), self.assertRaises(ValueError):
            pair.check_pair(False)

    def test_decimal_clock_and_long_run_cadence(self):
        cfg = {'simulation': {'start_date': [20180801, 0], 'end_date': [20180801, 10000]}}
        text = prepare.dump_config(cfg)
        self.assertIn('[20180801, 010000]', text)
        # Demonstrates why semantic PyYAML parsing of the clock is unsafe.
        self.assertEqual(yaml.safe_load(text)['simulation']['end_date'][1], 4096)
        hist = 'SpeciesConc.frequency: 00000000 010000\nSpeciesConc.duration: 00000000 010000\n'
        preflight.check_cadence(text, hist, 'DiagnFreq: Hourly', ['SpeciesConc'], True)
        with self.assertRaises(ValueError):
            preflight.check_cadence('end_date: [20180901, 000000]', hist, 'DiagnFreq: Monthly', ['SpeciesConc'], False)

    def test_legacy_nested_guards_preserve_rows(self):
        guard = 'GFAS.and.GFAS_EXTENSION_INJECTION.and.GFAS_BRC_HARMONIZED_SENSITIVITY'
        raw = f'((({guard}\n166 GFAS_INJECT_CO unchanged row\n))){guard}\n'
        fixed = prepare.nested_gfas(raw)
        self.assertNotIn('.and.', fixed)
        self.assertIn('(((GFAS\n(((GFAS_EXTENSION_INJECTION\n', fixed)
        self.assertIn('166 GFAS_INJECT_CO unchanged row', fixed)
        self.assertEqual(prepare.nested_gfas(fixed), fixed)
        with self.assertRaises(ValueError):
            prepare.nested_gfas('(((OTHER.and.SWITCH\n')

    def test_fire_diagnostics_selectors(self):
        text = 'EmisCO_Total CO -1 -1 -1 3 kg/m2/s total\n'
        for legacy, extension in [(True, '166'), (False, '112')]:
            fixed = prepare.fire_diagnostics(text, legacy)
            self.assertTrue(fixed.startswith(text))
            rows = [l.split() for l in fixed.splitlines() if '_Fire' in l]
            self.assertEqual(len(rows), 20)
            self.assertEqual({r[2] for r in rows}, {extension})
            self.assertEqual(prepare.fire_diagnostics(fixed, legacy), fixed)

    def make_restart(self, hours=0):
        p = self.root / 'restart.nc4'
        with netCDF4.Dataset(p, 'w') as nc:
            for name, size in [('time', 1), ('lev', 2), ('lat', 2), ('lon', 2)]:
                nc.createDimension(name, size)
            t = nc.createVariable('time', 'f8', ('time',))
            t.units = 'hours since 2018-08-01 00:00:00'
            t[:] = hours
            v = nc.createVariable('SpeciesRst_CO', 'f8', ('time', 'lev', 'lat', 'lon'))
            v[:] = 1e-9
        return p

    def test_full_kpp_union_and_restart_date(self):
        p = self.make_restart()
        dims = dict(lev=2, lat=2, lon=2)
        self.assertEqual(preflight.check_restart(p, ['CO'], ['CO', 'KPP_ONLY'], {'KPP_ONLY'}, dims), '2018-08-01 00:00:00')
        with self.assertRaises(ValueError):
            preflight.check_restart(p, ['CO'], ['CO', 'KPP_ONLY'], set(), dims)
        with netCDF4.Dataset(p, 'a') as nc:
            nc['time'][:] = 24
        with self.assertRaises(ValueError):
            preflight.check_restart(p, ['CO'], ['CO', 'KPP_ONLY'], {'KPP_ONLY'}, dims)

    def test_restart_nonfinite_rejected(self):
        p = self.make_restart()
        with netCDF4.Dataset(p, 'a') as nc:
            nc['SpeciesRst_CO'][0, 0, 0, 0] = np.nan
        with self.assertRaises(ValueError):
            preflight.check_restart(p, ['CO'], [], set(), dict(lev=2, lat=2, lon=2))

    def test_stale_independent_verdict_rejected(self):
        self.write_json(common.FREEZE, {'cases': {}})
        report = self.write_json('audit_147_smoke.json', {'status': 'PASS'})
        review = self.write_json('review.json', {'status': 'PASS', 'scope': 'final_harmonized_smoke_pair', 'main_reports_sha256': {report.name: 'old hash'}})
        with self.assertRaisesRegex(ValueError, 'Stale independent'):
            acceptance.accept(review, self.root)
        self.assertFalse((self.root / common.ACCEPTANCE).exists())

    def test_install_refuses_existing_workflow(self):
        record = install(self.root)
        common.verify_hashes(self.root, record['sha256'])
        with self.assertRaises(ValueError):
            install(self.root)

    def test_optimized_python_still_checks(self):
        env = dict(os.environ, PYTHONPATH=str(SCRIPTS / 'august2018'))
        result = subprocess.run([sys.executable, '-O', '-c', 'from workflow_common import require; require(False, "reject")'], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_submission_partial_failure_is_recorded_without_retry(self):
        results = [subprocess.CompletedProcess([], 0, '123\n', ''), subprocess.CompletedProcess([], 1, '', 'scheduler rejection')]
        with patch.object(submitter, 'verify_acceptance'), patch.object(submitter.subprocess, 'check_output', return_value=''), patch.object(submitter.subprocess, 'run', side_effect=results) as run:
            with self.assertRaises(ValueError):
                submitter.submit(self.root)
            d = common.load(self.root / 'MONTH_SUBMISSION_20260922.json')
            self.assertEqual(d['jobs']['147']['job_id'], '123')
            self.assertEqual(d['status'], 'SUBMISSION_FAILED')
            with self.assertRaises(ValueError):
                submitter.submit(self.root)
            self.assertEqual(run.call_count, 2)

    def test_shared_config_symlink_is_rejected_before_write(self):
        shared = self.root / 'shared.yml'
        shared.write_text('BackgroundVV: 1.0e-18\n')
        case = self.root / 'case'
        case.mkdir()
        (case / 'species_database.yml').symlink_to(shared)
        with self.assertRaisesRegex(ValueError, 'Mutable config is a symlink'):
            prepare.check_case_paths(case, self.root / 'restart.nc4')
        self.assertEqual(shared.read_text(), 'BackgroundVV: 1.0e-18\n')
        self.assertFalse((case / 'before_august_recipe').exists())

    def test_smoke_runner_cannot_launch_month(self):
        bindir = self.root / 'bin'
        bindir.mkdir()
        for name, body in [('hostname', 'echo compute-node'), ('scontrol', 'exit 0')]:
            p = bindir / name
            p.write_text('#!/bin/sh\n' + body + '\n')
            p.chmod(0o700)
        env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'], BRC_AUGUST_ROOT=str(self.root), SLURM_JOB_ID='test')
        result = subprocess.run(['bash', str(SCRIPTS / 'august2018/run_smoke_pair.sh'), common.CASES[0]], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Not a smoke case', result.stderr)
        self.assertFalse((self.root / common.CASES[0]).exists())

    def test_analysis_depends_on_both_jobs(self):
        results = [subprocess.CompletedProcess([], 0, str(i) + '\n', '') for i in (123, 124, 125)]
        with patch.object(submitter, 'verify_acceptance'), patch.object(submitter.subprocess, 'check_output', return_value=''), patch.object(submitter.subprocess, 'run', side_effect=results) as run:
            self.assertEqual(submitter.submit(self.root)['status'], 'SUBMITTED')
            args = run.call_args_list[-1].args[0]
            self.assertIn('--dependency=afterok:123:124', args)
            self.assertIn('--kill-on-invalid-dep=yes', args)
        wrapper = (SCRIPTS / 'august2018/run_month_analysis.sh').read_text()
        self.assertIn('#SBATCH --mem-per-cpu=8G', wrapper)
        self.assertNotIn('#SBATCH --mem=', wrapper)


if __name__ == '__main__':
    unittest.main()
