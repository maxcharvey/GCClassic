import tempfile
import unittest
from pathlib import Path

from check_brc_history import check_history


GOOD = """COLLECTIONS: 'Restart',
             'Aerosols',
             # comment between active entries
             'BrCDiagnostics',
             'RRTMG',
::
Restart.filename: './Restarts/example.nc4',
Aerosols.template: '%y4%m2%d2_%h2%n2z.nc4',
"""


class HistoryTests(unittest.TestCase):
    def run_text(self, text, brc="on", rrtmg="on"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".rc", delete=False)
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        tmp.write(text)
        tmp.close()
        return check_history(tmp.name, brc, rrtmg)

    def test_good_enabled(self):
        self.assertEqual(self.run_text(GOOD)["status"], "PASS")

    def test_multiple_names_on_line_fails(self):
        report = self.run_text("COLLECTIONS: 'Restart', 'Aerosols',\n'BrCDiagnostics'\n'RRTMG'\n")
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("multiple collection" in e for e in report["errors"]))

    def test_format_fails_without_single_quote_and_comma(self):
        report = self.run_text('COLLECTIONS: "Restart"\n\'Aerosols\',\n\'BrCDiagnostics\',\n\'RRTMG\',\n')
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("single quotes" in e for e in report["errors"]))

    def test_missing_mode_collection_fails(self):
        self.assertEqual(self.run_text("COLLECTIONS: 'Restart',\n'Aerosols'\n")["status"], "FAIL")

    def test_disabled_collections_fail(self):
        self.assertEqual(self.run_text(GOOD, "off", "off")["status"], "FAIL")

    def test_brc_off_allows_brc_diagnostics_control(self):
        report = self.run_text(GOOD, "off", "on")
        self.assertEqual(report["status"], "PASS")

    def test_missing_collection_terminator(self):
        self.assertEqual(self.run_text(GOOD.replace("::", ""))["status"], "FAIL")

    def test_missing_filename_comma(self):
        self.assertEqual(self.run_text(GOOD.replace("example.nc4',", "example.nc4'"))["status"], "FAIL")

    def test_missing_template_comma(self):
        self.assertEqual(self.run_text(GOOD.replace("%h2%n2z.nc4',", "%h2%n2z.nc4'"))["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
