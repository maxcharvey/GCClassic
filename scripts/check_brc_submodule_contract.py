#!/usr/bin/env python3
"""Read-only provenance check for the BrC GCClassic integration stack."""

import argparse
import json
import subprocess
from pathlib import Path


CANONICAL_URLS = {
    "src/GEOS-Chem": "https://github.com/maxcharvey/geos-chem.git",
    "src/HEMCO": "https://github.com/maxcharvey/HEMCO.git",
    "src/Cloud-J": "https://github.com/maxcharvey/Cloud-J.git",
}
WRAPPER_ORIGIN = "https://github.com/maxcharvey/GCClassic.git"


class GitError(RuntimeError):
    """A Git command failed; callers must report a failed contract."""


def git(repo, *args):
    """Run Git read-only and return stdout, failing closed on an error."""
    command = ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(
            command, text=True, capture_output=True, check=False, timeout=30
        )
    except subprocess.TimeoutExpired as error:
        raise GitError(f"{' '.join(command)}: timed out after 30 seconds") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise GitError(f"{' '.join(command)}: {detail}")
    return result.stdout


def canonical_modules(repo):
    """Return path -> URL entries from the wrapper .gitmodules file."""
    modules = Path(repo) / ".gitmodules"
    if not modules.is_file():
        raise GitError(f"missing {modules}")
    paths = git(repo, "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$")
    found = {}
    for line in paths.splitlines():
        key, path = line.split(maxsplit=1)
        name = key[len("submodule.") : -len(".path")]
        url = git(repo, "config", "-f", ".gitmodules", "--get", f"submodule.{name}.url").strip()
        found[path] = url
    return found


def submodule_rows(repo):
    """Parse recursive submodule status without mutating the checkout."""
    text = git(repo, "submodule", "status", "--recursive")
    rows = []
    for raw in text.splitlines():
        if not raw:
            continue
        marker = raw[0]
        fields = raw[1:].strip().split(maxsplit=2)
        if len(fields) < 2:
            raise GitError(f"unparseable submodule status: {raw}")
        rows.append({"marker": marker, "sha": fields[0], "path": fields[1],
                     "describe": fields[2] if len(fields) == 3 else ""})
    return rows


def clean(repo):
    """Return local dirt, leaving recursive submodule checks to this checker."""
    return [line for line in git(
        repo, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=all"
    ).splitlines() if line]


def remote_record(repo, path, expected_url, branch):
    """Return remote provenance for one repository, raising on Git failures."""
    local_head = git(repo, "rev-parse", "HEAD").strip()
    origin_url = git(repo, "config", "--get", "remote.origin.url").strip()
    refs = git(repo, "ls-remote", "--heads", "origin", branch).splitlines()
    remote_head = refs[0].split()[0] if refs else None
    return {
        "path": path,
        "expected_origin": expected_url,
        "origin_url": origin_url,
        "local_head": local_head,
        "remote_head": remote_head,
    }


def check_contract(repo, branch="integration/brc-14.8.0", remote=False,
                   expected_urls=None):
    """Check the wrapper/submodule provenance contract and return a JSON-ready dict."""
    root = Path(repo).resolve()
    expected = dict(CANONICAL_URLS if expected_urls is None else expected_urls)
    report = {"repo": str(root), "branch": branch, "remote_checked": remote,
              "status": "FAIL", "errors": [], "modules": [], "remotes": []}
    try:
        report["head"] = git(root, "rev-parse", "HEAD").strip()
        configured = canonical_modules(root)
        for path, url in expected.items():
            actual = configured.get(path)
            module = {"path": path, "expected_url": url, "configured_url": actual}
            if actual != url:
                report["errors"].append(f"{path}: .gitmodules URL is {actual!r}, expected {url!r}")
            report["modules"].append(module)

        # GCClassic intentionally includes additional official recursive
        # dependencies. This contract governs the three BrC forked modules;
        # expose other entries without incorrectly treating them as drift.
        report["other_modules"] = {
            path: url for path, url in configured.items() if path not in expected
        }

        rows = submodule_rows(root)
        row_by_path = {row["path"]: row for row in rows}
        for module in report["modules"]:
            row = row_by_path.get(module["path"])
            if row is None:
                report["errors"].append(f"{module['path']}: absent from recursive submodule status")
                continue
            module.update({"gitlink": row["sha"], "gitlink_marker": row["marker"]})

        for row in rows:
            child = root / row["path"]
            if row["marker"] != " ":
                report["errors"].append(
                    f"{row['path']}: recursive gitlink is not initialized/exact (marker {row['marker']!r})"
                )
                continue
            if not child.is_dir():
                report["errors"].append(f"{row['path']}: initialized submodule directory is missing")
                continue
            actual_head = git(child, "rev-parse", "HEAD").strip()
            if actual_head != row["sha"]:
                report["errors"].append(
                    f"{row['path']}: HEAD {actual_head} differs from recorded gitlink {row['sha']}"
                )
            dirty = clean(child)
            if dirty:
                report["errors"].append(f"{row['path']}: dirty ({'; '.join(dirty)})")

        root_dirty = clean(root)
        if root_dirty:
            report["errors"].append(f"wrapper: dirty ({'; '.join(root_dirty)})")

        if remote:
            remotes = [(".", root, WRAPPER_ORIGIN)]
            remotes.extend((path, root / path, url) for path, url in expected.items())
            for path, module_repo, expected_url in remotes:
                record = remote_record(module_repo, path, expected_url, branch)
                report["remotes"].append(record)
                if record["origin_url"] != expected_url:
                    report["errors"].append(
                        f"{path}: origin URL is {record['origin_url']!r}, expected {expected_url!r}"
                    )
                if record["remote_head"] != record["local_head"]:
                    report["errors"].append(
                        f"{path}: origin/{branch} is {record['remote_head'] or 'absent'}, "
                        f"not local HEAD {record['local_head']}"
                    )

    except (GitError, OSError, ValueError) as error:
        report["errors"].append(f"subprocess/check failure: {error}")

    report["status"] = "PASS" if not report["errors"] else "FAIL"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True,
                        help="GCClassic wrapper checkout to inspect")
    parser.add_argument("--branch", default="integration/brc-14.8.0",
                        help="remote branch required by --remote")
    parser.add_argument("--remote", action="store_true",
                        help="also require origin/<branch> to equal each local integration HEAD")
    args = parser.parse_args()
    report = check_contract(args.repo, args.branch, args.remote)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
