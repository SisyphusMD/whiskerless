#!/usr/bin/env python3
"""Merge `brew bottle --json` manifests into the `bottle do` block a formula carries.

    bottle-block.py --formula <name> --version 0.2.0rc28 --root-url URL manifest.json...

Each platform bottles on its own runner and emits its own manifest; this is what
turns the pile back into one block. Written here rather than reached for through
`brew bottle --merge --write` because that wants the formula already tapped and
rewrites it in place, while this tap is rendered from a template — and because a
merge step that silently accepts a manifest from the *previous* release is
exactly the failure that would publish a formula pointing at bottles that do not
exist. Everything below that can be checked is checked.

The keg inside a bottle is rooted at `<formula-name>/<version>/`, so a bottle
built for `<name>` cannot be renamed and served as `<name>-rc`. That is why a
stable tag builds two sets of bottles and not one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# macOS before Linux, newest OS first — the order homebrew-core writes, so a
# hand-read diff of the tap looks like every other formula.
TAG_ORDER = [
    "arm64_tahoe",
    "arm64_sequoia",
    "arm64_sonoma",
    "tahoe",
    "sequoia",
    "sonoma",
    "x86_64_linux",
    "arm64_linux",
]


def _cellar_literal(cellar: str) -> str:
    """Render `cellar:` as Ruby.

    `any`/`any_skip_relocation` are symbols; anything else is a concrete Cellar
    path and has to stay a string. A venv install is the "anything else" case —
    virtualenv_install_with_resources bakes absolute paths into shebangs and
    pyvenv.cfg, so the bottle is only poured where that path matches.
    """
    if cellar in ("any", "any_skip_relocation"):
        return f":{cellar}"
    return json.dumps(cellar)


def collect(paths: list[Path], formula: str, version: str) -> tuple[dict[str, str], str]:
    """Return {tag: sha256} plus the one cellar value every manifest agreed on."""
    tags: dict[str, str] = {}
    cellars: set[str] = set()
    seen_formula = False

    for path in paths:
        data = json.loads(path.read_text())
        # The outer key is tap-qualified (`<owner>/tap/<name>`), so it is
        # not something to match on; the inner `formula.name` is the short name.
        for entry in data.values():
            info = entry["formula"]
            if info["name"] != formula:
                continue
            seen_formula = True
            if info["pkg_version"] != version:
                raise SystemExit(
                    f"{path}: manifest is for {formula} {info['pkg_version']}, "
                    f"expected {version} — a bottle from another release would "
                    f"publish a formula whose block points at files this release "
                    f"never uploaded"
                )
            bottle = entry["bottle"]
            # A rebuild suffixes the filename (`.bottle.1.tar.gz`). Nothing here
            # ever rebuilds a published version, so a non-zero counter means the
            # runner poured a stale keg and the filenames would not match.
            if bottle.get("rebuild", 0) != 0:
                raise SystemExit(f"{path}: rebuild={bottle['rebuild']}, expected 0")
            cellars.add(bottle["cellar"])
            for tag, spec in bottle["tags"].items():
                sha = spec["sha256"]
                if tags.get(tag, sha) != sha:
                    raise SystemExit(
                        f"{path}: two different bottles claim tag {tag} "
                        f"({tags[tag]} vs {sha})"
                    )
                tags[tag] = sha

    if not seen_formula:
        raise SystemExit(f"no manifest mentions formula {formula}")
    if not tags:
        raise SystemExit(f"no bottle tags found for {formula}")
    if len(cellars) != 1:
        # Merging these would mean picking one and silently mis-describing the
        # others, and `cellar` is what decides whether a bottle is poured at all.
        raise SystemExit(f"manifests disagree on cellar: {sorted(cellars)}")
    return tags, cellars.pop()


def render(tags: dict[str, str], cellar: str, root_url: str, indent: str = "  ") -> str:
    ordered = sorted(tags, key=lambda t: (TAG_ORDER.index(t) if t in TAG_ORDER else len(TAG_ORDER), t))
    cellar_part = f"cellar: {_cellar_literal(cellar)}, "
    width = max(len(t) for t in ordered)
    lines = [f"{indent}bottle do", f'{indent}  root_url "{root_url}"']
    lines += [f'{indent}  sha256 {cellar_part}{tag + ":":{width + 1}} "{tags[tag]}"' for tag in ordered]
    lines.append(f"{indent}end")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formula", required=True)
    parser.add_argument("--version", required=True, help="Homebrew pkg_version, e.g. 0.2.0rc28")
    parser.add_argument("--root-url", required=True)
    parser.add_argument("--expect-tags", type=int, default=0, help="fail unless exactly this many tags merged")
    parser.add_argument("manifests", nargs="+", type=Path)
    args = parser.parse_args(argv)

    tags, cellar = collect(args.manifests, args.formula, args.version)
    # A missing platform is silent otherwise: the formula publishes, and everyone
    # on the platform that did not bottle quietly compiles for several minutes —
    # which is the entire problem bottles were added to solve.
    if args.expect_tags and len(tags) != args.expect_tags:
        raise SystemExit(
            f"merged {len(tags)} bottle tag(s) for {args.formula} "
            f"({', '.join(sorted(tags))}), expected {args.expect_tags}"
        )
    print(render(tags, cellar, args.root_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
