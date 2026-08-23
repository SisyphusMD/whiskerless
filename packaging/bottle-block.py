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


def collect(paths: list[Path], formula: str, version: str) -> dict[str, tuple[str, str]]:
    """Return {tag: (sha256, cellar)} — the cellar recorded PER TAG.

    Homebrew's bottle DSL puts `cellar:` on each tag's own `sha256` line, and the platforms
    legitimately disagree: macOS bottles are typically `:any_skip_relocation` while Linux ones are
    `:any`. Demanding one global value rejected a perfectly valid four-platform set, and the
    second tap pass could then publish no bottle block at all.
    """
    tags: dict[str, tuple[str, str]] = {}
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
            cellar = bottle["cellar"]
            for tag, spec in bottle["tags"].items():
                sha = spec["sha256"]
                if tag in tags and tags[tag] != (sha, cellar):
                    raise SystemExit(
                        f"{path}: two different bottles claim tag {tag} "
                        f"({tags[tag]} vs {(sha, cellar)})"
                    )
                tags[tag] = (sha, cellar)

    if not seen_formula:
        raise SystemExit(f"no manifest mentions formula {formula}")
    if not tags:
        raise SystemExit(f"no bottle tags found for {formula}")
    return tags


def render(tags: dict[str, tuple[str, str]], root_url: str, indent: str = "  ") -> str:
    ordered = sorted(tags, key=lambda t: (TAG_ORDER.index(t) if t in TAG_ORDER else len(TAG_ORDER), t))
    # Aligned on the PREFIX, not the tag: the cellar literal differs per platform, so padding the
    # tag alone left the hashes ragged in a file that ends up committed to the tap.
    prefixes = {t: f"cellar: {_cellar_literal(tags[t][1])}, {t}:" for t in ordered}
    width = max(len(x) for x in prefixes.values())
    # Padded to `width`, not width+1: the literal space in the format string supplies the
    # separator, so the extra column put two spaces after the longest tag.
    lines = [f"{indent}bottle do", f'{indent}  root_url "{root_url}"']
    lines += [
        f'{indent}  sha256 {prefixes[tag]:{width}} "{tags[tag][0]}"' for tag in ordered
    ]
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

    tags = collect(args.manifests, args.formula, args.version)
    # A missing platform is silent otherwise: the formula publishes, and everyone
    # on the platform that did not bottle quietly compiles for several minutes —
    # which is the entire problem bottles were added to solve.
    if args.expect_tags and len(tags) != args.expect_tags:
        raise SystemExit(
            f"merged {len(tags)} bottle tag(s) for {args.formula} "
            f"({', '.join(sorted(tags))}), expected {args.expect_tags}"
        )
    print(render(tags, args.root_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
