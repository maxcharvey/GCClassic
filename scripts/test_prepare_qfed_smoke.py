#!/usr/bin/env python3
"""Unit tests for QFED smoke-fixture staging; uses synthetic donor files."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scripts/testdata/qfed_smoke"
SPEC = importlib.util.spec_from_file_location("prepare_qfed_smoke", ROOT / "scripts/prepare_qfed_smoke.py")
assert SPEC and SPEC.loader
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)


class PrepareQfedSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.donor = self.root / "donor"
        self.donor.mkdir()
        self.template = FIXTURES / "reviewed_qfed_fullchem.rc"
        self.donor.joinpath("HEMCO_Config.rc").write_text((FIXTURES / "published_gfed_donor.rc").read_text())
        self.donor.joinpath("geoschem_config.yml").write_text(
            "simulation:\n  start_date: [20000101, 000000]\n  end_date: [20000101, 010000]\n"
            "operations:\n  brown_carbon: false\n")
        self.donor.joinpath("HEMCO_Config.rc.gmao_metfields").write_text("met\n")
        self.donor.joinpath("species_database.yml").write_text("species\n")
        self.donor.joinpath("HISTORY.rc").write_text((FIXTURES / "published_history.rc").read_text())
        self.donor.joinpath("HEMCO_Diagn.rc").write_text((FIXTURES / "published_hemco_diagn.rc").read_text())
        self.donor.joinpath("build_info").mkdir()
        self.donor.joinpath("build_info/CMakeCache.txt").write_text("cache\n")
        self.donor.joinpath("Restarts").mkdir()
        self.donor.joinpath("Restarts/GEOSChem.Restart.20190701_0000z.nc4").write_text("restart\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_paired_cases_are_closed_and_differ_only_by_hs_flag(self) -> None:
        outroot = self.root / "out"
        outroot.mkdir()
        for name, hs in STAGE.CASES:
            STAGE.stage_case(self.donor, self.template, outroot / name, hs)
        off_name, on_name = (name for name, _ in STAGE.CASES)
        off = (outroot / off_name / "HEMCO_Config.rc").read_text()
        on = (outroot / on_name / "HEMCO_Config.rc").read_text()
        self.assertEqual(STAGE.replace_setting(off, "QFED2_BRC_HARMONIZED_SENSITIVITY", True), on)
        for text, hs in ((off, False), (on, True)):
            self.assertIn(f"QFED2_BRC_HARMONIZED_SENSITIVITY : {'true' if hs else 'false'}", text)
            for ident in STAGE.SCALAR_IDS:
                self.assertEqual(len(__import__("re").findall(rf"^\s*{ident}\s+", text, __import__("re").M)), 1)
            for name, value in (("QFED2", True), ("GFED4", False)):
                self.assertEqual(STAGE.replace_setting(text, name, value), text)
            for extension, name in (("111", "GFED"), ("112", "GFAS"), ("165", "FINNv25_Inject")):
                self.assertRegex(text, rf"(?m)^\s*{extension}\s+{name}\s*:\s*off\b")
            case_name = next(name for name, enabled in STAGE.CASES if enabled == hs)
            self.assertNotIn("gcclassic", "\n".join(p.name for p in (outroot / case_name).iterdir()))
        self.assertEqual((outroot / off_name / "HISTORY.rc").read_text(),
                         (self.donor / "HISTORY.rc").read_text())
        # The reviewed parser verifies effective QFED rows and numeric closure.
        parser = ROOT / "src/GEOS-Chem/test/implementation/qfed_brc_config_test.py"
        import subprocess
        parser_inputs = []
        for case, _ in STAGE.CASES:
            config = outroot / case / "HEMCO_Config.rc"
            fullchem = config.with_name("HEMCO_Config.rc.fullchem")
            shutil.copy2(config, fullchem)
            parser_inputs.append(str(fullchem))
        subprocess.run([sys.executable, str(parser), *parser_inputs], check=True)

    def test_manifest_is_pending_and_diagnostics_have_exact_selectors(self) -> None:
        outroot = self.root / "out"
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts/prepare_qfed_smoke.py"),
                        "--donor", str(self.donor), "--qfed-template", str(self.template),
                        "--outroot", str(outroot)], check=True)
        for name, _ in STAGE.CASES:
            diag = (outroot / name / "HEMCO_Diagn.rc").read_text().splitlines()
            expected_names = {f"Emis{label}_Fire{suffix}"
                              for label, _ in STAGE.QFED_DIAGNOSTICS
                              for suffix in ("", "Column")}
            selected = [line.split() for line in diag if line.split() and line.split()[0] in expected_names]
            self.assertEqual(len(selected), 18)
            self.assertTrue(all(row[2:6] in (["0", "5", "2", "3"], ["0", "5", "2", "2"]) for row in selected))
        manifest = json.loads((outroot / "manifest.json").read_text())
        self.assertEqual(manifest["executable"], "PENDING")
        self.assertEqual(manifest["source_contract"], "PENDING")

    def test_failure_preserves_staging_error_manifest(self) -> None:
        import subprocess
        outroot = self.root / "failed"
        broken = self.root / "broken.rc"
        broken.write_text("not a HEMCO template\n")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/prepare_qfed_smoke.py"),
                                 "--donor", str(self.donor), "--qfed-template", str(broken),
                                 "--outroot", str(outroot)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        manifest = json.loads((outroot / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "STAGING_FAILED")
        self.assertIn("QFED2 block", manifest["error"])

    def test_rejects_scalar_collision_missing_scale_section_and_overwrite(self) -> None:
        donor_text = (self.donor / "HEMCO_Config.rc").read_text()
        with self.assertRaisesRegex(ValueError, "scalar ID 288"):
            STAGE.replace_qfed_and_scalars(donor_text + "\n288 collision 1 - - - xy 1\n", self.template.read_text(), False)
        with self.assertRaisesRegex(ValueError, "scale-factor section"):
            STAGE.replace_qfed_and_scalars(donor_text.replace("### END SECTION SCALE FACTORS ###", ""), self.template.read_text(), False)
        occupied = self.root / "occupied"
        occupied.mkdir()
        import subprocess
        result = subprocess.run([sys.executable, str(ROOT / "scripts/prepare_qfed_smoke.py"),
                                 "--donor", str(self.donor), "--qfed-template", str(self.template),
                                 "--outroot", str(occupied)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((occupied / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
