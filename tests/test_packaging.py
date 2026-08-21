"""The version stamper, which is the only thing keeping four strings in agreement.

A release that disagrees with itself is broken in a way ordinary CI cannot see:
the integration depends on the *published* library, so a manifest pinning a
version PyPI does not have leaves users unable to set the integration up at all.

The module rewrites real repository files, so every test here points it at copies
in a tmp_path and asserts against those.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    """Import the script despite its hyphenated, non-importable filename."""
    spec = importlib.util.spec_from_file_location(
        "stamp_version", REPO / "packaging" / "stamp-version.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stamp = _load()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A miniature repo holding the five strings, in the real relative layout.

    No module surgery: the script takes the root as an argument, so a temporary tree is addressed
    the same way the real repository is.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "whiskerless"\nversion = "0.1.3"\n')
    package = tmp_path / "src" / "whiskerless"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""doc."""\n\n__version__ = "0.1.3"\n')
    component = tmp_path / "custom_components" / "whiskerless"
    component.mkdir(parents=True)
    (component / "manifest.json").write_text(
        json.dumps(
            {"domain": "whiskerless", "requirements": ["whiskerless==0.1.3"], "version": "0.1.3"},
            indent=2,
        )
    )
    (tmp_path / "README.md").write_text(
        "download whiskerless-<version>-linux-x86_64 or whiskerless_<version>_amd64.deb\n"
    )
    return tmp_path


INIT = Path("src/whiskerless/__init__.py")
MANIFEST = Path("custom_components/whiskerless/manifest.json")


def _versions(tree: Path) -> dict[str, str]:
    manifest = json.loads((tree / MANIFEST).read_text())
    return {
        "pyproject": (tree / "pyproject.toml").read_text().split('version = "')[1].split('"')[0],
        "init": (tree / INIT).read_text().split('__version__ = "')[1].split('"')[0],
        "manifest": manifest["version"],
        "requirement": manifest["requirements"][0].split("==")[1],
    }


def test_a_stamp_moves_all_four_strings_together(tree: Path) -> None:
    stamp.stamp(tree, "0.2.0")
    assert set(_versions(tree).values()) == {"0.2.0"}


def test_the_requirement_pin_moves_with_the_manifest_version(tree: Path) -> None:
    """The sharp one: a pin PyPI does not have breaks setup entirely."""
    stamp.stamp(tree, "0.2.0")
    manifest = json.loads((tree / MANIFEST).read_text())
    assert manifest["requirements"] == ["whiskerless==0.2.0"]
    assert manifest["version"] == manifest["requirements"][0].split("==")[1]


def test_a_release_candidate_is_stamped_the_same_way(tree: Path) -> None:
    stamp.stamp(tree, "0.2.0-rc.1")
    assert set(_versions(tree).values()) == {"0.2.0-rc.1"}


@pytest.mark.parametrize("version", ["0.2.0", "1.0.0", "0.2.0-rc.1", "10.20.30-rc.99"])
def test_the_versions_a_release_may_carry(version: str) -> None:
    assert stamp.VERSION_RE.match(version)


@pytest.mark.parametrize(
    "version",
    ["0.2", "v0.2.0", "0.2.0rc1", "0.2.0-rc1", "0.2.0-beta.1", "0.2.0 ", "", "latest"],
)
def test_anything_that_is_not_a_release_version_is_refused(version: str) -> None:
    """A typo reaching the tag costs a yanked release; failing here costs nothing."""
    assert not stamp.VERSION_RE.match(version)


def test_check_passes_on_a_tree_that_agrees(tree: Path) -> None:
    stamp.stamp(tree, "0.2.0")
    assert stamp.stamp(tree, "0.2.0", check=True)


def test_check_names_every_file_that_disagrees(tree: Path) -> None:
    """It is run right after a stamp, so its job is to describe the damage."""
    stamp.stamp(tree, "0.2.0")
    (tree / INIT).write_text('__version__ = "0.1.9"\n')

    disagreed = stamp.stamp_common.stamp(tree, stamp.rendered, "0.2.0", check=True)
    assert [p.name for p in disagreed] == ["__init__.py"]


def test_a_requirement_left_behind_is_caught(tree: Path) -> None:
    """The failure mode with no other symptom: HACS installs, then cannot resolve."""
    manifest = tree / MANIFEST
    manifest.write_text(
        json.dumps({"requirements": ["whiskerless==0.1.3"], "version": "0.2.0"}, indent=2)
    )
    (tree / "pyproject.toml").write_text('version = "0.2.0"\n')
    (tree / INIT).write_text('__version__ = "0.2.0"\n')

    disagreed = stamp.stamp_common.stamp(tree, stamp.rendered, "0.2.0", check=True)
    assert [p.name for p in disagreed] == ["manifest.json"]


def test_a_file_the_pattern_no_longer_matches_stops_the_stamp(tree: Path) -> None:
    """A reformat that breaks a regex must fail loudly, not skip a file silently."""
    (tree / "pyproject.toml").write_text('[project]\nversion="0.1.3"\n')  # no spaces

    with pytest.raises(ValueError, match="exactly one version record"):
        stamp.stamp(tree, "0.2.0")


def test_a_second_version_key_is_an_error_not_a_coin_flip(tree: Path) -> None:
    """Two matches means the wrong one could be rewritten; refuse instead."""
    (tree / "pyproject.toml").write_text('version = "0.1.3"\nversion = "0.1.3"\n')

    with pytest.raises(ValueError, match="exactly one version record"):
        stamp.stamp(tree, "0.2.0")


def test_the_real_repository_agrees_with_itself_right_now() -> None:
    """The invariant the release workflow asserts, asserted on every test run too.

    Nothing else notices a hand-edited version string until a release is cut.
    """
    version = json.loads(
        (REPO / "custom_components" / "whiskerless" / "manifest.json").read_text()
    )["version"]
    assert stamp.stamp(REPO, version, check=True)
