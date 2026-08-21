#!/usr/bin/env python3
"""Assert this project's .gitignore contains the shared base patterns.

    check-gitignore-base.py [repo-root]

The base is a floor, not a ceiling: a project adds its own artifacts below it. The check exists
because the expensive omissions are the ones nobody notices — a project that signs macOS artifacts
without ignoring `*.p12` and `*.p8` is one careless `git add` from publishing an Apple signing
certificate, and nothing about the working tree makes that visible.

Exits 0 when every base pattern is present, 1 when any is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path


def patterns(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    base_file = Path(__file__).resolve().parent / "gitignore.base"
    target = root / ".gitignore"
    if not base_file.is_file():
        print(f"missing {base_file}", file=sys.stderr)
        return 2
    if not target.is_file():
        print(f"missing {target}", file=sys.stderr)
        return 2

    have = set(patterns(target))
    missing = [p for p in patterns(base_file) if p not in have]
    if missing:
        print(f"{target} is missing shared base patterns:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f".gitignore contains all {len(patterns(base_file))} shared base patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
