#!/usr/bin/env python3
"""Focused tests for the FIREX-AQ logical/header inventory validator."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import yaml

from validate_firex_aq_inventory import (
    EXPECTED_ABSORPTION_FIELDS,
    EXPECTED_MERGE_FILES,
    build_report,
    has_explicit_standard_conditions,
    read_icartt_header,
    validate_logical_contract,
)


def valid_contract() -> dict:
    return {
        "observation_space": {
            "state": "dry_instrument_standard_conditions",
            "absorption": [
                {"field": field, "wavelength_nm": wavelength, "unit": "Mm-1"}
                for field, wavelength in zip(
                    EXPECTED_ABSORPTION_FIELDS, [405, 532, 664]
                )
            ],
            "aae": {"endpoint_wavelengths_nm": [405, 664]},
            "rejected_middle_wavelength_nm": 488,
        },
        "merge_files": EXPECTED_MERGE_FILES,
        "derived_products": {
            "non_bc_absorption_residual": {
                "status": "blocked_pending_separate_bc_optical_operator"
            }
        },
        "acquisition_gate": {"payloads_present": False},
        "qc": {"retain_finite_negative_absorption": True},
    }


class FirexAqInventoryTests(unittest.TestCase):
    def test_frozen_logical_contract_passes(self) -> None:
        self.assertEqual(validate_logical_contract(valid_contract()), [])

    def test_provisional_488_middle_band_fails(self) -> None:
        contract = deepcopy(valid_contract())
        contract["observation_space"]["absorption"][1]["wavelength_nm"] = 488
        errors = validate_logical_contract(contract)
        self.assertTrue(any("wavelengths" in error for error in errors))

    def test_non_bc_residual_cannot_be_unblocked(self) -> None:
        contract = deepcopy(valid_contract())
        contract["derived_products"]["non_bc_absorption_residual"]["status"] = "ready"
        errors = validate_logical_contract(contract)
        self.assertTrue(any("non-BC" in error for error in errors))

    def test_icartt_header_count_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.ict"
            path.write_text("3,1001\nmetadata\nTime,abs_dry_405\n1,2\n", encoding="utf-8")
            self.assertEqual(len(read_icartt_header(path)), 3)

    def test_manifest_only_report_does_not_claim_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inventory.yml"
            path.write_text(
                yaml.safe_dump(valid_contract(), sort_keys=False),
                encoding="utf-8",
            )
            report = build_report(path, None)
            self.assertEqual(report["result"], "pass")
            self.assertEqual(report["mode"], "logical_contract")
            self.assertEqual(report["payload_provenance"], [])

    def test_stp_label_without_numeric_definition_is_insufficient(self) -> None:
        header = "abs_dry_405, Mm-1, AerOpt_Absorption_PM2.5_STP"
        self.assertFalse(has_explicit_standard_conditions(header))

    def test_numeric_standard_temperature_and_pressure_are_accepted(self) -> None:
        header = "STP convention: standard temperature 273.15 K; pressure 1013.25 hPa"
        self.assertTrue(has_explicit_standard_conditions(header))


if __name__ == "__main__":
    unittest.main()
