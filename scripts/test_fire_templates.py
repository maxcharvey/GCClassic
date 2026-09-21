"""Check the active FINN/GFAS data rows for each supported template mode."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src/GEOS-Chem/run/GCClassic"
BRC = ("FSOAP", "DBRCPOA", "NPBRCPOA", "PBRCPOA")


def selected_block(text, inventory, options):
    # Evaluate only the deliberately bounded inventory block, not arbitrary
    # HEMCO expressions. All new selectors here are one switch or its negation.
    start = text.index(f"((({inventory}\n")
    end = text.index(f"))){inventory}\n", start)
    stack = [True]
    records = []
    for line in text[start:end].splitlines()[1:]:
        if line.startswith("((("):
            key = line[3:]
            negated = key.startswith(".not.")
            key = key.removeprefix(".not.")
            if key not in options:
                raise AssertionError(f"Unknown test selector {key}")
            enabled = not options[key] if negated else options[key]
            stack.append(stack[-1] and enabled)
        elif line.startswith(")))"):
            stack.pop()
        elif stack[-1] and re.match(r"^\d+\s", line):
            fields = line.split()
            assert len(fields) == 12, line
            records.append(fields)
    assert stack == [True]
    return records


class FireTemplateTests(unittest.TestCase):
    def test_paired_brc_total_diagnostics(self):
        for kind in ("fullchem", "aerosol"):
            text = (ROOT / f"HEMCO_Diagn.rc.templates/HEMCO_Diagn.rc.{kind}").read_text()
            rows = {row.split()[0]: row.split() for row in text.splitlines()
                    if row.strip() and not row.lstrip().startswith("#")}
            for species in BRC:
                with self.subTest(kind=kind, species=species):
                    profile = rows[f"Emis{species}_Total"]
                    column = rows[f"Emis{species}_TotalColumn"]
                    self.assertEqual(profile[1:5], [species, "-1", "-1", "-1"])
                    self.assertEqual(column[1:5], profile[1:5])
                    self.assertEqual(profile[5:7], ["3", "kg/m2/s"])
                    self.assertEqual(column[5:7], ["2", "kg/m2/s"])

    def test_modes(self):
        for kind in ("fullchem", "aerosol"):
            text = (ROOT / f"HEMCO_Config.rc.templates/HEMCO_Config.rc.{kind}").read_text()
            for injection in (False, True):
                for harmonized in (False, True):
                    with self.subTest(kind=kind, injection=injection, harmonized=harmonized):
                        rows = selected_block(text, "FINNv25", {
                            "FINNv25_Inject": injection,
                            "FINNV25_BRC_HARMONIZED_SENSITIVITY": harmonized})
                        self.assertTrue(rows)
                        self.assertEqual({r[0] for r in rows}, {"165" if injection else "0"})
                        self.assertEqual(len({r[1] for r in rows}), len(rows))
                        if injection:
                            self.assertTrue(all(r[1] == "FINNV25_INJECT_" + r[8] for r in rows))
                        for species in BRC:
                            selected = [r for r in rows if r[8] == species]
                            if harmonized or injection:
                                self.assertEqual(len(selected), 1)
                                if harmonized:
                                    self.assertNotEqual(selected[0][2], "0")
                                    if species == "FSOAP":
                                        self.assertEqual(selected[0][9], "75/286/287")
                                else:
                                    self.assertEqual(selected[0][2], "0")
                            else:
                                self.assertFalse(selected)
            for harmonized in (False, True):
                with self.subTest(kind=kind, gfas_harmonized=harmonized):
                    rows = selected_block(text, "GFAS", {
                        "GFAS_BRC_HARMONIZED_SENSITIVITY": harmonized})
                    self.assertTrue(all(r[0] == "112" for r in rows))
                    by_name = {r[1]: r for r in rows}
                    self.assertEqual(len(by_name), len(rows))
                    self.assertEqual(by_name["GFAS_CO_3D"][6], "xyz")
                    self.assertIn("v2026-06", by_name["GFAS_CO_3D"][2])
                    self.assertEqual(by_name["GFAS_CO_3D"][3], "cofire_3d")
                    for species in BRC:
                        row = by_name[f"GFAS_{species}_2D"]
                        self.assertEqual(row[7], "kg/m2/s")
                        self.assertEqual(row[2] == "0", not harmonized)
                        self.assertNotIn("287", row[9])
                    for species in ("OCPI", "OCPO"):
                        self.assertEqual("282" in by_name[f"GFAS_{species}_2D"][9], harmonized)


if __name__ == "__main__":
    unittest.main()
