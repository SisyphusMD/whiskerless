#!/usr/bin/env python3
"""Verify this project's vendored standard files still match STANDARD.lock.

    packaging/check-standard-sync.py [repo-root]     # defaults to the current directory

Vendored into every consumer and run by its CI, so the check travels with the files it guards —
including itself: this script is locked too, so editing it in place is caught by running it.

Stdlib only, so a consumer can run it in CI with no dependencies and no network. This is what
catches the failure mode that drove these projects apart in the first place: someone improves a
shared helper by editing the vendored COPY, the sibling project never learns about it, and six
months later the two scripts have four divergent behaviours between them.

Exit 0 in sync, 1 on drift, 2 on a malformed or missing lock.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

LOCK_NAME = "STANDARD.lock"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    consumer = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    lock_path = consumer / LOCK_NAME
    if not lock_path.is_file():
        print(f"no {LOCK_NAME} in {consumer}", file=sys.stderr)
        return 2
    try:
        lock = json.loads(lock_path.read_text())
        files = lock["files"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"malformed {LOCK_NAME}: {exc}", file=sys.stderr)
        return 2

    drifted: list[str] = []
    missing: list[str] = []
    for rel, expected in sorted(files.items()):
        path = consumer / rel
        if not path.is_file():
            missing.append(rel)
        elif digest(path) != expected:
            drifted.append(rel)

    if not drifted and not missing:
        print(f"standard in sync: {len(files)} files match {lock.get('source_tag', '?')}")
        return 0

    for rel in missing:
        print(f"MISSING  {rel}", file=sys.stderr)
    for rel in drifted:
        print(f"DRIFTED  {rel}", file=sys.stderr)
    print(
        "\nA vendored standard file was edited in place. Make the change in "
        "SisyphusMD/project-standard, re-vendor BOTH projects, and land them together — that is the "
        "whole point of the lock.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
