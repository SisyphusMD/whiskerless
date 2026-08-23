#!/usr/bin/env python3
"""Write one version into every place that has to agree, or verify they do.

    stamp-version.py <version> [root] [--check]

Five strings must match or a release is broken in a way CI cannot otherwise see:

* ``pyproject.toml`` ``version``            — what PyPI publishes
* ``src/whiskerless/__init__.py``           — what the library reports
* ``manifest.json`` ``version``             — what HACS offers
* ``manifest.json`` ``requirements``        — the library the integration pulls
* ``README.md`` download filenames          — what a user is told to install

The middle two are the sharp edge: the integration depends on the *published* library, so a manifest
pinning a version PyPI does not have leaves the user unable to set the integration up at all.

The mechanism (the match guards, the staged atomic write, `--check` reporting) is shared in
stamp_common.py. Only the inventory below is project-specific.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stamp_common
from stamp_common import readable, replace_at_least_once, replace_once

_FILES = (
    Path("pyproject.toml"),
    Path("src/whiskerless/__init__.py"),
    Path("custom_components/whiskerless/manifest.json"),
    Path("README.md"),
)

# Every asset filename the README tells someone to download, in all three spellings the packagers
# produce: `whiskerless-1.2.3-linux-x86_64`, `whiskerless_1.2.3_amd64.deb`,
# `whiskerless-1.2.3.x86_64.rpm`.
_README_ASSET = re.compile(r"(whiskerless[-_])(?:<version>|\d+\.\d+\.\d+)")
_README_STAMPED = re.compile(r"whiskerless[-_]\d+\.\d+\.\d+")

# A PEP 440 release, optionally an -rc.N prerelease. Deliberately stricter than the shared default,
# which also admits `.devN`: this project publishes no dev builds, and a tag vocabulary wider than
# the release process actually supports is a way for a typo to reach a tag.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-rc\.\d+)?$")


def rendered(root: Path, version: str, *, check: bool = False) -> dict[Path, str]:
    project, package, manifest, readme = readable(root, _FILES)
    manifest_text = replace_once(
        manifest.read_text(encoding="utf-8"),
        re.compile(r'"version": "[^"]+"'),
        f'"version": "{version}"',
        "manifest.json version",
    )
    manifest_text = replace_once(
        manifest_text,
        re.compile(r'"whiskerless==[^"]+"'),
        f'"whiskerless=={version}"',
        "manifest.json requirements",
    )
    updates = {
        project: replace_once(
            project.read_text(encoding="utf-8"),
            re.compile(r'(?m)^version = "[^"]+"'),
            f'version = "{version}"',
            "pyproject.toml",
        ),
        package: replace_once(
            package.read_text(encoding="utf-8"),
            re.compile(r'(?m)^__version__ = "[^"]+"'),
            f'__version__ = "{version}"',
            "src/whiskerless/__init__.py",
        ),
        manifest: manifest_text,
    }

    # The README documents installing the latest STABLE release, so a candidate must not rewrite it:
    # an rc's assets are spelled differently by each packager (`-rc.4` for the binaries, `.rc.4` for
    # deb/rpm), and stamping one spelling everywhere would hand users filenames that do not exist.
    if "-rc." in version:
        return updates

    readme_text = readme.read_text(encoding="utf-8")
    # `<version>` is the un-stamped state, not a wrong version. Before the first stable release
    # stamps it, the placeholder is the honest text — the pre-stamp assets carry no version in their
    # names at all, so any concrete number there would name a file that never existed. So a CHECK
    # tolerates a README still holding only placeholders, while a STAMP replaces them. These two
    # deliberately differ, which is why the renderer is told which one it is serving.
    placeholder_only = "<version>" in readme_text and not _README_STAMPED.search(readme_text)
    if not (check and placeholder_only):
        updates[readme] = replace_at_least_once(
            readme_text,
            _README_ASSET,
            rf"\g<1>{version}",
            "README.md download filenames",
        )
    return updates


# Thin wrappers so this script's own shape is unchanged by where the mechanism lives.
def stamp(root: Path, version: str, *, check: bool = False) -> bool:
    return not stamp_common.stamp(root, rendered, version, check=check)


def main() -> int:
    return stamp_common.run(rendered, VERSION_RE)


if __name__ == "__main__":
    raise SystemExit(main())
