"""The bottle-block generator, which decides what the published tap tells users to download.

Every failure this guards against is silent at the API and loud on a user's
machine: a block naming a bottle nobody uploaded sends Homebrew back to
compiling cryptography for several minutes, and a block carrying last release's
sha256 fails the download outright. So the merge refuses anything it cannot
account for rather than emitting a best effort.

The manifest shape asserted here was captured from a real `brew bottle --json`
run (Homebrew 4.6.20), not written from memory.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    """Import the script despite its hyphenated, non-importable filename."""
    spec = importlib.util.spec_from_file_location(
        "bottle_block", REPO / "packaging" / "bottle-block.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bb = _load()


def _manifest(
    path: Path,
    *,
    formula: str = "whiskerless",
    version: str = "0.2.0rc28",
    tag: str = "arm64_sequoia",
    sha: str = "a" * 64,
    cellar: str = "/opt/homebrew/Cellar",
    rebuild: int = 0,
) -> Path:
    """One platform's manifest, shaped like the real thing."""
    path.write_text(
        json.dumps(
            {
                f"sisyphusmd/tap/{formula}": {
                    "formula": {"name": formula, "pkg_version": version},
                    "bottle": {
                        "root_url": "https://example.invalid",
                        "cellar": cellar,
                        "rebuild": rebuild,
                        "tags": {
                            tag: {
                                "filename": f"{formula}-{version}.{tag}.bottle.tar.gz",
                                "local_filename": f"{formula}--{version}.{tag}.bottle.tar.gz",
                                "sha256": sha,
                            }
                        },
                    },
                }
            }
        )
    )
    return path


def test_the_four_platforms_merge_into_one_block(tmp_path: Path) -> None:
    paths = [
        _manifest(tmp_path / f"{tag}.json", tag=tag, sha=chr(97 + i) * 64)
        for i, tag in enumerate(["arm64_sequoia", "sequoia", "x86_64_linux", "arm64_linux"])
    ]
    tags = bb.collect(paths, "whiskerless", "0.2.0rc28")
    assert set(tags) == {"arm64_sequoia", "sequoia", "x86_64_linux", "arm64_linux"}
    assert {cellar for _, cellar in tags.values()} == {"/opt/homebrew/Cellar"}


def test_macos_is_listed_before_linux(tmp_path: Path) -> None:
    """Only so the published formula reads like every other one; nothing depends
    on the order, and a hand diff of the tap is easier when it does not move."""
    paths = [
        _manifest(tmp_path / f"{tag}.json", tag=tag)
        for tag in ["arm64_linux", "sequoia", "x86_64_linux", "arm64_sequoia"]
    ]
    tags = bb.collect(paths, "whiskerless", "0.2.0rc28")
    rendered = [line.split()[-2].rstrip(":") for line in bb.render(tags, "u").splitlines()[2:-1]]
    assert rendered == ["arm64_sequoia", "sequoia", "x86_64_linux", "arm64_linux"]


@pytest.mark.parametrize(
    ("cellar", "expected"),
    [
        ("any", "cellar: :any,"),
        ("any_skip_relocation", "cellar: :any_skip_relocation,"),
        # A venv bakes absolute paths into its shebangs, so this is the case the
        # real formula hits — and it has to stay a Ruby string, not a symbol.
        ("/opt/homebrew/Cellar", 'cellar: "/opt/homebrew/Cellar",'),
    ],
)
def test_the_cellar_is_a_symbol_only_when_homebrew_means_one(
    tmp_path: Path, cellar: str, expected: str
) -> None:
    path = _manifest(tmp_path / "m.json", cellar=cellar)
    tags = bb.collect([path], "whiskerless", "0.2.0rc28")
    assert expected in bb.render(tags, "https://example.invalid")


def test_a_manifest_from_another_release_is_refused(tmp_path: Path) -> None:
    """The failure that motivated the check: a stale manifest merges cleanly and
    publishes a formula whose block names files this release never uploaded."""
    path = _manifest(tmp_path / "m.json", version="0.2.0rc27")
    with pytest.raises(SystemExit, match=re.escape("0.2.0rc27")):
        bb.collect([path], "whiskerless", "0.2.0rc28")


