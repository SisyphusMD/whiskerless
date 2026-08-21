"""Finding every copy of the tool on a machine — the basis for `whiskerless uninstall`.

Exercised against a fake filesystem so the whole table is reachable with nothing installed.
The sibling dreame-valetudo project has the same file for the same reason; the channels differ.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whiskerless.installs import PKG_IDENTIFIER, find_installs


def _mk(root: Path, *dirs: str) -> None:
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)


def _receipt(root: Path) -> None:
    """What the macOS installer writes. Without it a bare binary at /usr/local/bin is somebody's
    pip console script or a hand-copied release, not a package."""
    _mk(root, "var/db/receipts")
    (root / "var/db/receipts" / f"{PKG_IDENTIFIER}.plist").write_text("<plist/>\n")


def _found(root: Path, **env: str) -> list:
    """Everything found, minus whatever the TEST ENVIRONMENT itself is.

    These tests run from an editable install inside a git checkout, so both of those are genuinely
    present and would otherwise appear in every single case. Anything under the fake root is the
    case under test and is kept.
    """
    return [
        i
        for i in find_installs({"HOME": str(root), **env}, root)
        if i.kind != "source checkout" and (i.marker == root or root in i.marker.parents)
    ]


def test_finds_nothing_on_a_bare_system(tmp_path: Path) -> None:
    assert _found(tmp_path) == []


def test_brew_is_identified_by_its_cellar_not_a_bin_entry(tmp_path: Path) -> None:
    """On Intel macs Homebrew's prefix IS /usr/local, the same place the .pkg installs — so a bare
    bin/ entry cannot tell them apart and the Cellar is what proves it."""
    _mk(tmp_path, "opt/homebrew/Cellar/whiskerless")
    kinds = {i.kind for i in _found(tmp_path)}
    assert "Homebrew" in kinds
    assert "macOS .pkg" not in kinds


def test_the_rc_formula_is_reported_separately(tmp_path: Path) -> None:
    _mk(tmp_path, "opt/homebrew/Cellar/whiskerless-rc")
    i = next(i for i in _found(tmp_path) if "candidate" in i.kind)
    assert i.removal == ["/opt/homebrew/bin/brew", "uninstall", "whiskerless-rc"]


def test_an_explicit_homebrew_prefix_is_honoured(tmp_path: Path) -> None:
    _mk(tmp_path, "somewhere/else/Cellar/whiskerless")
    kinds = {i.kind for i in _found(tmp_path, HOMEBREW_PREFIX="/somewhere/else")}
    assert "Homebrew" in kinds


def test_the_pkg_binary_is_found_and_its_receipt_is_forgotten_too(tmp_path: Path) -> None:
    _mk(tmp_path, "usr/local/bin")
    (tmp_path / "usr/local/bin/whiskerless").write_text("#!/bin/sh\n")
    _receipt(tmp_path)
    i = next(i for i in _found(tmp_path) if i.kind == "macOS .pkg")
    assert i.removal == ["sudo", "rm", "-f", str(tmp_path / "usr/local/bin/whiskerless")]
    # Removing the binary without forgetting the receipt leaves macOS believing the package is
    # still installed, which blocks a later reinstall from repairing it.
    assert PKG_IDENTIFIER in i.note


def test_a_homebrew_symlink_in_usr_local_bin_is_not_counted_as_a_pkg(tmp_path: Path) -> None:
    """Intel Homebrew symlinks into /usr/local/bin, the exact path the .pkg writes a real file to.
    Counting the symlink would report one install as two and offer `sudo rm` on brew's own link."""
    _mk(tmp_path, "usr/local/Cellar/whiskerless/1.0/bin", "usr/local/bin")
    target = tmp_path / "usr/local/Cellar/whiskerless/1.0/bin/whiskerless"
    target.write_text("#!/bin/sh\n")
    (tmp_path / "usr/local/bin/whiskerless").symlink_to(target)
    kinds = [i.kind for i in _found(tmp_path)]
    assert kinds == ["Homebrew"]


def test_deb_is_identified_by_its_doc_directory_not_the_binary(tmp_path: Path) -> None:
    """A binary at /usr/bin could equally be one someone copied off a release page by hand, and
    telling them to `apt-get remove` it reports a package that was never installed."""
    _mk(tmp_path, "usr/bin")
    (tmp_path / "usr/bin/whiskerless").write_text("#!/bin/sh\n")
    assert _found(tmp_path) == []


def test_deb_and_rpm_share_a_path_so_the_remover_follows_the_system(tmp_path: Path) -> None:
    _mk(tmp_path, "usr/share/doc/whiskerless", "usr/bin")
    (tmp_path / "usr/bin/apt-get").write_text("")
    i = next(i for i in _found(tmp_path) if "package" in i.kind)
    assert i.kind == ".deb package"
    assert i.removal == ["sudo", "apt-get", "remove", "-y", "whiskerless"]


