#!/usr/bin/env python3
"""Parser and configuration-rendering tests for the Phase-B TPCORE ledger."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import h5py
import numpy as np
import yaml

from prepare_run import render_tpcore_config
from validate_tpcore_budget import (
    AGING_TAGS,
    COLUMNS_V1,
    COLUMNS_V2,
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
    budget_interval_durations_s,
    read_budget_record_time,
    read_checkpoint_masses,
    read_ledger,
)


TEMPLATE = Path(__file__).resolve().parent / "templates/geoschem_config.tpcore.yml"


def manifest(fill_negative_values: bool) -> dict:
    return {
        "run": {
            "start": "2019-01-01T00:00:00Z",
            "end": "2019-01-01T00:20:00Z",
            "transport_timestep_s": 600,
            "chemistry_timestep_s": 1200,
            "operators": {
                "chemistry": True,
                "transport": True,
                "pbl_turbulence": False,
                "convection": False,
                "dry_deposition": False,
                "wet_deposition": False,
                "native_tpcore": True,
                "transport_fill_negative_values": fill_negative_values,
                "transport_orders_i_j_k": [3, 3, 7],
                "native_do_tend": True,
            },
        }
    }


def record_values(schema_version: str, qckxyz_invoked: int | None) -> dict[str, str]:
    values = {
        "schema_version": schema_version,
        "run_id": "test-run",
        "manifest_id": "test-manifest",
        "model_date": "20190101",
        "model_time": "0",
        "elapsed_seconds": "0",
        "heartbeat_index": "1",
        "omp_thread_count": "1",
        "tpcore_call_index": "1",
        "boundary": "TPCORE_ENTRY",
        "tag": "PLUME_SFC",
        "global_mass_kg": "0.0",
        "boundary_delta_kg": "0.0",
        "global_dry_air_mass_kg": "1.0",
        "negative_cell_count": "0",
        "minimum_mixing_ratio": "0.0",
        "total_negative_mass_kg": "0.0",
        "corrected_cell_count": "0",
        "correction_mass_delta_kg": "0.0",
    }
    if qckxyz_invoked is not None:
        values["qckxyz_invoked"] = str(qckxyz_invoked)
    return values


class TpcoreBudgetTests(unittest.TestCase):
    def test_template_renders_both_reviewed_lfill_values(self) -> None:
        for expected in (True, False):
            rendered = render_tpcore_config(TEMPLATE, manifest(expected))
            configured = yaml.safe_load(rendered)
            actual = configured["operations"]["transport"]["gcclassic_tpcore"][
                "fill_negative_values"
            ]
            self.assertIs(actual, expected)
            self.assertNotIn("__PLUME_TPCORE_FILL_NEGATIVE_VALUES__", rendered)

    def test_template_renders_manifest_timestamps_and_timesteps(self) -> None:
        rendered = render_tpcore_config(TEMPLATE, manifest(True))
        configured = yaml.safe_load(rendered)
        self.assertIn("start_date: [20190101, 000000]", rendered)
        self.assertIn("end_date: [20190101, 002000]", rendered)
        self.assertEqual(configured["timesteps"]["transport_timestep_in_s"], 600)
        self.assertEqual(configured["timesteps"]["chemistry_timestep_in_s"], 1200)

    def test_v1_and_v2_ledgers_parse_with_explicit_schema_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            v1_path = directory / "v1.csv"
            v2_path = directory / "v2.csv"
            for path, columns, schema, invoked in (
                (v1_path, COLUMNS_V1, SCHEMA_VERSION_V1, None),
                (v2_path, COLUMNS_V2, SCHEMA_VERSION_V2, 0),
            ):
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=columns)
                    writer.writeheader()
                    writer.writerow(record_values(schema, invoked))

            v1_record = read_ledger(v1_path)[0]
            v2_record = read_ledger(v2_path)[0]
            self.assertEqual(v1_record.schema_version, SCHEMA_VERSION_V1)
            self.assertIsNone(v1_record.qckxyz_invoked)
            self.assertEqual(v2_record.schema_version, SCHEMA_VERSION_V2)
            self.assertEqual(v2_record.qckxyz_invoked, 0)

    def test_budget_interval_contract_allows_full_or_heartbeat_files(self) -> None:
        self.assertEqual(
            budget_interval_durations_s(1, 2, 600, 1200.0), (1200.0,)
        )
        self.assertEqual(
            budget_interval_durations_s(2, 2, 600, 1200.0), (600.0, 600.0)
        )
        with self.assertRaisesRegex(ValueError, "one full-duration file"):
            budget_interval_durations_s(3, 2, 600, 1200.0)

    def test_budget_record_time_requires_the_reviewed_coordinate_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "Budget.nc4"
            with h5py.File(path, "w") as dataset:
                coordinate = dataset.create_dataset("time", data=np.array([10.0]))
                coordinate.attrs["units"] = "minutes since 2019-01-01 00:00:00"
                coordinate.attrs["calendar"] = "gregorian"
            self.assertEqual(
                read_budget_record_time(path),
                datetime(2019, 1, 1, 0, 10, tzinfo=timezone.utc),
            )

    def test_checkpoint_reader_accepts_the_explicit_ten_pool_aging_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.nc4"
            with h5py.File(path, "w") as dataset:
                tag_ids = dataset.create_dataset("tag_id", data=np.arange(len(AGING_TAGS)))
                tag_ids.attrs["tag_names"] = ",".join(AGING_TAGS)
                dataset.create_dataset(
                    "global_plume_mass", data=np.arange(len(AGING_TAGS), dtype=np.float64)
                )
            masses = read_checkpoint_masses(path, AGING_TAGS)
            self.assertEqual(tuple(masses), AGING_TAGS)
            self.assertEqual(masses["PLUME_PROFILE_PI"], 9.0)


if __name__ == "__main__":
    unittest.main()
