"""Shared mechanism for stamping one version into every record that must agree.

Each project owns *which* files carry a version and what the patterns look like — that inventory is
genuinely project-specific and does not belong here. What is shared is the mechanism: PEP 440
normalisation, the exactly-one-match guard, the staged atomic write, and `--check` diagnostics that
name the file that disagrees.

A project's `packaging/stamp-version.py` declares a `rendered(root, version) -> dict[Path, str]` and
hands it to `run()`.
"""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:(?:-rc\.[0-9]+)|(?:\.dev[0-9]+))?$")

# The renderer is told whether this is a check, because for some records "already correct" and
# "acceptable as-is" are not the same set. A README carrying `<version>` placeholders is honest
# before the first stable release stamps it, but stamping still replaces it — so a renderer may
# legitimately omit such a record from the check-time inventory.
Renderer = Callable[..., "dict[Path, str]"]


def normalized(version: str) -> str:
    """The PEP 440 spelling of a release tag's version (`1.2.3-rc.4` -> `1.2.3rc4`).

    Packaging metadata and lockfiles record the normalised form while the git tag keeps the
    hyphenated one, so anything comparing the two needs this conversion rather than the raw string.
    """
    if VERSION.fullmatch(version) is None:
        raise ValueError(f"invalid project version: {version!r}")
    match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+)-rc\.([0-9]+)", version)
    return f"{match[1]}rc{match[2]}" if match else version


def replace_once(text: str, pattern: re.Pattern[str], replacement: str, label: str) -> str:
    """Substitute exactly one match, or fail.

    Zero matches means the pattern has drifted from the file and the stamp would silently do
    nothing; several means the file has more version records than the caller believes, and stamping
    all of them is as likely to be wrong as right. Both are release-breaking, and both are invisible
    to a plain `re.sub`.
    """
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise ValueError(f"{label} must contain exactly one version record; found {count}")
    return updated


def replace_at_least_once(
    text: str, pattern: re.Pattern[str], replacement: str, label: str
) -> str:
    """Substitute every match, requiring at least one.

    For records that legitimately repeat — a README listing one download filename per platform —
    where zero matches still means the pattern has drifted and the stamp silently did nothing.
    """
    updated, count = pattern.subn(replacement, text)
    if count < 1:
        raise ValueError(f"{label} has no version record to stamp")
    return updated


def readable(root: Path, relatives: tuple[Path, ...]) -> list[Path]:
    """Resolve the inventory, refusing anything missing, non-regular, or symlinked."""
    paths = [root / relative for relative in relatives]
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"version record is missing, non-regular, or symlinked: {path}")
    return paths


def stamp(root: Path, render: Renderer, version: str, *, check: bool = False) -> list[Path]:
    """Write the rendered version records; return the paths that disagreed.

    In `--check` mode nothing is written and the disagreeing paths are reported, so a release gate
    can prove the tree it is about to publish is self-consistent.

    Every replacement file is written and fsynced BEFORE any of them is moved into place, so a
    failure while rendering cannot leave a half-stamped tree.
    """
    updates = render(root, version, check=check)
    changed = {path: contents for path, contents in updates.items() if path.read_text() != contents}
    if check or not changed:
        return sorted(changed)

    temporary: dict[Path, Path] = {}
    try:
        for path, contents in changed.items():
            descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            target = Path(raw)
            temporary[path] = target
            with os.fdopen(descriptor, "w") as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            target.chmod(path.stat().st_mode)
        for path, target in temporary.items():
            target.replace(path)
    finally:
        for target in temporary.values():
            target.unlink(missing_ok=True)
    return sorted(changed)


def run(render: Renderer, version_pattern: re.Pattern[str] = VERSION) -> int:
    """Drive one project's stamp from the command line.

    `version_pattern` defaults to the permissive union of what these projects accept. A project that
    does not publish `.devN` builds passes its own stricter pattern rather than inheriting a wider
    tag vocabulary than it means to support — a typo reaching a tag costs a yanked release, and
    failing here costs nothing.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if not version_pattern.match(args.version):
        parser.error(f"invalid release version: {args.version!r}")
    try:
        disagreed = stamp(root, render, args.version, check=args.check)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.check and disagreed:
        # Name the files, not just the fact. "version records disagree" sends you reading all of
        # them; naming the one that drifted is the difference between a minute and twenty.
        listing = "\n  ".join(str(p.relative_to(root)) for p in disagreed)
        print(f"version records do not all match {args.version}:\n  {listing}")
        return 1
    print(f"version records match {args.version}" if args.check else f"stamped {args.version}")
    return 0
