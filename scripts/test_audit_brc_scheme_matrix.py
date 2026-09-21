import unittest
import numpy as np
from audit_brc_scheme_matrix import check_rates


class SchemeTests(unittest.TestCase):
    def test_zero_is_exact(self):
        tau = np.array([1e8, 1e8])
        zero = np.zeros(2)
        self.assertEqual(check_rates(0, tau, zero, zero, zero), [])
        self.assertTrue(check_rates(0, tau, 1 / tau, zero, zero))

    def test_one_day(self):
        tau = np.full(2, 86400.)
        self.assertEqual(check_rates(1, tau, 1 / tau, np.ones(2), np.ones(2)), [])

    def test_altitude_regimes_required(self):
        tau = np.array([86400., 1e8])
        self.assertEqual(check_rates(2, tau, 1 / tau, np.ones(2), np.ones(2)), [])
        tau[:] = 86400.
        self.assertTrue(check_rates(2, tau, 1 / tau, np.ones(2), np.ones(2)))

    def test_viscosity_response(self):
        tau = np.array([21600., 1e8])
        for scheme in (3, 4):
            self.assertEqual(check_rates(scheme, tau, 1 / tau, np.ones(2), np.ones(2)), [])
        self.assertTrue(check_rates(4, tau, np.zeros(2), np.ones(2), np.ones(2)))

    def test_nonfinite_fails(self):
        self.assertTrue(check_rates(4, np.array([np.nan]), np.ones(1), np.ones(1), np.ones(1)))

    def test_empty_fails(self):
        self.assertTrue(check_rates(0, *(np.array([]) for _ in range(4))))

    def test_broadcastable_shape_mismatch_fails(self):
        self.assertTrue(check_rates(1, np.full((2, 1), 86400.), np.full((1, 2), 1 / 86400.),
                                    np.ones((2, 1)), np.ones((2, 1))))
