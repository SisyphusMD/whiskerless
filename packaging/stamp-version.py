#!/usr/bin/env python3
"""Write one version into every place that has to agree, or verify they do.

    stamp-version.py <version>
    stamp-version.py <version> --check

Four strings must match or a release is broken in a way CI cannot see:

* ``pyproject.toml`` ``version``            — what PyPI publishes
* ``src/whiskerless/__init__.py``           — what the library reports
* ``manifest.json`` ``version``             — what HACS offers
* ``manifest.json`` ``requirements``        — the library the integration pulls
* ``README.md`` download filenames          — what a user is told to install

The last two are the sharp edge: the integration depends on the *published*
library, so a manifest pinning a version PyPI does not have leaves the user
unable to set the integration up at all.

``--check`` re-reads from disk and fails on any disagreement, so both the gate
and the tag job can prove the tree they are about to publish is consistent.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "whiskerless" / "__init__.py"
MANIFEST = ROOT / "custom_components" / "whiskerless" / "manifest.json"
README = ROOT / "README.md"

# Every asset filename the README tells someone to download, in all three
# spellings the packagers produce: `whiskerless-1.2.3-linux-x86_64`,
# `whiskerless_1.2.3_amd64.deb`, `whiskerless-1.2.3.x86_64.rpm`.
#
# `<version>` is matched too, because that is the state the README starts in and
# no release can be told to substitute itself. Before the first stamped release
# the placeholder is the honest text — 0.1.3's assets carry no version in their
# names at all, so any concrete number there would be a filename that has never
# existed. From the first stable release on, this keeps it current.
README_ASSET_RE = re.compile(r"(whiskerless[-_])(?:<version>|\d+\.\d+\.\d+)")

# A PEP 440 release, optionally an -rc.N prerelease. Deliberately strict: a typo
# reaching the tag is far more expensive than failing here.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-rc\.\d+)?$")

def _rewrite(version: str) -> None:
    for path, pattern, replacement in (
        (PYPROJECT, re.compile(r'(?m)^version = "[^"]+"'), f'version = "{version}"'),
        (INIT, re.compile(r'(?m)^__version__ = "[^"]+"'), f'__version__ = "{version}"'),
        (MANIFEST, re.compile(r'"version": "[^"]+"'), f'"version": "{version}"'),
        (MANIFEST, re.compile(r'"whiskerless==[^"]+"'), f'"whiskerless=={version}"'),
    ):
        text = path.read_text(encoding="utf-8")
        stamped, count = pattern.subn(replacement, text)
        if count != 1:
            sys.exit(f"{path}: expected exactly one match for {pattern.pattern!r}, found {count}")
        path.write_text(stamped, encoding="utf-8")

    # The README documents installing the latest STABLE release, so a candidate
    # must not rewrite it: an rc's own assets are spelled differently by each
    # packager (`-rc.4` for the binaries, `.rc.4` for deb/rpm), and stamping one
    # spelling everywhere would hand users filenames that do not exist.
    if "-rc." in version:
        return
    text = README.read_text(encoding="utf-8")
    stamped, count = README_ASSET_RE.subn(rf"\g<1>{version}", text)
    if count < 1:
        sys.exit(f"{README}: no versioned download filenames found to stamp")
    README.write_text(stamped, encoding="utf-8")


def _check(version: str) -> None:
    expected = (
        (PYPROJECT, f'version = "{version}"'),
        (INIT, f'__version__ = "{version}"'),
        (MANIFEST, f'"version": "{version}"'),
        (MANIFEST, f'"whiskerless=={version}"'),
    )
    problems = [
        f"{path.relative_to(ROOT)}: missing {needle!r}"
        for path, needle in expected
        if needle not in path.read_text(encoding="utf-8")
    ]
    if "-rc." not in version:
        stale = {
            m.group(0)
            for m in README_ASSET_RE.finditer(README.read_text(encoding="utf-8"))
            # `<version>` is the un-stamped state, not a wrong version.
            if "<version>" not in m.group(0) and not m.group(0).endswith(version)
        }
        problems += [f"README.md: stale download filename {name!r}" for name in sorted(stale)]
    if problems:
        sys.exit("version strings disagree:\n  " + "\n  ".join(problems))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()

    if not VERSION_RE.match(args.version):
        sys.exit(f"not a release or -rc.N version: {args.version!r}")

    if args.check:
        _check(args.version)
    else:
        _rewrite(args.version)


if __name__ == "__main__":
    main()
