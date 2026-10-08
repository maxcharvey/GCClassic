from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from validate_ras_surface_reevap import FIELDS, SCHEMA, aggregate, normalized_rows, parse_ledger


def sample(**updates):
    row = {
        "schema_version": SCHEMA, "run_id": "run-1", "manifest_id": "m-1",
        "model_date": 20190101, "model_time": 1000, "elapsed_seconds": 600,
        "convection_call_index": 2, "omp_thread_count": 1, "tag": "PLUME_SFC",
        "model_species_id": 1, "advect_id": 1, "wetdep_id": 1,
        "i_gc": 31, "j_gc": 12, "k_gc": 1, "event_count": 2,
        "f_scavenging": 0.0, "area_m2": 2.0, "gained_kg_m2": 4.0,
        "gross_wash_kg_m2": 3.0, "signed_wetloss_kg_m2": -1.0,
        "signed_wetloss_kg": -2.0, "realized_signed_loss_kg": -2.0,
        "state_gain_kg": 2.0,
    }
    row.update(updates)
    return row


class LedgerTests(unittest.TestCase):
    def write(self, rows, fields=FIELDS):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ledger.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_valid_signed_gain_and_aggregate(self):
        rows = parse_ledger(self.write([sample()]))
        self.assertEqual(aggregate(rows)[(600, "PLUME_SFC")]["realized_kg"], -2.0)

    def test_normalization_ignores_only_provenance_and_threads(self):
        a = sample()
        b = sample(run_id="other", manifest_id="other-m", omp_thread_count=8)
        self.assertEqual(normalized_rows([a]), normalized_rows([b]))

    def test_rejects_bad_header_duplicate_nonfinite_and_identity(self):
        with self.assertRaisesRegex(ValueError, "header"):
            parse_ledger(self.write([sample()], FIELDS[:-1]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_ledger(self.write([sample(), sample()]))
        with self.assertRaisesRegex(ValueError, "non-finite"):
            parse_ledger(self.write([sample(area_m2=float("nan"))]))
        with self.assertRaisesRegex(ValueError, "mass conversion"):
            parse_ledger(self.write([sample(signed_wetloss_kg=-3.0)]))

    def test_rejects_wrong_level_fraction_tag_and_order(self):
        for key, value, message in (
            ("k_gc", 2, "surface"), ("f_scavenging", 0.1, "exact zero"),
            ("tag", "OCPO", "tag"),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                parse_ledger(self.write([sample(**{key: value})]))
        later = sample(tag="PLUME_PBL", model_species_id=2, advect_id=2, wetdep_id=2)
        with self.assertRaisesRegex(ValueError, "row order"):
            parse_ledger(self.write([later, sample()]))


if __name__ == "__main__":
    unittest.main()
