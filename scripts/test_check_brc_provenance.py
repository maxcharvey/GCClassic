import copy
import tempfile
import unittest
from pathlib import Path

from check_brc_provenance import (LABEL_FIELDS, REPOSITORIES, REQUIRED_ROLES,
                                  REVIEW_ROLES, check_record, sha256)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / "fixture.txt"
        self.artifact.write_text("fixture, not real simulation data\n")
        artifacts = []
        for role in sorted(REQUIRED_ROLES):
            path = self.root / (role + ".txt")
            path.write_text(role + " fixture\n")
            artifacts.append({"role": role, "path": path.name, "sha256": sha256(path)})
        self.artifact = self.root / artifacts[0]["path"]
        self.record = {
            "schema_version": 1, "run_id": "UNIT_TEST", "purpose": "engineering",
            "definition": {key: "explicit fixture definition" for key in LABEL_FIELDS},
            "sources": {key: {"commit": "a" * 40, "ref": "test", "dirty": False}
                        for key in REPOSITORIES},
            "radiation": {"code": "RRTMG", "flux_convention": "full minus masked",
                          "temporal_sampling": "hourly means",
                          "diagnostic_fields": ["RadSWTOABRC"]},
            "absorption": {"method": "unavailable"},
            "artifacts": artifacts,
            "qualification": {"status": "engineering_only", "optics": "placeholder",
                              "limitations": "Engineering fixture only"},
        }

    def check(self, record=None, verify=True):
        return check_record(self.record if record is None else record, self.root, verify)

    def test_complete_engineering_record(self):
        self.assertEqual(self.check()["status"], "PASS")
        self.assertTrue(self.check()["files_verified"])

    def test_each_definition_required(self):
        for name in LABEL_FIELDS:
            with self.subTest(name=name):
                record = copy.deepcopy(self.record)
                del record["definition"][name]
                self.assertEqual(self.check(record)["status"], "FAIL")

    def test_short_sha_or_dirty_source_rejected(self):
        self.record["sources"]["geos-chem"]["commit"] = "abcdef0"
        self.assertEqual(self.check()["status"], "FAIL")
        self.record["sources"]["geos-chem"]["commit"] = "a" * 40
        self.record["sources"]["geos-chem"]["dirty"] = True
        self.assertEqual(self.check()["status"], "FAIL")

    def test_modified_artifact_rejected(self):
        self.artifact.write_text("changed\n")
        self.assertEqual(self.check()["status"], "FAIL")

    def test_missing_artifact_rejected(self):
        self.artifact.unlink()
        self.assertEqual(self.check()["status"], "FAIL")
        self.assertEqual(self.check(verify=False)["status"], "PASS")
        self.assertFalse(self.check(verify=False)["files_verified"])

    def test_missing_artifact_role_rejected(self):
        self.record["artifacts"].pop()
        self.assertEqual(self.check()["status"], "FAIL")

    def test_placeholder_cannot_be_science(self):
        self.record["purpose"] = "science"
        self.assertEqual(self.check()["status"], "FAIL")

    def test_science_needs_all_hashed_reviews(self):
        self.record["purpose"] = "science"
        self.record["qualification"]["optics"] = "qualified"
        self.assertEqual(self.check()["status"], "FAIL")
        for role in REVIEW_ROLES:
            self.record["artifacts"].append({"role": role, "path": "fixture.txt",
                                             "sha256": sha256(self.root / "fixture.txt")})
        self.assertEqual(self.check()["status"], "FAIL")
        self.record["qualification"].update(status="reviewed_for_scope", reviewer="Test reviewer",
                                             review_date="2026-09-21", scope="Synthetic unit fixture")
        result = self.check()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["science_approval"], "not conferred by this checker")

    def test_separate_means_cannot_be_derived_aaod(self):
        self.record["absorption"] = {"method": "paired_instantaneous_aod_ssa",
                                    "sampling": "hourly means", "same_bins": True,
                                    "evidence": "fixture", "aod_fields": ["AOD"], "ssa_fields": ["SSA"]}
        self.record["artifacts"].append({"role": "absorption_output", "path": "fixture.txt",
                                         "sha256": sha256(self.root / "fixture.txt")})
        self.assertEqual(self.check()["status"], "FAIL")
        self.record["absorption"]["sampling"] = "instantaneous"
        self.assertEqual(self.check()["status"], "PASS")
        self.record["absorption"]["same_bins"] = False
        self.assertEqual(self.check()["status"], "FAIL")

    def test_online_aaod_needs_archived_fields_and_output(self):
        self.record["absorption"] = {"method": "online_aaod", "evidence": "assertion only"}
        self.assertEqual(self.check()["status"], "FAIL")

    def test_roles_cannot_all_use_one_file(self):
        for artifact in self.record["artifacts"]:
            artifact.update(path="fixture.txt", sha256=sha256(self.root / "fixture.txt"))
        self.assertEqual(self.check()["status"], "FAIL")

    def test_malformed_types_fail_without_crashing(self):
        self.assertEqual(self.check([])["status"], "FAIL")
        record = copy.deepcopy(self.record)
        record["artifacts"][0]["role"] = []
        self.assertEqual(self.check(record)["status"], "FAIL")
        for key in ("definition", "sources", "radiation", "absorption", "qualification", "artifacts"):
            with self.subTest(key=key):
                record = copy.deepcopy(self.record)
                record[key] = None
                self.assertEqual(self.check(record)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
