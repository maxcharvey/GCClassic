import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_brc_submodule_contract as contract


URLS = {
    "src/GEOS-Chem": "https://github.com/maxcharvey/geos-chem.git",
    "src/HEMCO": "https://github.com/maxcharvey/HEMCO.git",
    "src/Cloud-J": "https://github.com/maxcharvey/Cloud-J.git",
}
WRAPPER_URL = "https://github.com/maxcharvey/GCClassic.git"


def run(directory, *args):
    subprocess.run(args, cwd=directory, check=True, text=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class SubmoduleContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "wrapper"
        self.root.mkdir()
        self.init_repo(self.root)
        run(self.root, "git", "remote", "add", "origin", WRAPPER_URL)
        entries = []
        for path, url in URLS.items():
            source = Path(self.tmp.name) / (path.replace("/", "_") + "_source")
            source.mkdir()
            self.init_repo(source)
            (source / "README").write_text(path)
            run(source, "git", "add", "README")
            run(source, "git", "commit", "-m", "child")
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            run(self.root, "git", "clone", "--quiet", str(source), str(target))
            self.configure_identity(target)
            run(target, "git", "remote", "set-url", "origin", url)
            entries.extend((f'[submodule "{path}"]', f"\tpath = {path}", f"\turl = {url}"))

        (self.root / ".gitmodules").write_text("\n".join(entries) + "\n")
        # A manually assembled fixture needs the same local registration that
        # `git submodule update --init` would create in a real checkout.
        for path, url in URLS.items():
            run(self.root, "git", "config", f"submodule.{path}.url", url)
            run(self.root, "git", "config", f"submodule.{path}.active", "true")
        run(self.root, "git", "add", ".gitmodules", *URLS)
        run(self.root, "git", "commit", "-m", "wrapper")

    @staticmethod
    def configure_identity(path):
        run(path, "git", "config", "user.email", "test@example.invalid")
        run(path, "git", "config", "user.name", "test")

    @classmethod
    def init_repo(cls, path):
        run(path, "git", "init", "--quiet")
        cls.configure_identity(path)

    def report(self):
        return contract.check_contract(self.root, expected_urls=URLS)

    def remote_report(self, mode):
        original_git = contract.git

        def mocked_git(repo, *args):
            if args[:1] == ("ls-remote",):
                local_head = original_git(repo, "rev-parse", "HEAD").strip()
                if mode == "match":
                    return f"{local_head}\trefs/heads/integration/brc-14.8.0\n"
                if mode == "different":
                    return f"{'0' * 40}\trefs/heads/integration/brc-14.8.0\n"
                if mode == "absent":
                    return ""
                if mode == "failure":
                    raise contract.GitError("mock remote failure")
            return original_git(repo, *args)

        with patch.object(contract, "git", side_effect=mocked_git):
            return contract.check_contract(self.root, remote=True, expected_urls=URLS)

    def test_matching_contract_passes(self):
        self.assertEqual(self.report()["status"], "PASS")

    def test_gitlink_mismatch_fails(self):
        child = self.root / "src/HEMCO"
        (child / "new_file").write_text("changed")
        run(child, "git", "add", "new_file")
        run(child, "git", "commit", "-m", "drift")
        report = self.report()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("not initialized/exact" in error for error in report["errors"]))

    def test_uninitialized_submodule_fails(self):
        shutil.rmtree(self.root / "src/Cloud-J")
        report = self.report()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("not initialized/exact" in error for error in report["errors"]))

    def test_dirty_submodule_fails(self):
        (self.root / "src/GEOS-Chem" / "untracked").write_text("dirty")
        report = self.report()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("src/GEOS-Chem: dirty" in error for error in report["errors"]))

    def test_dirty_wrapper_fails(self):
        (self.root / "untracked").write_text("dirty")
        report = self.report()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("wrapper: dirty" in error for error in report["errors"]))

    def test_nested_gitlink_mismatch_fails(self):
        parent = self.root / "src/GEOS-Chem"
        source = Path(self.tmp.name) / "nested_source"
        source.mkdir()
        self.init_repo(source)
        (source / "README").write_text("nested")
        run(source, "git", "add", "README")
        run(source, "git", "commit", "-m", "nested")
        nested = parent / "nested"
        run(parent, "git", "clone", "--quiet", str(source), str(nested))
        self.configure_identity(nested)
        (parent / ".gitmodules").write_text(
            '[submodule "nested"]\n\tpath = nested\n\turl = https://example.invalid/nested.git\n'
        )
        run(parent, "git", "config", "submodule.nested.url", "https://example.invalid/nested.git")
        run(parent, "git", "config", "submodule.nested.active", "true")
        run(parent, "git", "add", ".gitmodules", "nested")
        run(parent, "git", "commit", "-m", "register nested")
        run(self.root, "git", "add", "src/GEOS-Chem")
        run(self.root, "git", "commit", "-m", "record nested gitlink")
        (nested / "drift").write_text("drift")
        run(nested, "git", "add", "drift")
        run(nested, "git", "commit", "-m", "nested drift")
        report = self.report()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("src/GEOS-Chem/nested: recursive gitlink" in error
                            for error in report["errors"]))

    def test_url_drift_fails(self):
        run(self.root, "git", "config", "-f", ".gitmodules", "submodule.src/HEMCO.url",
            "https://example.invalid/not-hemco.git")
        report = self.report()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(".gitmodules URL" in error for error in report["errors"]))

    def test_remote_matching_refs_pass(self):
        report = self.remote_report("match")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["remotes"]), 4)
        self.assertTrue(all(item["origin_url"] == item["expected_origin"]
                            for item in report["remotes"]))

    def test_remote_absent_ref_fails(self):
        report = self.remote_report("absent")
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("is absent" in error for error in report["errors"]))

    def test_remote_different_ref_fails(self):
        report = self.remote_report("different")
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("not local HEAD" in error for error in report["errors"]))

    def test_remote_failure_fails_closed(self):
        report = self.remote_report("failure")
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("subprocess/check failure" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
