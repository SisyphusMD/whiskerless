"""`whiskerless uninstall` — the command, as distinct from the detection behind it.

What matters here is not that it can run `brew uninstall`. It is that it never runs anything the
user did not agree to, that it says out loud which installs it found before asking, and that it
leaves the store alone: the CA private key in there is what every robot's certificate chains to,
and losing it means re-provisioning every robot by hand.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from whiskerless.cli import main
from whiskerless.installs import Install


class _Process:
    """Stands in for what `asyncio.create_subprocess_exec` returns."""

    def __init__(self, code: int) -> None:
        self._code = code

    async def wait(self) -> int:
        return self._code


def _spawner(codes: dict[str, int], calls: list[list[str]]):
    async def _spawn(*argv: str) -> _Process:
        calls.append(list(argv))
        return _Process(codes.get(argv[0], 0))

    return _spawn


def _run(found: list[Install], *, answer: str = "y", codes: dict[str, int] | None = None):
    calls: list[list[str]] = []
    with (
        patch("whiskerless.installs.find_installs", return_value=found),
        patch("builtins.input", return_value=answer),
        patch("asyncio.create_subprocess_exec", _spawner(codes or {}, calls)),
    ):
        return main(["uninstall"]), calls


BREW = Install("Homebrew", Path("/opt/homebrew/Cellar/whiskerless"),
               ["brew", "uninstall", "whiskerless"])
PKG = Install("macOS .pkg", Path("/usr/local/bin/whiskerless"),
              ["sudo", "rm", "-f", "/usr/local/bin/whiskerless"],
              "then run: sudo pkgutil --forget com.sisyphusmd.whiskerless")
HACS = Install("Home Assistant integration", Path("/config/custom_components/whiskerless"),
               [], "remove it through HACS, then delete the integration")


def test_says_so_when_there_is_nothing_to_remove(capsys: pytest.CaptureFixture[str]) -> None:
    code, calls = _run([])
    assert code == 0
    assert calls == []
    assert "no installs of whiskerless found" in capsys.readouterr().out


def test_every_install_is_listed_with_the_command_that_removes_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run([BREW, PKG], answer="n")
    out = capsys.readouterr().out
    assert "Homebrew" in out
    assert "brew uninstall whiskerless" in out
    # A removal that needs a second manual step says both, or the user removes the binary and
    # leaves macOS believing the package is still installed.
    assert "pkgutil --forget" in out


def test_declining_removes_nothing_and_is_not_a_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 0, per the CLI contract: a deliberate abort is a decision, not an error."""
    code, calls = _run([BREW], answer="n")
    assert code == 0
    assert calls == []
    assert "aborted" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["y", "yes", "YES"])
def test_agreeing_runs_each_removal(answer: str) -> None:
    code, calls = _run([BREW, PKG], answer=answer)
    assert code == 0
    assert calls == [
        ["brew", "uninstall", "whiskerless"],
        ["sudo", "rm", "-f", "/usr/local/bin/whiskerless"],
    ]


def test_anything_but_yes_declines(capsys: pytest.CaptureFixture[str]) -> None:
    """The default on a bare enter is NO — this uninstalls things."""
    _, calls = _run([BREW], answer="")
    assert calls == []


