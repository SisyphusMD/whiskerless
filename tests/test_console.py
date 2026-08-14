"""The CLI's terminal presentation: color gating, liveness, emphasis.

The behaviours that matter: styling is decided once and honors the environment
unless a test overrides it; a piped run never sees cursor control; the progress
display proves liveness in both modes and never celebrates a failure.
"""

from __future__ import annotations

import sys
import time
from typing import Any

import pytest

from whiskerless import console as console_module
from whiskerless.console import Console, _elapsed


@pytest.fixture(autouse=True)
def _fast_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real cadences are human-paced; the tests only need the mechanism."""
    monkeypatch.setattr(console_module, "_SPIN_INTERVAL", 0.01)
    monkeypatch.setattr(console_module, "_HEARTBEAT_INTERVAL", 0.01)


# --- deciding styling once ----------------------------------------------------
def test_a_pipe_gets_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert Console(tty=False).color is False


def test_a_tty_gets_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert Console(tty=True).color is True


@pytest.mark.parametrize("env", [{"NO_COLOR": "1"}, {"TERM": "dumb"}])
def test_the_environment_can_veto_color(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert Console(tty=True).color is False


def test_an_explicit_override_is_immune_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert Console(tty=True, color=True).color is True


def test_tty_detection_asks_the_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    console = Console()
    assert console.tty is False and console.color_err is False


# --- styled fragments and lines -----------------------------------------------
def test_fragments_carry_codes_only_in_color() -> None:
    plain = Console(tty=False, color=False)
    styled = Console(tty=False, color=True)
    assert plain.accent("x") == "x" and plain.dim("x") == "x"
    assert styled.accent("x") == "\033[1;36mx\033[0m"
    assert styled.dim("x") == "\033[2mx\033[0m"


def test_a_banner_stands_out_or_stays_plain(capsys: pytest.CaptureFixture[str]) -> None:
    Console(tty=False, color=True).banner("POWER TOGGLES")
    assert "\033[1;30;103m" in capsys.readouterr().out
    Console(tty=False, color=False).banner("POWER TOGGLES")
    assert capsys.readouterr().out == "  POWER TOGGLES  \n"


def test_elapsed_reads_like_a_clock() -> None:
    assert _elapsed(5) == "5s"
    assert _elapsed(65) == "1m05s"


# --- progress: piped ------------------------------------------------------------
def _drain_until(capsys: pytest.CaptureFixture[str], needle: str) -> str:
    """Accumulate captured output until ``needle`` arrives (bounded).

    A fixed sleep races the thread scheduler for the display thread's first
    wake, and lost that race on a loaded CI runner — the assertion saw start
    and done lines with no heartbeat between them. Polling makes the test
    about WHAT is emitted, not when the scheduler feels like it.
    """
    out = ""
    deadline = time.monotonic() + 5.0
    while needle not in out and time.monotonic() < deadline:
        time.sleep(0.01)
        out += capsys.readouterr().out
    return out


def test_piped_progress_starts_beats_and_finishes(capsys: pytest.CaptureFixture[str]) -> None:
    console = Console(tty=False, color=False)
    with console.progress("scanning"):
        out = _drain_until(capsys, "... scanning (")
    out += capsys.readouterr().out
    assert out.startswith("scanning ...\n")
    assert "... scanning (" in out, "a piped log needs liveness too"
    assert "scanning — done (" in out
    assert "\r" not in out, "cursor control must never reach a pipe"


def test_a_failed_operation_gets_no_done_line(capsys: pytest.CaptureFixture[str]) -> None:
    console = Console(tty=False, color=False)
    with pytest.raises(RuntimeError), console.progress("scanning"):
        raise RuntimeError("boom")
    assert "done" not in capsys.readouterr().out


def test_close_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    console = Console(tty=False, color=False)
    progress = console.progress("scanning").__enter__()
    progress.close(done=True)
    progress.close(done=True)
    assert capsys.readouterr().out.count("done") == 1


# --- progress: TTY --------------------------------------------------------------
def test_tty_progress_redraws_one_row_in_place(capsys: pytest.CaptureFixture[str]) -> None:
    console = Console(tty=True, color=True)
    with console.progress("scanning"):
        out = _drain_until(capsys, "\r\033[2K")
    out += capsys.readouterr().out
    assert "\r\033[2K" in out, "the row is redrawn, not appended"
    assert "scanning" in out
    assert "— done (" in out, "the done-line closes the display"


def test_a_line_printed_mid_progress_clears_the_row_first(
    capsys: pytest.CaptureFixture[str],
) -> None:
    console = Console(tty=True, color=False)
    with console.progress("scanning"):
        out = _drain_until(capsys, "\r\033[2K")  # at least one frame has drawn
        console.banner("look out")
    out += capsys.readouterr().out
    assert "look out" in out
    assert out.index("\r\033[2K") < out.index("look out"), "the spinner row must not bleed into it"


def test_a_vanished_terminal_never_breaks_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The display thread and its cleanup swallow a dying stdout; the operation
    the display merely decorates must survive it."""
    console = Console(tty=True, color=False)

    class Vanished:
        def write(self, _text: str) -> int:
            raise OSError("terminal gone")

        def flush(self) -> None:
            raise OSError("terminal gone")

    progress = console.progress("scanning").__enter__()
    _drain_until(capsys, "\r\033[2K")  # at least one frame drew against the real stream
    monkeypatch.setattr(sys, "stdout", Vanished())
    time.sleep(0.03)  # frames now hit the dead stream; the thread must swallow
    progress.close(done=True)  # clear + done-line against the dead stream


def test_no_frame_is_drawn_after_close_wins_the_race(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A frame that slips out after close would repaint the row the close just
    erased. The drawing thread re-checks the stop flag under the console lock,
    so a close that lands while it waits for that lock silences it."""
    console = Console(tty=True, color=False)
    progress = console.progress("scanning").__enter__()
    time.sleep(0.03)
    with console._lock:
        time.sleep(0.03)  # the wait elapses; the thread is now parked on the lock
        progress._stop.set()  # close's signal lands before the thread gets it
    progress.close(done=False)
    assert not capsys.readouterr().out.endswith("scanning")


def test_progress_returns_a_context_manager(capsys: pytest.CaptureFixture[str]) -> None:
    console = Console(tty=False, color=False)
    handle: Any = console.progress("scanning")
    assert handle.__enter__() is handle
    handle.__exit__(None, None, None)
