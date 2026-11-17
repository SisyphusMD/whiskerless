#!/usr/bin/env python3
"""Fail a PR that changes more than LIMIT lines outside tests and lockfiles.

Usage: diff-size.py <base-sha> <head-sha>
Env: PR_BODY, optional DIFF_LIMIT (default 400).
Counts added plus deleted lines from `git diff --numstat base...head`; binary files count 0.
Test paths match tests-with-code.py. `Large diff: <reason>` in the PR description lets a PR
through; the AI review judges the reason.
"""
import os
import re
import subprocess
import sys

LOCKFILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock",
             "Cargo.lock", "go.sum", "flake.lock", "Package.resolved", "Gemfile.lock",
             "composer.lock", "Podfile.lock"}


def is_test(path):
    parts = path.split("/")
    name = parts[-1]
    return (any(p in ("tests", "test", "__tests__") for p in parts[:-1])
            or name.startswith("test_") or re.search(r"(_test|\.test|\.spec)\.[^.]+$", name) is not None)


def counted(path):
    return not is_test(path) and path.split("/")[-1] not in LOCKFILES


def changed_lines(base, head):
    out = subprocess.run(["git", "diff", "--numstat", "-M", "-z", f"{base}...{head}"],
                         capture_output=True, text=True, check=True).stdout
    # -z: "added\tdeleted\tpath\0", or for a rename "added\tdeleted\t\0old\0new\0".
    fields = out.split("\0")
    total, i = 0, 0
    while i < len(fields) and fields[i]:
        added, deleted, path = fields[i].split("\t", 2)
        if path:
            paths, i = [path], i + 1
        else:
            paths, i = [fields[i + 1], fields[i + 2]], i + 3
        # A rename counts if either side is counted code, so moving code into tests/ is not free.
        if any(counted(p) for p in paths) and added != "-":
            total += int(added) + int(deleted)
    return total


def main(base, head):
    limit = int(os.environ.get("DIFF_LIMIT", "400"))
    total = changed_lines(base, head)
    if total <= limit:
        print(f"{total} changed lines outside tests and lockfiles (limit {limit}).")
        return
    m = re.search(r"(?im)^[ \t]*Large diff:[ \t]*(\S.*)$", os.environ.get("PR_BODY") or "")
    if m:
        print(f"{total} changed lines, over {limit}, by the description: {m.group(1).strip()}")
        return
    sys.exit(f"{total} changed lines outside tests and lockfiles, over the {limit} limit.\n"
             "Split the PR, or say `Large diff: <reason>` in the PR description.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