def test_a_rebuild_counter_is_refused(tmp_path: Path) -> None:
    """A rebuild suffixes the filename, so a non-zero counter means the block and
    the uploaded asset would disagree about the name."""
    path = _manifest(tmp_path / "m.json", rebuild=1)
    with pytest.raises(SystemExit, match="rebuild"):
        bb.collect([path], "whiskerless", "0.2.0rc28")


def test_the_other_formulas_manifests_are_ignored(tmp_path: Path) -> None:
    """A stable tag bottles both formulae and the manifests land in one
    directory; each block must take only its own."""
    mine = _manifest(tmp_path / "a.json", formula="whiskerless", sha="b" * 64)
    theirs = _manifest(tmp_path / "b.json", formula="whiskerless-rc", sha="c" * 64)
    tags = bb.collect([mine, theirs], "whiskerless", "0.2.0rc28")
    assert tags == {"arm64_sequoia": ("b" * 64, "/opt/homebrew/Cellar")}


def test_a_formula_with_no_manifest_at_all_is_an_error(tmp_path: Path) -> None:
    path = _manifest(tmp_path / "m.json", formula="whiskerless")
    with pytest.raises(SystemExit, match="no manifest mentions"):
        bb.collect([path], "whiskerless-rc", "0.2.0rc28")


def test_two_bottles_claiming_one_platform_are_refused(tmp_path: Path) -> None:
    a = _manifest(tmp_path / "a.json", sha="d" * 64)
    b = _manifest(tmp_path / "b.json", sha="e" * 64)
    with pytest.raises(SystemExit, match="two different bottles"):
        bb.collect([a, b], "whiskerless", "0.2.0rc28")


def test_each_platform_keeps_its_own_cellar(tmp_path: Path) -> None:
    """Homebrew puts `cellar:` on each tag's own sha256 line, and the platforms legitimately
    disagree — macOS bottles are typically :any_skip_relocation while Linux ones are :any.
    Demanding one global value rejected a valid set and published no block at all."""
    a = _manifest(tmp_path / "a.json", tag="arm64_sequoia", cellar="any_skip_relocation")
    b = _manifest(tmp_path / "b.json", tag="x86_64_linux", cellar="any")
    tags = bb.collect([a, b], "whiskerless", "0.2.0rc28")
    block = bb.render(tags, "https://example.invalid")
    assert "cellar: :any_skip_relocation, arm64_sequoia:" in block
    assert "cellar: :any, x86_64_linux:" in block


def test_a_short_set_is_refused_when_a_count_is_demanded(tmp_path: Path) -> None:
    """The silent failure this exists for: three bottles publish happily and
    everyone on the fourth platform quietly goes back to compiling."""
    paths = [
        _manifest(tmp_path / f"{tag}.json", tag=tag, sha=chr(97 + i) * 64)
        for i, tag in enumerate(["arm64_sequoia", "sequoia", "x86_64_linux"])
    ]
    argv = [
        "--formula", "whiskerless",
        "--version", "0.2.0rc28",
        "--root-url", "https://example.invalid",
        "--expect-tags", "4",
        *[str(p) for p in paths],
    ]
    with pytest.raises(SystemExit, match="expected 4"):
        bb.main(argv)


def test_the_rendered_block_is_the_shape_homebrew_parses(tmp_path: Path) -> None:
    """Homebrew fetches `<root_url>/<filename>`; both halves are asserted live in
    the pour test, so what matters here is that the block keeps its shape."""
    path = _manifest(tmp_path / "m.json", cellar="any")
    tags = bb.collect([path], "whiskerless", "0.2.0rc28")
    block = bb.render(tags, "https://forgejo.example/releases/download/v0.2.0-rc.28")
    assert block.splitlines()[0] == "  bottle do"
    assert block.splitlines()[1] == '    root_url "https://forgejo.example/releases/download/v0.2.0-rc.28"'
    assert block.splitlines()[-1] == "  end"
    assert f'arm64_sequoia: "{"a" * 64}"' in block
