from pathlib import Path
import tempfile
import unittest

from run_brc_engineering_matrix import DRYRUN_ARGUMENT, validate_dryrun


class DryrunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name)
        (self.run / 'OutputDir').mkdir()
        (self.run / 'dryrun.log').write_text('!!! GEOS-CHEM IS IN DRY-RUN MODE!')

    def test_matches_actual_cli_parser(self):
        source = Path(__file__).resolve().parents[1] / 'src/GEOS-Chem/Interfaces/GCClassic/main.F90'
        self.assertIn(f"CASE( '{DRYRUN_ARGUMENT}' )", source.read_text())

    def test_acknowledged_dryrun(self):
        validate_dryrun(self.run, 0)

    def test_ignored_switch_fails(self):
        (self.run / 'dryrun.log').write_text('Normal simulation; --dry-run was ignored')
        with self.assertRaises(RuntimeError):
            validate_dryrun(self.run, 0)

    def test_model_output_fails(self):
        (self.run / 'OutputDir/GEOSChem.Aerosols.nc4').touch()
        with self.assertRaises(RuntimeError):
            validate_dryrun(self.run, 0)

    def test_nonzero_exit_fails(self):
        with self.assertRaises(RuntimeError):
            validate_dryrun(self.run, 159)
