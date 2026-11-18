#!/usr/bin/env python3
"""Verify a merged release PR before authorizing an annotated tag.

Pass the Forgejo pull request response on stdin. Fetch the primary's main and
tags first, and pass the resulting main SHA. The checked-out tree stays untouched.
"""

import json
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def git(*args):
    return subprocess.run(
        ["git", *args], check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()


def verify(pr, repo, number, main):
    if pr["number"] != number or pr["state"] != "closed" or pr["merged"] is not True:
        raise ValueError("the requested pull request has not merged")
    base, head = pr["base"], pr["head"]
    if base["ref"] != "main" or any(side["repo"]["full_name"] != repo for side in (base, head)):
        raise ValueError("release must merge from a branch in this repository into main")
    branch = head["label"]
    # Forgejo keeps the original branch in label after replacing a deleted ref
    # with its pull-request ref. That ref must belong to this exact PR.
    tag = branch.removeprefix("release/")
    version = VERSION.fullmatch(tag)
    if (
        branch != f"release/{tag}"
        or version is None
        or head["ref"] not in (branch, f"refs/pull/{number}/head")
    ):
        raise ValueError("expected a release/vX.Y.Z head branch")
    merge, candidate = pr["merge_commit_sha"], head["sha"]
    if not all(isinstance(sha, str) and SHA.fullmatch(sha) for sha in (main, merge, candidate)):
        raise ValueError("the release and main must identify full commit SHAs")
    if merge not in git("rev-list", "--first-parent", main).splitlines():
        raise ValueError("merged commit is not on the primary's main history")
    if git("rev-parse", f"{merge}^{{tree}}") != git("rev-parse", f"{candidate}^{{tree}}"):
        raise ValueError("merged tree differs from the prepared release")
    changelog = git("show", f"{merge}:CHANGELOG.md")
    sections = re.findall(r"^## \[([^]]+)\]", changelog, re.MULTILINE)
    released = next((section for section in sections if section != "Unreleased"), None)
    if released != tag[1:]:
        raise ValueError("the first release in CHANGELOG.md does not match the tag")

    stable = {}
    for line in git("ls-remote", "--tags", "--refs", "origin", "refs/tags/v*").splitlines():
        sha, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/")
        if VERSION.fullmatch(name):
            stable[name] = sha
    if tag in stable:
        existing = stable[tag]
        if git("cat-file", "-t", existing) != "tag" or git(
            "rev-parse", f"{existing}^{{commit}}",
        ) != merge:
            raise ValueError("existing tag does not identify this release")
        return tag, merge

    if stable:
        latest = max(stable, key=lambda name: tuple(map(int, name[1:].split("."))))
        if tuple(map(int, version.groups())) <= tuple(map(int, latest[1:].split("."))):
            raise ValueError("release version must be newer than the latest stable tag")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", f"{stable[latest]}^{{commit}}", merge], check=False,
        )
        if ancestor.returncode:
            raise ValueError("release must descend from the latest stable tag")
    return tag, merge


def main():
    if len(sys.argv) != 4 or not re.fullmatch(r"[1-9][0-9]*", sys.argv[2]):
        sys.exit("usage: verify-release-pr.py OWNER/REPO PR_NUMBER FETCHED_MAIN_SHA")
    try:
        tag, commit = verify(json.load(sys.stdin), sys.argv[1], int(sys.argv[2]), sys.argv[3])
    except (ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Cannot verify release PR: {exc}")
    print(f"tag={tag}\ncommit={commit}")


if __name__ == "__main__":
    main()
