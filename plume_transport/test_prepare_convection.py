#!/usr/bin/env python3
"""Focused preparation tests for stage1-convection-v1."""

from __future__ import annotations

import copy
from pathlib import Path
import unittest

import yaml

from prepare_run import CONVECTION_PREPARATION_CONTRACT, render_tpcore_config


DIRECTORY = Path(__file__).resolve().parent
CONFIG_TEMPLATE = DIRECTORY / "templates/geoschem_config.convection.yml"


def manifest(convection_active: bool) -> dict:
    return {
        "preparation_contract": CONVECTION_PREPARATION_CONTRACT,
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
            "chemistry_timestep_s": 1200,
            "operators": {
                "chemistry": True,
                "transport": True,
                "pbl_turbulence": True,
                "convection": convection_active,
                "dry_deposition": False,
                "wet_deposition": False,
                "native_tpcore": True,
                "transport_fill_negative_values": True,
                "transport_orders_i_j_k": [3, 3, 7],
                "native_do_tend": True,
            },
        },
    }


class ConvectionPreparationTests(unittest.TestCase):
    def test_renders_only_convection_as_the_ab_switch(self) -> None:
        rendered = []
        for convection_active in (False, True):
            text = render_tpcore_config(CONFIG_TEMPLATE, manifest(convection_active))
            self.assertNotIn("__PLUME_", text)
            config = yaml.safe_load(text)
            operations = config["operations"]
            self.assertTrue(operations["transport"]["gcclassic_tpcore"]["activate"])
            self.assertTrue(operations["pbl_mixing"]["activate"])
            self.assertFalse(operations["pbl_mixing"]["use_non_local_pbl"])
            self.assertIs(operations["convection"]["activate"], convection_active)
            self.assertFalse(operations["dry_deposition"]["activate"])
            self.assertFalse(operations["wet_deposition"]["activate"])
            rendered.append(config)
        rendered[0]["operations"]["convection"] = rendered[1]["operations"]["convection"]
        self.assertEqual(rendered[0], rendered[1])

    def test_contract_rejects_pbl_off(self) -> None:
        invalid = copy.deepcopy(manifest(False))
        invalid["run"]["operators"]["pbl_turbulence"] = False
        with self.assertRaisesRegex(ValueError, "pbl_turbulence"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_contract_rejects_missing_donor_diagnostic_environment(self) -> None:
        invalid = manifest(True)
        del invalid["runtime_contract"]["donor_diagnostics_environment"]
        with self.assertRaisesRegex(ValueError, "donor diagnostics"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)


if __name__ == "__main__":
    unittest.main()
