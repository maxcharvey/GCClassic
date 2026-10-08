#!/usr/bin/env python3
"""Mathematical regression matrix for native and conservative Qck behavior.

These tests are an explicit algebraic companion to the runtime Fortran tests:
they document the current bottom update and the conservation policy boundary,
but they do not replace a compiled GEOS-Chem integration run.
"""

from __future__ import annotations

import unittest


def native_interior_update(above: float, target: float, below: float) -> tuple[float, float, float]:
    """Apply the native interior Qck algebra to one vertical three-cell stencil."""

    if target >= 0.0:
        raise ValueError("interior regression input must have a negative target")
    deficit = -target
    withdrawn = min(deficit, above)
    return above - withdrawn, 0.0, below + withdrawn - deficit


def native_bottom_update(column: list[float]) -> tuple[list[float], float]:
    """Apply the native bottom Qck algebra and return its artificial mass delta."""

    if len(column) < 2 or column[-1] >= 0.0:
        raise ValueError("bottom regression input needs a negative bottom cell")
    updated = list(column)
    deficit = -updated[-1]
    immediate = updated[-2]
    withdrawn = min(deficit, immediate)
    updated[-2] = immediate - withdrawn
    updated[-1] = 0.0
    return updated, deficit - withdrawn


def nonnegative_conservative_correction_is_possible(column: list[float]) -> bool:
    """A redistribution can make a finite column nonnegative iff its total is nonnegative."""

    return sum(column) >= 0.0


def conservative_bottom_update(
    column: list[float],
    relative_tolerance: float = 1.0e-9,
    absolute_tolerance: float = 1.0e-30,
    microclosure_tolerance: float = 0.0,
) -> tuple[list[float], str, float, int]:
    """Mirror the staged full-column QCK_BOTTOM policy in small exact cases."""

    if len(column) < 2 or column[-1] >= 0.0:
        raise ValueError("bottom regression input needs a negative bottom cell")
    if (
        relative_tolerance < 0.0
        or absolute_tolerance < 0.0
        or microclosure_tolerance < 0.0
    ):
        raise ValueError("correction tolerances must be non-negative")

    updated = list(column)
    deficit = -updated[-1]
    available = 0.0
    for donor in reversed(updated[:-1]):
        if donor > 0.0:
            available += donor
    tolerance = max(absolute_tolerance, relative_tolerance * max(deficit, available))
    for donor in reversed(updated[:-1]):
        if donor < -tolerance:
            raise ValueError("materially negative donor violates the precondition")

    remaining = deficit
    for donor in reversed(updated[:-1]):
        if donor <= 0.0:
            continue
        if donor >= remaining:
            remaining = 0.0
            break
        remaining -= donor
    if remaining > tolerance and (
        microclosure_tolerance <= 0.0 or remaining > microclosure_tolerance
    ):
        raise ValueError("full donor column is materially insufficient")

    if remaining > 0.0:
        donor_count = 0
        for index in range(len(updated) - 2, -1, -1):
            if updated[index] > 0.0:
                updated[index] = 0.0
                donor_count += 1
        updated[-1] = 0.0
        outcome = (
            "roundoff_closed" if remaining <= tolerance else "microclosure_closed"
        )
        return updated, outcome, remaining, donor_count

    donor_count = 0
    remaining = deficit
    for index in range(len(updated) - 2, -1, -1):
        if updated[index] <= 0.0:
            continue
        withdrawn = min(remaining, updated[index])
        updated[index] -= withdrawn
        donor_count += 1
        remaining -= withdrawn
        if remaining <= 0.0:
            break
    updated[-1] = 0.0
    return updated, "exact", 0.0, donor_count


