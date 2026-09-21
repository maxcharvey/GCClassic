#!/usr/bin/env python3
"""Synthetic contract tests for compare_planeflight_profiles.py."""

import tempfile
import unittest
from pathlib import Path

from compare_planeflight_profiles import compare


HEADER = "POINT TYPE YYYYMMDD HHMM LAT LON PRESS OBS OCPI FSOAP"


def schedule_for(rows):
    points = []
    for row in rows:
        fields = row.split()
        date = fields[2]
        longitude = float(fields[5]) % 360.
        points.append(f"{fields[0]}{fields[1]} {date[6:8]}-{date[4:6]}-{date[:4]} {fields[3][:2]}:{fields[3][2:]} {fields[4]} {longitude:.2f} {fields[6]} 0")
    return ("Planeflight.dat\nGCST\nWE-CAN\n---\n2\n---\nOCPI\nFSOAP\n---\n"
            "Now give the times and locations of the flight\n---\n"
            "Point Type DD-MM-YYYY HH:MM LAT LON ALT/PRE OBS\n" + "\n".join(points) +
            "\n99999END 00-00-0000 00:00 0 0 0 0\n").encode()


def write_case(root, rows, schedule=None, date="20180801"):
    output = root / "OutputDir"
    output.mkdir(parents=True)
    (root / f"Planeflight.dat.{date}").write_bytes(schedule if schedule is not None else schedule_for(rows))
    (output / f"plane.log.{date}").write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    return output


class PlaneFlightProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.case_number = 0
        self.left_rows = [
            "1 C130 20180801 0000 43.27 -113.86 526.91 0 10 2",
            "2 C130 20180801 0001 43.28 -113.85 650.00 0 20 4",
            "3 C130 20180801 0002 43.29 -113.84 950.00 0 30 6",
        ]
        self.right_rows = [
            "1 C130 20180801 0000 43.27 -113.86 526.91 0 11 3",
            "2 C130 20180801 0001 43.28 -113.85 650.00 0 22 6",
            "3 C130 20180801 0002 43.29 -113.84 950.00 0 33 9",
        ]

    def paths(self, left_rows=None, right_rows=None, left_schedule=None, right_schedule=None):
        self.case_number += 1
        self.left_root = self.root / f"left_{self.case_number}"
        self.right_root = self.root / f"right_{self.case_number}"
        left = write_case(self.left_root, left_rows or self.left_rows, left_schedule)
        right = write_case(self.right_root, right_rows or self.right_rows, right_schedule)
        return left, right

    def test_positive_pair_and_excluded_pressure(self):
        left, right = self.paths()
        result = compare(left, right, self.left_root, self.right_root, ("OCPI", "FSOAP"), (500., 600., 800.))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["excluded_samples_outside_pressure_bins"], 1)
        self.assertEqual(result["pressure_bins"][0]["fields"]["OCPI"]["delta_14_8_minus_14_7"]["median"], 1.)
        self.assertEqual(result["pressure_bins"][1]["fields"]["FSOAP"]["left"]["median"], 4.)
        self.assertEqual(result["units"]["chemical_species"], "molec/cm3")

    def test_unmatched_track_fails(self):
        right = list(self.right_rows)
        right[1] = right[1].replace("0001", "0003", 1)
        left_dir, right_dir = self.paths(right_rows=right, right_schedule=schedule_for(self.left_rows))
        with self.assertRaisesRegex(ValueError, "unmatched track rows"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))

    def test_schedule_mismatch_fails(self):
        left_dir, right_dir = self.paths(right_schedule=b"different schedule\n")
        with self.assertRaisesRegex(ValueError, "schedule SHA-256 differs"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))

    def test_duplicate_track_fails(self):
        schedule = schedule_for(self.left_rows)
        left_dir, right_dir = self.paths(left_rows=self.left_rows + [self.left_rows[0]],
                                         left_schedule=schedule, right_schedule=schedule)
        with self.assertRaisesRegex(ValueError, "duplicate flight key"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))

    def test_sentinel_and_numeric_tracer_fail(self):
        rows = list(self.left_rows)
        rows[0] = rows[0].replace(" 10 2", " -999 2")
        left_dir, right_dir = self.paths(left_rows=rows)
        with self.assertRaisesRegex(ValueError, "missing-value sentinel"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))
        with self.assertRaisesRegex(ValueError, "TRA_\\* numeric"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("TRA_214",), (500., 800.))

    def test_negative_and_nonfinite_chemical_fail(self):
        rows = list(self.left_rows)
        rows[0] = rows[0].replace(" 10 2", " -1 2")
        left_dir, right_dir = self.paths(left_rows=rows)
        with self.assertRaisesRegex(ValueError, "negative chemical"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))
        rows = list(self.left_rows)
        rows[0] = rows[0].replace(" 10 2", " nan 2")
        left_dir, right_dir = self.paths(left_rows=rows)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))

    def test_unknown_field_missing_day_and_coordinate_fail(self):
        left_dir, right_dir = self.paths()
        with self.assertRaisesRegex(ValueError, "lack verified chemical"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("GMAO_PRES",), (500., 800.))
        with self.assertRaisesRegex(ValueError, "missing PlaneFlight days"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.), ("20180802",))
        changed = list(self.right_rows)
        changed[0] = changed[0].replace("43.27", "43.29")
        left_dir, right_dir = self.paths(right_rows=changed, right_schedule=schedule_for(self.left_rows))
        with self.assertRaisesRegex(ValueError, "LAT differs"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))

    def test_header_and_final_pressure_edge_fail_closed(self):
        left_dir, right_dir = self.paths()
        with self.assertRaisesRegex(ValueError, "missing requested/header"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("PBRCPOA",), (500., 800.))
        left_rows = list(self.left_rows)
        right_rows = list(self.right_rows)
        left_rows[2] = left_rows[2].replace("950.00", "800.00")
        right_rows[2] = right_rows[2].replace("950.00", "800.00")
        left_dir, right_dir = self.paths(left_rows=left_rows, right_rows=right_rows)
        result = compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 600., 800.))
        self.assertEqual(result["pressure_bins"][1]["fields"]["OCPI"]["left"]["count"], 2)

    def test_identically_wrong_output_coordinates_fail_schedule(self):
        left_rows = list(self.left_rows)
        right_rows = list(self.right_rows)
        left_rows[0] = left_rows[0].replace("43.27", "43.40")
        right_rows[0] = right_rows[0].replace("43.27", "43.40")
        schedule = schedule_for(self.left_rows)
        left_dir, right_dir = self.paths(left_rows=left_rows, right_rows=right_rows,
                                         left_schedule=schedule, right_schedule=schedule)
        with self.assertRaisesRegex(ValueError, "left LAT differs from input schedule"):
            compare(left_dir, right_dir, self.left_root, self.right_root, ("OCPI",), (500., 800.))


if __name__ == "__main__":
    unittest.main()
