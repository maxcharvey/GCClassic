#!/usr/bin/env python3
"""Focused preparation tests for stage1-pbl-mixing-v1."""

from __future__ import annotations

import copy
from pathlib import Path
import unittest

import yaml

from prepare_run import PBL_MIXING_PREPARATION_CONTRACT, render_tpcore_config


DIRECTORY = Path(__file__).resolve().parent
CONFIG_TEMPLATE = DIRECTORY / "templates/geoschem_config.pbl.yml"


def manifest(pbl_active: bool) -> dict:
    return {
        "preparation_contract": PBL_MIXING_PREPARATION_CONTRACT,
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
                "pbl_turbulence": pbl_active,
                "convection": False,
                "dry_deposition": False,
                "wet_deposition": False,
                "native_tpcore": True,
                "transport_fill_negative_values": True,
                "transport_orders_i_j_k": [3, 3, 7],
                "native_do_tend": True,
            },
        },
    }


class PblPreparationTests(unittest.TestCase):
    def test_renders_only_pbl_as_the_ab_switch(self) -> None:
        rendered = []
        for pbl_active in (False, True):
            text = render_tpcore_config(CONFIG_TEMPLATE, manifest(pbl_active))
            self.assertNotIn("__PLUME_", text)
            config = yaml.safe_load(text)
            operations = config["operations"]
            self.assertTrue(operations["transport"]["gcclassic_tpcore"]["activate"])
            self.assertIs(operations["pbl_mixing"]["activate"], pbl_active)
            self.assertFalse(operations["pbl_mixing"]["use_non_local_pbl"])
            self.assertFalse(operations["convection"]["activate"])
            self.assertFalse(operations["dry_deposition"]["activate"])
            self.assertFalse(operations["wet_deposition"]["activate"])
            rendered.append(config)
        rendered[0]["operations"]["pbl_mixing"] = rendered[1]["operations"][
            "pbl_mixing"
        ]
        self.assertEqual(rendered[0], rendered[1])

    def test_contract_rejects_convection(self) -> None:
        invalid = copy.deepcopy(manifest(True))
        invalid["run"]["operators"]["convection"] = True
        with self.assertRaisesRegex(ValueError, "convection"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_contract_rejects_noncausal_manifest(self) -> None:
        invalid = manifest(True)
        invalid["acceptance"]["contract_version"] = "stage1-tpcore-ledger-v1"
        with self.assertRaisesRegex(ValueError, "causality-v2"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)

    def test_contract_rejects_missing_cell_diagnostic_environment(self) -> None:
        invalid = manifest(True)
        del invalid["runtime_contract"]["cell_diagnostics_environment"]
        with self.assertRaisesRegex(ValueError, "cell diagnostics"):
            render_tpcore_config(CONFIG_TEMPLATE, invalid)


if __name__ == "__main__":
    unittest.main()
