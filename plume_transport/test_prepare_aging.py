#!/usr/bin/env python3
"""Focused preparation and source-contract tests for stage1-aging-v1."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import yaml

from prepare_run import (
    AGING_PREPARATION_CONTRACT,
    AGING_PRODUCT_PROPERTIES,
    AGING_TAGS,
    PRODUCT_TAGS,
    TAGS,
    WETDEP_PROPERTIES,
    patch_aging_species_database,
    render_tpcore_config,
)


DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent
CONFIG_TEMPLATE = DIRECTORY / "templates/geoschem_config.aging.yml"
HISTORY_TEMPLATE = DIRECTORY / "templates/HISTORY.aging.rc"
SPECIES_DATABASE = ROOT / "src/GEOS-Chem/run/shared/species_database.yml"
AGING_MODULE = ROOT / "src/GEOS-Chem/GeosCore/plume_aging_mod.F90"
CHEMISTRY = ROOT / "src/GEOS-Chem/GeosCore/chemistry_mod.F90"
CHECKPOINT = ROOT / "src/GEOS-Chem/Interfaces/GCClassic/plume_checkpoint_mod.F90"


def manifest(aging_metadata_only: bool = True) -> dict:
    del aging_metadata_only
    return {
        "preparation_contract": AGING_PREPARATION_CONTRACT,
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
            "manifest_id": "PLUME-012-aging-test",
            "environment": {
                "GC_RAS_SURFACE_REEVAP_LEDGER": "1",
                "GC_RAS_SURFACE_REEVAP_LEDGER_FILE": "./OutputDir/ras_surface_reevap.csv",
                "GC_RAS_SURFACE_REEVAP_LEDGER_RUN_ID": "aging-test-20190101",
                "GC_RAS_SURFACE_REEVAP_LEDGER_MANIFEST_ID": "PLUME-012-aging-test",
                "GC_RAS_SURFACE_REEVAP_INCLUDE_AGED": "1",
            },
        },
        "checkpoint_runtime": {
            "environment": {
                "GC_PLUME_CHECKPOINTS": "1",
                "GC_PLUME_CHECKPOINT_DIR": "./OutputDir/PlumeCheckpoints",
                "GC_PLUME_CHECKPOINT_AGED_POOLS": "1",
                "GC_PLUME_CHECKPOINT_RUN_ID": "aging-test-20190101",
            },
        },
        "aging_runtime": {
            "enabled": True,
            "schema_version": "plume-aging-ledger-v1",
            "lifetime_s": 99360,
            "manifest_id": "PLUME-012-aging-test",
            "clear_environment": ["GC_PLUME_AGING"],
            "environment": {
                "GC_PLUME_AGING_LIFETIME_S": "99360",
                "GC_PLUME_AGING_FILE": "./OutputDir/plume_aging_v1.csv",
                "GC_PLUME_AGING_RUN_ID": "aging-test-20190101",
                "GC_PLUME_AGING_MANIFEST_ID": "PLUME-012-aging-test",
            },
        },
        "run": {
            "start": "2019-01-01T00:00:00Z",
            "end": "2019-01-01T00:20:00Z",
            "transport_timestep_s": 600,
            "chemistry_timestep_s": 1200,
            "operators": {
                "chemistry": True,
                "transport": True,
                "pbl_turbulence": True,
                "convection": True,
                "dry_deposition": True,
                "wet_deposition": True,
                "native_tpcore": True,
                "transport_fill_negative_values": True,
                "transport_orders_i_j_k": [3, 3, 7],
                "native_do_tend": True,
                "aging": False,
            },
        },
    }


class AgingPreparationTests(unittest.TestCase):
    def test_config_transports_all_ten_with_1200_second_chemistry(self) -> None:
        text = render_tpcore_config(CONFIG_TEMPLATE, manifest())
        self.assertNotIn("__PLUME_", text)
        config = yaml.safe_load(text)
        self.assertEqual(
            tuple(config["operations"]["transport"]["transported_species"]),
            AGING_TAGS,
        )
        self.assertEqual(config["timesteps"]["chemistry_timestep_in_s"], 1200)

    def test_contract_fails_closed_if_product_is_removed(self) -> None:
        text = render_tpcore_config(CONFIG_TEMPLATE, manifest())
        config = yaml.safe_load(text)
        config["operations"]["transport"]["transported_species"].pop()
        from prepare_run import validate_operator_contract

        with self.assertRaisesRegex(ValueError, "transported-species"):
            validate_operator_contract(manifest(), config)

    def test_contract_rejects_missing_aged_ras_ledger_switch(self) -> None:
        invalid = manifest()
        del invalid["ras_surface_reevap_runtime"]["environment"][
            "GC_RAS_SURFACE_REEVAP_INCLUDE_AGED"
        ]
        with self.assertRaisesRegex(ValueError, "incomplete RAS ledger"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_species_patch_has_sourced_parents_and_unsourced_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "species_database.yml"
            path.write_text(SPECIES_DATABASE.read_text(encoding="utf-8"),
                            encoding="utf-8")
            patch_aging_species_database(path)
            database = yaml.safe_load(path.read_text(encoding="utf-8"))
            for tag in TAGS:
                self.assertEqual(
                    {key: database[tag][key] for key in WETDEP_PROPERTIES},
                    WETDEP_PROPERTIES,
                )
            for tag in PRODUCT_TAGS:
                self.assertEqual(
                    {key: database[tag][key] for key in AGING_PRODUCT_PROPERTIES},
                    AGING_PRODUCT_PROPERTIES,
                )
                self.assertEqual(database[tag]["Src_Mode"], "none")
                self.assertIs(database[tag]["Src_Add"], False)

    def test_history_archives_chemistry_and_wet_budgets_each_heartbeat(self) -> None:
        text = HISTORY_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("BudgetChemistryFull_?ADV?", text)
        self.assertIn("BudgetWetDepFull_?WET?", text)
        self.assertIn("SpeciesConc.frequency: 00000000 001000", text)

    def test_source_is_default_off_and_hooked_after_tracer_sinks(self) -> None:
        module = AGING_MODULE.read_text(encoding="utf-8")
        chemistry = CHEMISTRY.read_text(encoding="utf-8")
        self.assertIn("LOGICAL, SAVE :: Enabled          = .FALSE.", module)
        self.assertIn("GC_PLUME_AGING_LIFETIME_S", module)
        self.assertIn("STATUS='NEW'", module)
        sink = chemistry.index("CALL Tracer_Sink_Phase")
        aging = chemistry.index("CALL Apply_Plume_Aging", sink)
        self.assertLess(sink, aging)
        self.assertIn("GC_PLUME_CHECKPOINT_AGED_POOLS", CHECKPOINT.read_text())

    def test_operator_is_exact_pair_transfer_without_native_sink_changes(self) -> None:
        module = AGING_MODULE.read_text(encoding="utf-8")
        self.assertIn("Transfer   = Parent_Old - Parent_New", module)
        self.assertIn("Conc(I,J,K) + Transfer", module)
        self.assertNotIn("Tracer_Sink_Phase", module)
        self.assertNotIn("!$OMP ATOMIC", module)
        self.assertNotIn("!$OMP CRITICAL", module)


if __name__ == "__main__":
    unittest.main()
