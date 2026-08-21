#!/usr/bin/env python3
"""Verify that every local Markdown link resolves, in a repository or a staged release tree.

Relative links rot silently: a doc moves or a heading is renamed and the link keeps rendering,
pointing at nothing. Fragments are the half that rots most quietly, because the file still exists.

Two discovery modes, because both are needed:

  repo  git-tracked *.md only. The working tree also holds virtualenvs and scratch notes whose
        broken links are not ours to fix.
  tree  every *.md under the root. A staged source release is not a git checkout, and its links
        must resolve INSIDE the release — a link that escapes the staged tree ships broken.

`auto` picks `repo` when the root is a git work tree and `tree` otherwise.
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
    """The generated heading anchors for one document.

    Fenced code is stripped first: a `# comment` inside a shell block is not a heading, and
    treating it as one would invent anchors that do not exist.
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


def _is_git_worktree(root: Path) -> bool:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return False
    return done.returncode == 0 and done.stdout.strip() == "true"


def _documents(root: Path, mode: str) -> list[Path]:
    if mode == "repo":
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "*.md"],
            check=True, capture_output=True, text=True,
        )
        return sorted(root / name for name in listing.stdout.split("\0") if name)
    return sorted(root.rglob("*.md"))


def broken_links(root: Path, mode: str) -> list[str]:
    escape = "link escapes the repository" if mode == "repo" else "link escapes the release"
    broken: list[str] = []
    for document in _documents(root, mode):
        text = document.read_text(errors="replace")
        for raw in _LINK.findall(text):
            target = raw.strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target = target.split(maxsplit=1)[0]
            # A bare "#fragment" is NOT skipped here: it is a same-document anchor, and it is
            # checked against this file's own headings below. Skipping it early is what left that
            # check unreachable in the version this was merged from, so it never caught anything.
            if not target or target.startswith("//"):
                continue
            if _SCHEME.match(target):
                continue
            path_text, _, fragment = target.partition("#")
            path_text = unquote(path_text.split("?", 1)[0])
            fragment = unquote(fragment)
            where = document.relative_to(root)
            if not path_text:
                # Same-document anchor: check it against this file's own headings.
                if fragment and fragment.lower() not in _anchors(document):
                    broken.append(f"{where}: no such heading: {raw}")
                continue
            resolved = (document.parent / path_text).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                broken.append(f"{where}: {escape}: {raw}")
                continue
            if not resolved.exists():
                broken.append(f"{where}: missing local target: {raw}")
                continue
            if fragment and resolved.suffix == ".md" and fragment.lower() not in _anchors(resolved):
                broken.append(f"{where}: no such heading: {raw}")
    return broken


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--mode", choices=("auto", "repo", "tree"), default="auto")
    args = parser.parse_args()
    root = args.root.resolve()
    mode = args.mode
    if mode == "auto":
        mode = "repo" if _is_git_worktree(root) else "tree"
    try:
        broken = broken_links(root, mode)
    except OSError as exc:
        print(f"documentation link check failed: {exc}")
        return 2
    if broken:
        print(f"documentation has broken local links ({mode}):")
        for item in broken:
            print(f"  - {item}")
        return 1
    print(f"documentation links OK ({mode}, {len(_documents(root, mode))} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
