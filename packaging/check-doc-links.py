#!/usr/bin/env python3
"""Verify that every local Markdown link in the repository resolves.

Relative links rot silently: a doc moves or an entity is renamed and the link
keeps rendering, just pointing at nothing. The setup guide alone links to the
recovery guide, the compatibility notes and the examples directory, and this
session added several more.

Scoped to git-tracked files: the working tree also holds virtualenvs and
scratch notes whose broken links are not ours to fix.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", re.M)
_FENCE = re.compile(r"^```.*?^```", re.M | re.S)
_INLINE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _anchors(document: Path) -> set[str]:
    """GitHub's generated heading anchors for one document.

    Fenced code is stripped first: a `# comment` inside a shell block is not a
    heading, and treating it as one would invent anchors that do not exist.
    """
    text = _FENCE.sub("", document.read_text(errors="replace"))
    found = set()
    for heading in _HEADING.findall(text):
        # Link text survives as its label; inline code and emphasis markers do not.
        plain = _INLINE_LINK.sub(r"\1", heading)
        plain = re.sub(r"[`*_~]", "", plain)
        slug = re.sub(r"[^\w\- ]", "", plain).strip().lower().replace(" ", "-")
        if slug:
            found.add(slug)
    return found


def _tracked_markdown(root: Path) -> list[Path]:
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "*.md"],
        check=True, capture_output=True, text=True,
    )
    return sorted(root / name for name in listing.stdout.split("\0") if name)


def broken_links(root: Path) -> list[str]:
    broken: list[str] = []
    for document in _tracked_markdown(root):
        text = document.read_text(errors="replace")
        for raw in _LINK.findall(text):
            target = raw.strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target = target.split(maxsplit=1)[0]
            if not target or target.startswith(("#", "//")):
                continue
            if _SCHEME.match(target):
                continue
            path_text, _, fragment = target.partition("#")
            path_text = unquote(path_text.split("?", 1)[0])
            fragment = unquote(fragment)
            if not path_text:
                # Same-document anchor: check it against this file's own headings.
                if fragment and fragment.lower() not in _anchors(document):
                    broken.append(f"{document.relative_to(root)}: no such heading: {raw}")
                continue
            resolved = (document.parent / path_text).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                broken.append(f"{document.relative_to(root)}: link escapes the repository: {raw}")
                continue
            if not resolved.exists():
                broken.append(f"{document.relative_to(root)}: missing local target: {raw}")
                continue
            # A fragment is the half that rots silently: the file still exists, so
            # a heading rename leaves the link rendering and pointing at nothing.
            if (
                fragment
                and resolved.suffix == ".md"
                and fragment.lower() not in _anchors(resolved)
            ):
                broken.append(f"{document.relative_to(root)}: no such heading: {raw}")
    return broken


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        broken = broken_links(args.root.resolve())
    except OSError as exc:
        print(f"documentation link check failed: {exc}")
        return 2
    if broken:
        print("documentation has broken local links:")
        for item in broken:
            print(f"  - {item}")
        return 1
    print("documentation links OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