class QckxyzRegressionMatrix(unittest.TestCase):
    def test_interior_correction_is_conservative(self) -> None:
        initial = (7.0, -10.0, 4.0)
        updated = native_interior_update(*initial)
        self.assertEqual(updated, (0.0, 0.0, 1.0))
        self.assertEqual(sum(updated), sum(initial))

    def test_bottom_shortfall_creates_mass(self) -> None:
        initial = [7.0, -10.0]
        updated, mass_delta = native_bottom_update(initial)
        self.assertEqual(updated, [0.0, 0.0])
        self.assertEqual(mass_delta, 3.0)
        self.assertEqual(sum(updated) - sum(initial), 3.0)

    def test_farther_up_donor_makes_conservative_redistribution_feasible(self) -> None:
        initial = [8.0, 7.0, -10.0]
        updated, mass_delta = native_bottom_update(initial)
        self.assertEqual(updated, [8.0, 0.0, 0.0])
        self.assertEqual(mass_delta, 3.0)
        self.assertTrue(nonnegative_conservative_correction_is_possible(initial))
        self.assertEqual(sum(initial), 5.0)

    def test_conservative_policy_preserves_immediate_donor_result(self) -> None:
        initial = [10.0, -7.0]
        updated, outcome, closure, donor_count = conservative_bottom_update(initial)
        self.assertEqual(updated, [3.0, 0.0])
        self.assertEqual(outcome, "exact")
        self.assertEqual(closure, 0.0)
        self.assertEqual(donor_count, 1)
        self.assertEqual(sum(updated), sum(initial))

    def test_conservative_policy_uses_farther_donor_without_mass_creation(self) -> None:
        initial = [8.0, 7.0, -10.0]
        updated, outcome, closure, donor_count = conservative_bottom_update(initial)
        self.assertEqual(updated, [5.0, 0.0, 0.0])
        self.assertEqual(outcome, "exact")
        self.assertEqual(closure, 0.0)
        self.assertEqual(donor_count, 2)
        self.assertEqual(sum(updated), sum(initial))

    def test_roundoff_only_closure_is_declared(self) -> None:
        initial = [10.0 - 1.0e-12, -10.0]
        updated, outcome, closure, donor_count = conservative_bottom_update(initial)
        self.assertEqual(updated, [0.0, 0.0])
        self.assertEqual(outcome, "roundoff_closed")
        self.assertGreater(closure, 0.0)
        self.assertLessEqual(closure, 1.0e-8)
        self.assertEqual(donor_count, 1)

    def test_no_donor_column_cannot_be_nonnegative_and_conservative(self) -> None:
        initial = [7.0, -10.0]
        _, mass_delta = native_bottom_update(initial)
        self.assertEqual(mass_delta, 3.0)
        self.assertFalse(nonnegative_conservative_correction_is_possible(initial))
        with self.assertRaisesRegex(ValueError, "insufficient"):
            conservative_bottom_update(initial)
        self.assertEqual(initial, [7.0, -10.0])

    def test_microclosure_gate_closes_only_when_enabled(self) -> None:
        initial = [7.0, -10.0]
        updated, outcome, closure, donor_count = conservative_bottom_update(
            initial, microclosure_tolerance=4.0
        )
        self.assertEqual(updated, [0.0, 0.0])
        self.assertEqual(outcome, "microclosure_closed")
        self.assertEqual(closure, 3.0)
        self.assertEqual(donor_count, 1)

    def test_microclosure_over_limit_preserves_fatal_behavior(self) -> None:
        initial = [7.0, -10.0]
        with self.assertRaisesRegex(ValueError, "insufficient"):
            conservative_bottom_update(initial, microclosure_tolerance=2.0)
        self.assertEqual(initial, [7.0, -10.0])

    def test_day5_isop_event_rejects_at_015kg_and_closes_at_025kg(self) -> None:
        area_m2 = 54_582_546_432.0
        g0_100 = 100.0 / 9.80665
        deficit_hpa = 3.98814e-13
        available_hpa = 3.12163e-14
        initial = [available_hpa, -deficit_hpa]
        event_015kg_hpa = 0.15 / (area_m2 * g0_100)
        event_025kg_hpa = 0.25 / (area_m2 * g0_100)

        with self.assertRaisesRegex(ValueError, "insufficient"):
            conservative_bottom_update(
                initial, microclosure_tolerance=event_015kg_hpa
            )
        self.assertEqual(initial, [available_hpa, -deficit_hpa])

        updated, outcome, closure_hpa, donor_count = conservative_bottom_update(
            initial, microclosure_tolerance=event_025kg_hpa
        )
        self.assertEqual(updated, [0.0, 0.0])
        self.assertEqual(outcome, "microclosure_closed")
        self.assertEqual(donor_count, 1)
        self.assertAlmostEqual(
            closure_hpa * area_m2 * g0_100,
            0.20460012877533518,
            places=12,
        )

    def test_materially_negative_donor_fails_before_mutation(self) -> None:
        initial = [-1.0, -10.0]
        with self.assertRaisesRegex(ValueError, "negative donor"):
            conservative_bottom_update(initial)
        self.assertEqual(initial, [-1.0, -10.0])


if __name__ == "__main__":
    unittest.main()
