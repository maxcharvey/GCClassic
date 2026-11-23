"""Check the active FINN/GFAS data rows for each supported template mode."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src/GEOS-Chem/run/GCClassic"
BRC = ("FSOAP", "DBRCPOA", "NPBRCPOA", "PBRCPOA", "FOCPI", "FOCPO")


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
                        for row in rows:
                            if '.nc' in row[2]:
                                self.assertEqual(row[5], 'RF', row[1])
                                self.assertEqual(row[4].split('/')[2], '1-31')
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
                        legacy = by_name[f"GFAS_{species}_2D"]
                        tagged = by_name[f"GFAS_F{species}_2D"]
                        self.assertEqual(legacy[2] == "0", harmonized)
                        self.assertEqual(tagged[2] == "0", not harmonized)
                        self.assertEqual("282" in tagged[9], harmonized)

    def test_exclusive_fire_routing(self):
        for kind in ("fullchem", "aerosol"):
            text = (ROOT / f"HEMCO_Config.rc.templates/HEMCO_Config.rc.{kind}").read_text()
            for inventory, selector in (("GFAS", "GFAS_BRC_HARMONIZED_SENSITIVITY"),
                                        ("FINNv25", "FINNV25_BRC_HARMONIZED_SENSITIVITY"),
                                        ("QFED2", "QFED2_BRC_HARMONIZED_SENSITIVITY")):
                for enabled in (False, True):
                    for injection in ((False, True) if inventory == "FINNv25" else (False,)):
                        opts = {selector: enabled, "FINNv25_Inject": injection}
                        rows = selected_block(text, inventory, opts)
                        live = [r for r in rows if r[2] != "0"]
                        target = lambda row: row[1][5:-3] if row[0] == "112" else row[8]
                        species = [target(row) for row in live]
                        with self.subTest(kind=kind, inventory=inventory, enabled=enabled, injection=injection):
                            self.assertEqual("SOAP" in species, not enabled)
                            self.assertEqual("FSOAP" in species, enabled)
                            for phase in ("PI", "PO"):
                                self.assertEqual("FOC" + phase in species, enabled)
                                self.assertEqual("OC" + phase in species, not enabled)
                            if enabled:
                                # Residual OC + nonpersistent/persistent BrC close
                                # to the same input OC; splitting PI/PO adds no mass.
                                # Canonical configured coefficients (inventory factors
                                # 282-284 for FINN/GFAS, 288-290 for QFED).
                                ids = ("288", "289", "290") if inventory == "QFED2" else ("282", "283", "284")
                                values = {}
                                for line in text.splitlines():
                                    f = line.split()
                                    if len(f) > 2 and f[0] in ids + ("72", "73"):
                                        values[f[0]] = float(f[2])
                                self.assertAlmostEqual(values["72"] + values["73"], 1.0)
                                self.assertAlmostEqual(sum(values[i] for i in ids), 1.0)

    def test_gfas_source_inheritance(self):
        # Zero SOAP must not become the source inherited by the next species.
        for kind in ("fullchem", "aerosol"):
            text = (ROOT / f"HEMCO_Config.rc.templates/HEMCO_Config.rc.{kind}").read_text()
            for enabled in (False, True):
                rows = selected_block(text, "GFAS", {"GFAS_BRC_HARMONIZED_SENSITIVITY": enabled})
                previous = None
                for row in rows:
                    source = previous if row[2] == "-" else row[2:8]
                    self.assertIsNotNone(source)
                    if row[1] == "GFAS_STYR_2D":
                        self.assertIn("GFAS-smoke-", source[0])
                        self.assertEqual(source[1], "cofire")
                    previous = source

    def test_residual_fire_metadata(self):
        import yaml
        data = yaml.safe_load((ROOT.parent / "shared/species_database.yml").read_text())
        for phase in ("PI", "PO"):
            tagged, ordinary = data["FOC" + phase], data["OC" + phase]
            keys = [key for key in ordinary if key.startswith(("WD_", "DD_"))]
            keys += ["MW_g", "Density", "Is_Aerosol", "Is_DryDep", "Is_WetDep"]
            for key in keys:
                self.assertEqual(tagged[key], ordinary[key], (phase, key))
            self.assertTrue(tagged["Is_Advected"])
            self.assertEqual(tagged["Background_VV"], 0.0)
            self.assertFalse(tagged.get("Is_HygroGrowth", False))
            for kind in ("fullchem", "aerosol"):
                cfg = (ROOT / f"geoschem_config.yml.templates/geoschem_config.yml.{kind}").read_text()
                self.assertEqual(cfg.count("      - FOC" + phase + "\n"), 1)


if __name__ == "__main__":
    unittest.main()
