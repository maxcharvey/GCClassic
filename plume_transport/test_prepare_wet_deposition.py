#!/usr/bin/env python3
"""Focused preparation tests for stage1-wet-deposition-v1."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import yaml

from prepare_run import (
    TAGS,
    WETDEP_FORBIDDEN_PROPERTIES,
    WETDEP_PROPERTIES,
    WET_DEPOSITION_PREPARATION_CONTRACT,
    patch_wetdep_species_database,
    render_tpcore_config,
)


DIRECTORY = Path(__file__).resolve().parent
CONFIG_TEMPLATE = DIRECTORY / "templates/geoschem_config.wetdep.yml"
HISTORY_TEMPLATE = DIRECTORY / "templates/HISTORY.wetdep.rc"
SPECIES_DATABASE = DIRECTORY.parent / "src/GEOS-Chem/run/shared/species_database.yml"


def manifest(wet_deposition: bool) -> dict:
    return {
        "preparation_contract": WET_DEPOSITION_PREPARATION_CONTRACT,
        "acceptance": {"contract_version": "stage1-tpcore-causality-v2"},
        "runtime_contract": {
            "unset_environment": [
                "GC_QCK_BOTTOM_SURVEY",
                "GC_QCK_BOTTOM_SURVEY_RUN_ID",
                "GC_QCK_BOTTOM_SURVEY_FILE",
            ],
            "microclosure_environment": {
                "GC_QCK_BOTTOM_MICROCLOSURE_EVENT_MAX_KG": "5e-8",
                "GC_QCK_BOTTOM_MICROCLOSURE_CALL_MAX_KG": "5e-8",
            },
            "cell_diagnostics_environment": {
                "GC_PLUME_TPCORE_CELL_DIAGNOSTICS": "1",
                "GC_PLUME_TPCORE_CELL_DIAG_FILE": "./OutputDir/plume_tpcore_cell_events_v3.csv",
            },
            "donor_diagnostics_environment": {
                "GC_PLUME_TPCORE_DONOR_DIAGNOSTICS": "1",
                "GC_PLUME_TPCORE_DONOR_DIAG_FILE": "./OutputDir/plume_tpcore_donor_events_v3.csv",
            },
        },
        "ras_surface_reevap_runtime": {
            "enabled": True,
            "schema_version": "ras-surface-reevap-ledger-v1",
            "manifest_id": "PLUME-012-wetdep-test",
            "environment": {
                "GC_RAS_SURFACE_REEVAP_LEDGER": "1",
                "GC_RAS_SURFACE_REEVAP_LEDGER_FILE": "./OutputDir/ras_surface_reevap.csv",
                "GC_RAS_SURFACE_REEVAP_LEDGER_RUN_ID": "wetdep-test-20190101",
                "GC_RAS_SURFACE_REEVAP_LEDGER_MANIFEST_ID": "PLUME-012-wetdep-test",
            },
        },
        "run": {
            "start": "2019-01-01T00:00:00Z",
            "end": "2019-01-01T00:20:00Z",
            "transport_timestep_s": 600,
            "chemistry_timestep_s": 600,
            "operators": {
                "chemistry": True,
                "transport": True,
                "pbl_turbulence": True,
                "convection": True,
                "dry_deposition": True,
                "wet_deposition": wet_deposition,
                "native_tpcore": True,
                "transport_fill_negative_values": True,
                "transport_orders_i_j_k": [3, 3, 7],
                "native_do_tend": True,
            },
        },
    }


class WetDepositionPreparationTests(unittest.TestCase):
    def test_renders_only_wetdep_as_ab_switch(self) -> None:
        rendered = []
        for wet_deposition in (False, True):
            text = render_tpcore_config(CONFIG_TEMPLATE, manifest(wet_deposition))
            self.assertNotIn("__PLUME_", text)
            config = yaml.safe_load(text)
            operations = config["operations"]
            self.assertTrue(operations["transport"]["gcclassic_tpcore"]["activate"])
            self.assertTrue(operations["pbl_mixing"]["activate"])
            self.assertFalse(operations["pbl_mixing"]["use_non_local_pbl"])
            self.assertTrue(operations["convection"]["activate"])
            self.assertTrue(operations["dry_deposition"]["activate"])
            self.assertIs(operations["wet_deposition"]["activate"], wet_deposition)
            rendered.append(config)
        rendered[0]["operations"]["wet_deposition"] = rendered[1]["operations"][
            "wet_deposition"
        ]
        self.assertEqual(rendered[0], rendered[1])

    def test_contract_fails_closed_if_drydep_is_disabled(self) -> None:
        invalid = copy.deepcopy(manifest(True))
        invalid["run"]["operators"]["dry_deposition"] = False
        with self.assertRaisesRegex(ValueError, "dry_deposition"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_contract_rejects_missing_ras_surface_reevaporation_ledger(self) -> None:
        invalid = manifest(True)
        del invalid["ras_surface_reevap_runtime"]
        with self.assertRaisesRegex(ValueError, "ras_surface_reevap_runtime"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_species_patch_is_exact_active_standard_ocpo_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "species_database.yml"
            path.write_text(SPECIES_DATABASE.read_text(encoding="utf-8"), encoding="utf-8")
            patch_wetdep_species_database(path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("PLUME_WETDEP_PROP: &PLUMEWETDEPproperties", text)
            self.assertNotIn("PLUME_TAG_PROP:", text)
            database = yaml.safe_load(text)
            self.assertEqual(database["PLUME_WETDEP_PROP"], WETDEP_PROPERTIES)
            for tag in TAGS:
                species = database[tag]
                self.assertEqual(
                    {key: species[key] for key in WETDEP_PROPERTIES},
                    WETDEP_PROPERTIES,
                )
                self.assertTrue(species["FullName"])
                self.assertFalse(set(WETDEP_FORBIDDEN_PROPERTIES).intersection(species))

    def test_history_has_all_wetdep_ledgers_at_heartbeat_cadence(self) -> None:
        text = HISTORY_TEMPLATE.read_text(encoding="utf-8")
        for collection in ("Budget", "WetLossConv", "WetLossLS"):
            self.assertIn(f"{collection}.frequency:", text)
            self.assertIn(f"{collection}.duration:", text)
        self.assertIn("Budget.frequency:      00000000 001000", text)
        self.assertIn("Budget.duration:       00000000 001000", text)
        self.assertIn("WetLossConv.frequency: 00000000 001000", text)
        self.assertIn("WetLossConv.duration:  00000000 001000", text)
        self.assertIn("WetLossLS.frequency:   00000000 001000", text)
        self.assertIn("WetLossLS.duration:    00000000 001000", text)
        self.assertIn("'BudgetWetDepFull_?WET?", text)
        self.assertIn("'WetLossConv_?WET?", text)
        self.assertIn("'WetLossLS_?WET?", text)


if __name__ == "__main__":
    unittest.main()
