"""Terminal presentation for the CLI: color, liveness, and emphasis.

The library's other modules never print; this exists so the CLI can say things a
human parses at a glance — most importantly that a silent BLE scan is scanning,
not hung. Stdlib only, deliberately: the CLI ships to PyPI plus four packaged
channels, and a styling dependency would land in every one of them.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from types import TracebackType

# Spinner cadence on a TTY; piped output gets a heartbeat line instead, at a
# pace that reassures without flooding a CI log. Module-level so tests can pace.
_SPIN_INTERVAL = 0.1
_HEARTBEAT_INTERVAL = 60.0
_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


class Console:
    """Decides styling once, so no call site re-litigates it.

    Color is gated per stream on TTY-ness, and ``NO_COLOR`` / ``TERM=dumb`` are
    honored only when nothing was passed explicitly — the ``color`` / ``tty``
    overrides exist for tests and are deliberately immune to the environment.
    Redirected output stays clean text; the animation gates on ``tty`` alone, so
    a piped run never sees cursor control.
    """

    def __init__(self, *, color: bool | None = None, tty: bool | None = None) -> None:
        no_color = bool(os.environ.get("NO_COLOR")) or os.environ.get("TERM") == "dumb"
        self.tty = sys.stdout.isatty() if tty is None else tty
        self.color = (self.tty and not no_color) if color is None else color
        err_tty = sys.stderr.isatty() if tty is None else tty
        self.color_err = (err_tty and not no_color) if color is None else color
        self._lock = threading.Lock()
        self._active: _Progress | None = None

    # -- styled fragments, for lines the CLI assembles itself -------------------
    def accent(self, text: str) -> str:
        return self._c("1;36", text)

    def dim(self, text: str) -> str:
        return self._c("2", text)

    # -- whole lines ------------------------------------------------------------
    def banner(self, message: str) -> None:
        """High visibility for the step that cannot be taken back.

        Bold black-on-yellow, so a danger prompt is not read at the same weight
        as the scrolling lines above it — the one thing a confirmation cannot
        survive is being skimmed.
        """
        self._print(self._c("1;30;103", f"  {message}  "))

    def progress(self, label: str) -> _Progress:
        """Liveness for anything that can exceed a few seconds.

        On a TTY: one row redrawn in place with a spinner and elapsed time,
        erased on exit and replaced by a dim done-line. Piped: a start line,
        then a heartbeat every minute — a log needs liveness too, just without
        cursor control. Use as a context manager.
        """
        return _Progress(self, label)

    def _print(self, text: str) -> None:
        with self._lock:
            if self._active is not None:
                self._active._clear_row()
            print(text, flush=True)

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text


class _Progress:
    """One live progress display; obtained from :meth:`Console.progress`.

    A background thread owns the drawing, because the main thread is typically
    blocked inside the very await the display exists to vouch for. Frames and
    heartbeats are display chrome; only the done-line is a real output line.
    """

    def __init__(self, console: Console, label: str) -> None:
        self._console = console
        self._label = label
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False

    def __enter__(self) -> _Progress:
        con = self._console
        with con._lock:
            con._active = self
            if not con.tty:
                print(f"{self._label} ...", flush=True)
        self._thread = threading.Thread(
            target=self._run, name="whiskerless-progress", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # No done-line on an exception: "scanning — done" above a traceback
        # would claim the very thing that just failed.
        self.close(done=exc_type is None)

    def _run(self) -> None:
        con = self._console
        interval = _SPIN_INTERVAL if con.tty else _HEARTBEAT_INTERVAL
        frame = 0
        try:
            while not self._stop.wait(interval):
                with con._lock:
                    if self._stop.is_set():  # re-check under the lock: no frame after close
                        break
                    tail = con.dim(f"({_elapsed(time.monotonic() - self._t0)})")
                    if con.tty:
                        glyph = con.accent(_FRAMES[frame % len(_FRAMES)])
                        frame += 1
                        sys.stdout.write(f"\r\033[2K{glyph} {self._label} {tail}")
                        sys.stdout.flush()
                    else:
                        print(f"... {self._label} {tail}", flush=True)
        except Exception:  # noqa: BLE001 - a display thread must never take down a run
            return

    def _clear_row(self) -> None:
        # Caller holds the console lock. Suppression is not optional politeness:
        # the terminal can vanish mid-run, and cosmetic cleanup must never be
        # what turns that into a failed provisioning.
        if self._console.tty:
            with contextlib.suppress(OSError):
                sys.stdout.write("\r\033[2K")
                sys.stdout.flush()

    def close(self, *, done: bool) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        con = self._console
        with con._lock:
            self._clear_row()
            if con._active is self:
                con._active = None
        if done:
            elapsed = _elapsed(time.monotonic() - self._t0)
            with contextlib.suppress(OSError):
                print(con.dim(f"{self._label} — done ({elapsed})"), flush=True)