@pytest.mark.parametrize(
    ("manager", "expected"),
    [
        ("zypper", ["sudo", "zypper", "remove", "-y", "whiskerless"]),
        ("dnf", ["sudo", "dnf", "remove", "-y", "whiskerless"]),
        ("yum", ["sudo", "yum", "remove", "-y", "whiskerless"]),
    ],
)
def test_rpm_removal_uses_the_native_package_manager(
    tmp_path: Path, manager: str, expected: list[str]
) -> None:
    _mk(tmp_path, "usr/share/doc/whiskerless", "usr/bin")
    (tmp_path / "usr/bin" / manager).write_text("")
    i = next(i for i in _found(tmp_path) if "package" in i.kind)
    assert i.kind == ".rpm package"
    assert i.removal == expected


def test_rpm_falls_back_to_rpm_itself_when_no_manager_is_present(tmp_path: Path) -> None:
    _mk(tmp_path, "usr/share/doc/whiskerless")
    i = next(i for i in _found(tmp_path) if "package" in i.kind)
    assert i.removal == ["sudo", "rpm", "-e", "whiskerless"]


def test_user_level_tool_installs_are_found_under_the_configured_home(tmp_path: Path) -> None:
    _mk(tmp_path, ".local/share/uv/tools/whiskerless", ".local/pipx/venvs/whiskerless")
    removals = {i.kind: i.removal for i in _found(tmp_path)}
    assert removals["uv tool"] == ["uv", "tool", "uninstall", "whiskerless"]
    assert removals["pipx"] == ["pipx", "uninstall", "whiskerless"]


@pytest.mark.parametrize("layout", ["config", ".homeassistant"])
def test_the_home_assistant_integration_is_reported_but_never_removed(
    tmp_path: Path, layout: str
) -> None:
    """HACS owns its lifecycle, it is as often a different machine, and deleting the directory
    behind HACS's back leaves a config entry pointing at nothing."""
    _mk(tmp_path, f"{layout}/custom_components/whiskerless")
    i = next(i for i in _found(tmp_path) if i.kind == "Home Assistant integration")
    assert i.removal == []
    assert "HACS" in i.note


def test_brew_and_pkg_together_are_both_reported(tmp_path: Path) -> None:
    """The case the whole module exists for: two installs, and PATH order alone decides which one
    `whiskerless` runs."""
    _mk(tmp_path, "opt/homebrew/Cellar/whiskerless", "usr/local/bin")
    (tmp_path / "usr/local/bin/whiskerless").write_text("#!/bin/sh\n")
    _receipt(tmp_path)
    assert {i.kind for i in _found(tmp_path)} == {"Homebrew", "macOS .pkg"}


def test_a_source_checkout_has_no_command_to_run(tmp_path: Path) -> None:
    """Reported so the list is honest about what is on the machine, with no removal: deleting
    somebody's working clone is not this command's business."""
    checkout = next(
        i for i in find_installs({"HOME": str(tmp_path)}, tmp_path) if i.kind == "source checkout"
    )
    assert checkout.removal == []
    assert checkout.note


@pytest.mark.parametrize("home", [".local/share/pipx/venvs", ".local/pipx/venvs"])
def test_both_pipx_homes_are_found(tmp_path: Path, home: str) -> None:
    """pipx's default moved under ~/.local/share. Probing only the legacy path made a normal
    current install invisible, so `uninstall` reported no pipx copy at all."""
    _mk(tmp_path, f"{home}/whiskerless")
    assert [i.kind for i in _found(tmp_path)] == ["pipx"]


def test_one_pipx_install_is_reported_once(tmp_path: Path) -> None:
    """Both paths present is a migrated install, not two of them."""
    _mk(tmp_path, ".local/share/pipx/venvs/whiskerless", ".local/pipx/venvs/whiskerless")
    assert [i.kind for i in _found(tmp_path)] == ["pipx"]


