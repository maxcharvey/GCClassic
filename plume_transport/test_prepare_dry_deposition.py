#!/usr/bin/env python3
"""Focused preparation tests for stage1-dry-deposition-v1."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import yaml

from prepare_run import (
    DRYDEP_FORBIDDEN_PROPERTIES,
    DRYDEP_PROPERTIES,
    DRY_DEPOSITION_PREPARATION_CONTRACT,
    TAGS,
    patch_drydep_species_database,
    render_tpcore_config,
)


DIRECTORY = Path(__file__).resolve().parent
CONFIG_TEMPLATE = DIRECTORY / "templates/geoschem_config.drydep.yml"
HISTORY_TEMPLATE = DIRECTORY / "templates/HISTORY.drydep.rc"
SPECIES_DATABASE = (
    DIRECTORY.parent / "src/GEOS-Chem/run/shared/species_database.yml"
)


def manifest(dry_deposition: bool) -> dict:
    return {
        "preparation_contract": DRY_DEPOSITION_PREPARATION_CONTRACT,
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
                "dry_deposition": dry_deposition,
                "wet_deposition": False,
                "native_tpcore": True,
                "transport_fill_negative_values": True,
                "transport_orders_i_j_k": [3, 3, 7],
                "native_do_tend": True,
            },
        },
    }


class DryDepositionPreparationTests(unittest.TestCase):
    def test_renders_only_drydep_as_ab_switch(self) -> None:
        rendered = []
        for dry_deposition in (False, True):
            text = render_tpcore_config(CONFIG_TEMPLATE, manifest(dry_deposition))
            self.assertNotIn("__PLUME_", text)
            config = yaml.safe_load(text)
            operations = config["operations"]
            self.assertTrue(operations["transport"]["gcclassic_tpcore"]["activate"])
            self.assertTrue(operations["pbl_mixing"]["activate"])
            self.assertFalse(operations["pbl_mixing"]["use_non_local_pbl"])
            self.assertTrue(operations["convection"]["activate"])
            self.assertIs(operations["dry_deposition"]["activate"], dry_deposition)
            self.assertFalse(operations["wet_deposition"]["activate"])
            rendered.append(config)
        rendered[0]["operations"]["dry_deposition"] = rendered[1]["operations"][
            "dry_deposition"
        ]
        self.assertEqual(rendered[0], rendered[1])

    def test_contract_fails_closed_if_frozen_operator_is_disabled(self) -> None:
        invalid = copy.deepcopy(manifest(True))
        invalid["run"]["operators"]["convection"] = False
        with self.assertRaisesRegex(ValueError, "requires convection=true"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_contract_rejects_missing_donor_diagnostic_environment(self) -> None:
        invalid = manifest(True)
        del invalid["runtime_contract"]["donor_diagnostics_environment"]
        with self.assertRaisesRegex(ValueError, "donor diagnostics"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_species_patch_is_shared_ocpo_like_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "species_database.yml"
            path.write_text(SPECIES_DATABASE.read_text(encoding="utf-8"), encoding="utf-8")
            patch_drydep_species_database(path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("PLUME_DRYDEP_PROP: &PLUMEDRYDEPproperties", text)
            self.assertNotIn("PLUME_TAG_PROP:", text)
            database = yaml.safe_load(text)
            self.assertEqual(database["PLUME_DRYDEP_PROP"], DRYDEP_PROPERTIES)
            for tag in TAGS:
                species = database[tag]
                self.assertEqual(
                    {key: species[key] for key in DRYDEP_PROPERTIES},
                    DRYDEP_PROPERTIES,
                )
                self.assertTrue(species["FullName"])
                self.assertFalse(set(DRYDEP_FORBIDDEN_PROPERTIES).intersection(species))

    def test_history_has_heartbeat_budget_and_drydep_diagnostics(self) -> None:
        text = HISTORY_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("Budget.frequency:      00000000 001000", text)
        self.assertIn("Budget.duration:       00000000 001000", text)
        self.assertIn("'BudgetEmisDryDepFull_?ADV?", text)
        self.assertIn("'DryDep'", text)
        self.assertIn("DryDep.frequency:      00000000 001000", text)
        self.assertIn("DryDep.duration:       00000000 001000", text)
        self.assertIn("'DryDepMix_?DRY?", text)
        self.assertIn("'DryDepVel_?DRY?", text)


if __name__ == "__main__":
    unittest.main()