def test_the_store_is_named_as_untouched_before_the_question(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run([BREW], answer="n")
    out = capsys.readouterr().out
    assert "NOT touched" in out


def test_a_root_removal_warns_before_asking(capsys: pytest.CaptureFixture[str]) -> None:
    _run([PKG], answer="n")
    assert "sudo will ask for your password" in capsys.readouterr().out


def test_a_failed_removal_is_reported_with_the_command_to_run_by_hand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _ = _run([BREW], codes={"brew": 1})
    assert code == 1
    assert "brew uninstall whiskerless" in capsys.readouterr().err


def test_one_failure_does_not_stop_the_others(capsys: pytest.CaptureFixture[str]) -> None:
    """Each install is independent; a brew failure must not leave the .pkg behind too."""
    code, calls = _run([BREW, PKG], codes={"brew": 1})
    assert code == 1
    assert ["sudo", "rm", "-f", "/usr/local/bin/whiskerless"] in calls


def test_installs_that_cannot_be_removed_automatically_are_still_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, calls = _run([HACS])
    assert code == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "nothing here can be removed automatically" in out
    assert "HACS" in out


def test_manual_steps_are_repeated_after_a_successful_removal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The HACS line scrolls past before the removals run; the user needs it at the end, where
    they are actually looking when the command finishes."""
    code, _ = _run([BREW, HACS])
    assert code == 0
    out = capsys.readouterr().out
    assert "still to do by hand" in out
    assert out.rindex("HACS") > out.index("removing the Homebrew install")


def test_a_removable_install_with_a_manual_step_still_reports_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The macOS .pkg is removable AND needs `pkgutil --forget` afterwards. Repeating notes only
    for NON-removable installs ended the command with "removed." while the receipt survived — and
    a surviving receipt blocks a later reinstall from repairing anything."""
    code, _ = _run([PKG])
    assert code == 0
    out = capsys.readouterr().out
    assert "still to do by hand" in out
    assert "pkgutil --forget" in out.split("still to do by hand")[1]


def test_uninstall_works_when_the_store_was_written_by_a_newer_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The duplicate-install case this command exists for is exactly where an older copy on PATH
    meets a store a newer one wrote. Opening it there refused the cleanup that would fix it."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    (tmp_path / ".layout").write_text('{"layout_version": "9999", "min_tool_version": "99.0.0"}\n')
    code, _ = _run([BREW], answer="n")
    assert code == 0
    assert str(tmp_path) in capsys.readouterr().out


def test_a_closed_stdin_declines_rather_than_crashing(capsys: pytest.CaptureFixture[str]) -> None:
    """Ctrl-D, a pipe from an empty source, a CI step. EOFError escaped `main()` as a traceback
    from a half-asked question about removing things."""
    with (
        patch("whiskerless.installs.find_installs", return_value=[BREW]),
        patch("builtins.input", side_effect=EOFError),
        patch("asyncio.create_subprocess_exec"),
    ):
        assert main(["uninstall"]) == 0
    assert "aborted" in capsys.readouterr().out


def test_the_update_check_never_opens_the_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`uninstall` promises the store is untouched. The pre-dispatch nudge opened it anyway —
    running the legacy migration and writing a cache marker into a store being walked away from."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    with (
        patch("whiskerless.installs.find_installs", return_value=[]),
        patch("whiskerless.update_check.check") as check,
    ):
        main(["uninstall"])
    check.assert_not_called()
    assert not (tmp_path / ".update-check").exists()


def test_a_missing_remover_does_not_abandon_the_other_installs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stale pipx or uv environment whose manager is no longer on PATH raises FileNotFoundError.
    Letting it escape aborted the whole command and left every valid install after it in place."""
    calls: list[list[str]] = []

    async def _spawn(*argv: str) -> _Process:
        if argv[0] == "pipx":
            raise FileNotFoundError(argv[0])
        calls.append(list(argv))
        return _Process(0)

    stale = Install("pipx", Path("/x/pipx/venvs/whiskerless"), ["pipx", "uninstall", "whiskerless"])
    with (
        patch("whiskerless.installs.find_installs", return_value=[stale, BREW]),
        patch("builtins.input", return_value="y"),
        patch("asyncio.create_subprocess_exec", _spawn),
    ):
        code = main(["uninstall"])
    assert code == 1
    assert ["brew", "uninstall", "whiskerless"] in calls
    assert "pipx uninstall whiskerless" in capsys.readouterr().err


def test_manual_steps_are_printed_even_when_another_removal_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed Homebrew removal alongside a successfully deleted .pkg binary never mentioned
    `pkgutil --forget` — and the surviving receipt blocks a later reinstall from repairing it."""
    code, _ = _run([BREW, PKG], codes={"brew": 1})
    assert code == 1
    assert "pkgutil --forget" in capsys.readouterr().out
