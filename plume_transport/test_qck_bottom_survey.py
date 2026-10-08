from __future__ import annotations

import unittest

from validate_qck_bottom_survey import normalized_records, validate_records


SPECIES = ["A", "B"]


def record(status: str, deficit: float, available: float, tolerance: float) -> dict:
    immediate = min(available, deficit / 2.0)
    shortfall = max(deficit - available, 0.0)
    created = deficit - min(deficit, immediate)
    return {
        "schema_version": "qck-bottom-survey-v1",
        "run_id": "one",
        "model_date": 20190101,
        "model_time": 0,
        "elapsed_seconds": 0,
        "omp_thread_count": 1,
        "species_index": 1,
        "i_tpcore": 1,
        "j_tpcore": 2,
        "k_tpcore": 72,
        "feasibility_status": status,
        "deficit_hpa": deficit,
        "full_column_available_hpa": available,
        "shortfall_hpa": shortfall,
        "event_tolerance_hpa": tolerance,
        "immediate_donor_hpa": immediate,
        "native_withdrawn_hpa": min(deficit, immediate),
        "native_mass_created_hpa": created,
        "deficit_kg": deficit,
        "full_column_available_kg": available,
        "shortfall_kg": shortfall,
        "native_mass_created_kg": created,
        "area_m2": 1.0,
        "behavior": "native_immediate_donor_v1",
    }


class SurveyValidationTests(unittest.TestCase):
    def test_exact_and_unfillable_summary(self) -> None:
        exact = record("exact", 2.0, 3.0, 2.0e-9)
        failed = record("materially_unfillable", 2.0, 1.0, 2.0e-9)
        failed["i_tpcore"] = 2
        result = validate_records([exact, failed], SPECIES)
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["materially_unfillable_event_count"], 1)
        self.assertEqual(result["maximum_species_call_shortfall_kg"], 1.0)
        self.assertEqual(
            result["materially_unfillable_by_species"]["A"]["event_count"], 1
        )

    def test_roundoff_boundary(self) -> None:
        result = validate_records(
            [record("roundoff_feasible", 2.0, 2.0 - 1.0e-9, 2.0e-9)],
            SPECIES,
        )
        self.assertEqual(result["status_counts"]["roundoff_feasible"], 1)

    def test_exact_allows_rounded_inventory_sum_within_tolerance(self) -> None:
        result = validate_records(
            [record("exact", 2.0, 2.0 - 1.0e-12, 2.0e-9)],
            SPECIES,
        )
        self.assertEqual(result["status_counts"]["exact"], 1)

    def test_unfillable_within_tolerance_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "within tolerance"):
            validate_records(
                [record("materially_unfillable", 2.0, 2.0 - 1.0e-9, 2.0e-9)],
                SPECIES,
            )

    def test_thread_provenance_is_normalized(self) -> None:
        one = record("exact", 2.0, 3.0, 2.0e-9)
        eight = dict(one, run_id="eight", omp_thread_count=8)
        self.assertEqual(normalized_records([one]), normalized_records([eight]))


if __name__ == "__main__":
    unittest.main()