def test_a_debian_dist_packages_install_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Debian and Ubuntu rename the directory. Matching only `site-packages` missed an ordinary
    pip install on the distributions this project ships packages for."""
    pkg = tmp_path / "usr/lib/python3/dist-packages/whiskerless"
    pkg.mkdir(parents=True)
    monkeypatch.setattr("whiskerless.installs.__file__", str(pkg / "installs.py"))
    kinds = [i.kind for i in _found(tmp_path)]
    assert "pip (this interpreter)" in kinds


def test_an_editable_install_is_reported_as_more_than_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pip install -e .` is what CONTRIBUTING tells a contributor to run. Its code lives in the
    checkout, so no path tells it from a bare clone — and reporting only "source checkout" meant
    deleting the clone left the console script and pip's metadata behind."""
    checkout = tmp_path / "repo" / "src" / "whiskerless"
    checkout.mkdir(parents=True)
    monkeypatch.setattr("whiskerless.installs.__file__", str(checkout / "installs.py"))
    monkeypatch.setattr("whiskerless.installs._installed_as_editable", lambda: True)
    kinds = [i.kind for i in _found(tmp_path)]
    assert "pip (editable, this interpreter)" in kinds


def test_a_bare_clone_on_the_path_is_not_called_an_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "repo" / "src" / "whiskerless"
    checkout.mkdir(parents=True)
    monkeypatch.setattr("whiskerless.installs.__file__", str(checkout / "installs.py"))
    monkeypatch.setattr("whiskerless.installs._installed_as_editable", lambda: False)
    assert _found(tmp_path) == []


def test_a_binary_with_no_receipt_is_not_called_a_macos_package(tmp_path: Path) -> None:
    """A system-wide pip console script and a hand-copied release binary both live here, on Linux
    and on macOS alike. Calling either a `.pkg` offered `sudo rm` on a file no package manager
    owns, and told the user to forget a receipt that was never written."""
    _mk(tmp_path, "usr/local/bin")
    (tmp_path / "usr/local/bin/whiskerless").write_text("#!/bin/sh\n")
    assert _found(tmp_path) == []
    _receipt(tmp_path)
    assert [i.kind for i in _found(tmp_path)] == ["macOS .pkg"]


def test_an_exported_prefix_does_not_hide_the_other_homebrew(tmp_path: Path) -> None:
    """An Apple Silicon machine that kept its Intel Homebrew has installs under both, and exports
    HOMEBREW_PREFIX=/opt/homebrew as a matter of course. Honouring only that skipped /usr/local,
    so `uninstall` missed the second copy it exists to find."""
    _mk(tmp_path, "opt/homebrew/Cellar/whiskerless", "usr/local/Cellar/whiskerless")
    found = _found(tmp_path, HOMEBREW_PREFIX="/opt/homebrew")
    assert [i.kind for i in found] == ["Homebrew", "Homebrew"]
    assert {str(i.marker) for i in found} == {
        str(tmp_path / "opt/homebrew/Cellar/whiskerless"),
        str(tmp_path / "usr/local/Cellar/whiskerless"),
    }


def test_a_prefix_that_is_already_a_default_is_not_scanned_twice(tmp_path: Path) -> None:
    _mk(tmp_path, "usr/local/Cellar/whiskerless")
    assert len(_found(tmp_path, HOMEBREW_PREFIX="/usr/local")) == 1


def test_each_homebrew_is_removed_by_its_own_brew(tmp_path: Path) -> None:
    """With installs under both prefixes, a bare `brew` sent both removals to whichever Homebrew
    PATH picked: the first succeeded, the second failed against a formula it had never installed,
    and the other copy stayed — the exact situation `uninstall` exists to clear up."""
    _mk(tmp_path, "opt/homebrew/Cellar/whiskerless", "usr/local/Cellar/whiskerless")
    assert {i.removal[0] for i in _found(tmp_path)} == {
        "/opt/homebrew/bin/brew",
        "/usr/local/bin/brew",
    }


def test_the_windows_pipx_home_is_found(tmp_path: Path) -> None:
    """The README documents the Windows install, where pipx lives at ~/pipx rather than either
    POSIX path. Missing it meant the same venv was reported as a generic pip install, and
    `uninstall` offered to run pip inside pipx's managed environment."""
    _mk(tmp_path, "pipx/venvs/whiskerless")
    assert [i.kind for i in _found(tmp_path)] == ["pipx"]


def test_a_relocated_pipx_home_is_honoured(tmp_path: Path) -> None:
    """PIPX_HOME moves it anywhere, on any platform."""
    _mk(tmp_path, "elsewhere/venvs/whiskerless")
    assert [i.kind for i in _found(tmp_path, PIPX_HOME=str(tmp_path / "elsewhere"))] == ["pipx"]


def test_a_linuxbrew_install_is_found_without_an_exported_prefix(tmp_path: Path) -> None:
    """The project ships a Linux Homebrew formula and bottles for it. Scanning only the two macOS
    defaults meant `uninstall` could not find the install the tap had just put there."""
    _mk(tmp_path, "home/linuxbrew/.linuxbrew/Cellar/whiskerless")
    assert [i.kind for i in _found(tmp_path)] == ["Homebrew"]
