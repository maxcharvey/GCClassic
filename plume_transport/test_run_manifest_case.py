#!/usr/bin/env python3
"""Focused tests for manifest-derived wet/aging runtime launch contracts."""

from __future__ import annotations

import copy
from pathlib import Path
import unittest

from run_manifest_case import runtime_record, select_runtime_environment


def wetdep_manifest(threads: int = 1) -> dict:
    manifest_id = "PLUME-012-wetdep-runtime-test"
    return {
        "case_id": "wetdep-runtime-test-20190101",
        "preparation_contract": "stage1-wet-deposition-v1",
        "acceptance": {"contract_version": "stage1-tpcore-causality-v2"},
        "run": {"omp_threads": threads},
        "checkpoint_runtime": {
            "environment": {
                "GC_PLUME_CHECKPOINTS": "1",
                "GC_PLUME_CHECKPOINT_DIR": "./OutputDir/PlumeCheckpoints",
                "GC_PLUME_CHECKPOINT_RUN_ID": "wetdep-runtime-test-20190101",
            }
        },
        "tpcore_budget_runtime": {
            "environment": {
                "GC_PLUME_TPCORE_BUDGETS": "1",
                "GC_PLUME_TPCORE_BUDGET_FILE": "./OutputDir/plume_tpcore_budget_v2.csv",
                "GC_PLUME_TPCORE_BUDGET_MANIFEST_ID": manifest_id,
                "GC_PLUME_TPCORE_BUDGET_RUN_ID": "wetdep-runtime-test-20190101",
            }
        },
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
            "omp_num_threads": threads,
        },
        "ras_surface_reevap_runtime": {
            "enabled": True,
            "schema_version": "ras-surface-reevap-ledger-v1",
            "manifest_id": manifest_id,
            "environment": {
                "GC_RAS_SURFACE_REEVAP_LEDGER": "1",
                "GC_RAS_SURFACE_REEVAP_LEDGER_FILE": "./OutputDir/ras_surface_reevap.csv",
                "GC_RAS_SURFACE_REEVAP_LEDGER_RUN_ID": "wetdep-runtime-test-20190101",
                "GC_RAS_SURFACE_REEVAP_LEDGER_MANIFEST_ID": manifest_id,
            },
        },
    }


def aging_manifest(threads: int = 1, enabled: bool = False) -> dict:
    result = copy.deepcopy(wetdep_manifest(threads))
    manifest_id = "PLUME-012-aging-runtime-test"
    result["case_id"] = "aging-runtime-test-20190101"
    result["preparation_contract"] = "stage1-aging-v1"
    result["run"]["operators"] = {"aging": enabled}
    result["checkpoint_runtime"]["environment"][
        "GC_PLUME_CHECKPOINT_AGED_POOLS"
    ] = "1"
    result["ras_surface_reevap_runtime"] = {
        "enabled": True,
        "schema_version": "ras-surface-reevap-ledger-v1",
        "manifest_id": manifest_id,
        "environment": {
            "GC_RAS_SURFACE_REEVAP_LEDGER": "1",
            "GC_RAS_SURFACE_REEVAP_LEDGER_FILE": "./OutputDir/ras_surface_reevap.csv",
            "GC_RAS_SURFACE_REEVAP_LEDGER_RUN_ID": "aging-runtime-test-20190101",
            "GC_RAS_SURFACE_REEVAP_LEDGER_MANIFEST_ID": manifest_id,
            "GC_RAS_SURFACE_REEVAP_INCLUDE_AGED": "1",
        },
    }
    environment = {
        "GC_PLUME_AGING_LIFETIME_S": "99360",
        "GC_PLUME_AGING_FILE": "./OutputDir/plume_aging_v1.csv",
        "GC_PLUME_AGING_RUN_ID": "aging-runtime-test-20190101",
        "GC_PLUME_AGING_MANIFEST_ID": manifest_id,
    }
    if enabled:
        environment["GC_PLUME_AGING"] = "1"
    result["aging_runtime"] = {
        "enabled": True,
        "schema_version": "plume-aging-ledger-v1",
        "lifetime_s": 99360,
        "manifest_id": manifest_id,
        "clear_environment": ["GC_PLUME_AGING"],
        "environment": environment,
    }
    return result


class RunManifestCaseTests(unittest.TestCase):
    def test_selects_complete_survey_free_environment(self) -> None:
        selected, unset = select_runtime_environment(wetdep_manifest())
        self.assertEqual(selected["OMP_NUM_THREADS"], "1")
        self.assertEqual(selected["GC_RAS_SURFACE_REEVAP_LEDGER"], "1")
        self.assertEqual(
            selected["GC_RAS_SURFACE_REEVAP_LEDGER_MANIFEST_ID"],
            "PLUME-012-wetdep-runtime-test",
        )
        self.assertEqual(
            unset,
            (
                "GC_QCK_BOTTOM_SURVEY",
                "GC_QCK_BOTTOM_SURVEY_RUN_ID",
                "GC_QCK_BOTTOM_SURVEY_FILE",
            ),
        )

    def test_rejects_thread_mismatch(self) -> None:
        invalid = wetdep_manifest()
        invalid["runtime_contract"]["omp_num_threads"] = 8
        with self.assertRaisesRegex(ValueError, "OMP thread"):
            select_runtime_environment(invalid)

    def test_rejects_conflicting_runtime_environment(self) -> None:
        invalid = copy.deepcopy(wetdep_manifest())
        invalid["checkpoint_runtime"]["environment"]["GC_RAS_SURFACE_REEVAP_LEDGER"] = "0"
        with self.assertRaisesRegex(ValueError, "conflicts"):
            select_runtime_environment(invalid)

    def test_runtime_record_has_resolved_manifest_provenance(self) -> None:
        manifest = wetdep_manifest()
        selected, unset = select_runtime_environment(manifest)
        record = runtime_record(Path("test.yml"), manifest, selected, unset)
        self.assertEqual(record["case_id"], manifest["case_id"])
        self.assertEqual(record["selected_environment"], selected)
        self.assertEqual(record["unset_environment"], list(unset))
        self.assertEqual(len(record["resolved_manifest_sha256_at_launch"]), 64)

    def test_aging_gate_is_manifest_selected_and_precleared(self) -> None:
        off_selected, off_unset = select_runtime_environment(aging_manifest())
        self.assertNotIn("GC_PLUME_AGING", off_selected)
        self.assertIn("GC_PLUME_AGING", off_unset)

        on_selected, on_unset = select_runtime_environment(aging_manifest(enabled=True))
        self.assertEqual(on_selected["GC_PLUME_AGING"], "1")
        self.assertIn("GC_PLUME_AGING", on_unset)
        self.assertEqual(on_selected["GC_PLUME_AGING_LIFETIME_S"], "99360")


if __name__ == "__main__":
    unittest.main()
