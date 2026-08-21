"""Best-effort "you're out of date" nudge for the CLI.

Ported in contract, not in code, from dreame-valetudo's `update_check`: this project's channels and
upgrade commands are different, but the four properties that make such a nudge safe are the same.

  * **Never blocks and never fails loudly.** A short timeout, and every failure is swallowed — a
    tool that cannot reach GitHub is still a working tool.
  * **Cached once per day.** A marker in the store records the day and the version last seen, so
    the network is touched at most daily and the cached answer still drives the nudge between times.
  * **Detect and instruct, never self-update.** Upgrading across brew, apt, dnf, pipx and a raw
    binary is fragile, and doing it underneath a running provisioning session would be worse.
  * **Opt out** with ``WHISKERLESS_NO_UPDATE_CHECK=1``.

CLI only. The Home Assistant integration is updated through HACS, which already tells the user, and
a library import must never reach the network.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from . import __version__

_LATEST_URL = "https://api.github.com/repos/SisyphusMD/whiskerless/releases/latest"
#: Newest-first, prereleases included. `/releases/latest` EXCLUDES prereleases, so a machine on
#: rc.35 could never be told about rc.36 — the whole candidate channel was invisible to the very
#: people testing it, right up until the stable release appeared.
_RELEASES_URL = "https://api.github.com/repos/SisyphusMD/whiskerless/releases?per_page=10"
_MARKER = ".update-check"
#: Per CHANNEL. Both installs can share one WHISKERLESS_HOME, and a single marker was
#: overwritten on every switch between them — so alternating the two refetched on every
#: command and paid the full timeout each time, which is the cost the cache exists to avoid.
_RC_MARKER = ".update-check-rc"
_OPT_OUT = "WHISKERLESS_NO_UPDATE_CHECK"
_TIMEOUT_SECONDS = 3.0


def _channel_hint() -> str:
    """The upgrade command for however this copy was installed.

    Decided from where the running program actually lives, which is the only evidence available
    without asking a package manager a question that costs a subprocess.
    """
    here = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else Path(sys.executable)
    # Forward slashes whatever the platform. `str(Path(...))` uses backslashes on Windows, so
    # every POSIX-shaped substring below could never match there and a normal pipx or uv install
    # fell through to the pip fallback — telling the user to upgrade with the managed venv's own
    # pip instead of the tool that owns it. The README documents the Windows install.
    text = here.as_posix()
    if "/Cellar/" in text or "/linuxbrew/" in text or "/homebrew/" in text:
        # `whiskerless-rc` is a SEPARATE formula, and a machine on the candidate channel normally
        # does not have the stable one installed at all. Naming it there either failed outright or
        # quietly moved the user off the channel they chose to be on.
        formula = "whiskerless-rc" if "/Cellar/whiskerless-rc/" in text else "whiskerless"
        return f"brew upgrade sisyphusmd/tap/{formula}"
    if "/pipx/" in text:
        return "pipx upgrade whiskerless"
    if "/uv/tools/" in text or "/uv/tool/" in text:
        return "uv tool upgrade whiskerless"
    # A pip install, before the path rules below. Asked of the PACKAGE's own location rather than
    # the launcher's, because a system-wide `pip install` puts its console script in
    # /usr/local/bin — where the next rule would have answered "apt/dnf, or re-download the .pkg",
    # none of which upgrades it — and a virtualenv install lands somewhere nothing recognises at
    # all. site-packages/dist-packages is the one thing that identifies either.
    site = Path(__file__).resolve().parent.parent
    if site.name in {"site-packages", "dist-packages"}:
        return f"{sys.executable} -m pip install --upgrade whiskerless"
    if text.startswith("/usr/bin/") or text.startswith("/usr/local/bin/"):
        return "your package manager (apt/dnf), or re-download the .pkg"
    return "uv tool upgrade whiskerless, pipx upgrade whiskerless, or re-download the binary"


def _newer(latest: str, running: str) -> bool:
    """Whether `latest` is a higher release than `running`, comparing numerically.

    A string compare would call 0.10.0 older than 0.9.0. Anything unparseable means "do not nudge":
    a wrong nudge is worse than a missing one.
    """

    def parts(value: str) -> tuple[int, ...] | None:
        """(major, minor, patch, rc) — where a release sorts ABOVE its own candidates.

        Dropping the suffix made `0.2.0-rc.35` compare equal to `0.2.0`, so the people most in
        need of the nudge — everyone running a candidate — were the only ones never told the final
        release had shipped. A large sentinel puts a release after every rc of the same number.
        """
        head, _, suffix = value.lstrip("v").partition("-")
        try:
            numbers = tuple(int(p) for p in head.split("."))
        except ValueError:
            return None
        if not suffix:
            return (*numbers, 1 << 30)
        candidate = suffix.rpartition(".")[2]
        return (*numbers, int(candidate)) if candidate.isdigit() else None

    a, b = parts(latest), parts(running)
    return a is not None and b is not None and a > b


def _cached(marker: Path) -> tuple[str, str | None, str] | None:
    """(day, latest, channel) from the marker; `latest` is None when that day's check failed.

    A failed day is still a day. Requiring `latest` here made the failure marker unreadable, so an
    offline machine refetched on every command — the exact cost the marker exists to avoid.
    """
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
        data = json.loads(marker.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            latest = data.get("latest")
            # A marker written before the channel was recorded reads as "stable", which is the
            # only channel that existed then; a candidate install simply refetches once.
            channel = data.get("channel")
            return (
                str(data["day"]),
                str(latest) if isinstance(latest, str) else None,
                str(channel) if isinstance(channel, str) else "stable",
            )
    return None


def _fetch_latest(running: str = __version__) -> str | None:
    """The newest release this copy should be told about.

    Which endpoint depends on the CHANNEL. A stable install is asking about stable releases, and
    `/releases/latest` answers exactly that. A candidate install is asking about candidates, which
    that endpoint never returns — so it enumerates instead and takes the newest entry, prereleases
    included. `_newer()` still decides whether the answer is worth printing.
    """
    url = _RELEASES_URL if "-" in running else _LATEST_URL
    with contextlib.suppress(urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, list):
            # Newest first is GitHub's documented order, but the winner is chosen by comparison
            # rather than by position: a draft or a re-tagged release would otherwise decide it.
            tags = [r["tag_name"] for r in payload if isinstance(r.get("tag_name"), str)
                    and not r.get("draft")]
            best: str | None = None
            for tag in tags:
                if best is None or _newer(tag, best):
                    best = tag
            return best
        tag = payload["tag_name"]
        return str(tag) if isinstance(tag, str) else None
    return None


def check(root: Path, *, env: dict[str, str] | None = None) -> str | None:
    """The nudge to print, or None. Never raises."""
    environ = os.environ if env is None else env
    if environ.get(_OPT_OUT):
        return None
    channel = "rc" if "-" in __version__ else "stable"
    marker = root / (_RC_MARKER if channel == "rc" else _MARKER)
    today = date.today().isoformat()
    cached = _cached(marker)
    # The recorded channel is checked as well as the filename: a marker copied or restored from
    # the other install would otherwise let an rc run tell a stable install about a prerelease its
    # upgrade command cannot install.
    if cached is not None and cached[0] == today and cached[2] == channel:
        latest: str | None = cached[1]
    else:
        latest = _fetch_latest()
        if latest is None:
            # Keep yesterday's answer rather than nothing: an unreachable GitHub should not make an
            # out-of-date install look current.
            latest = cached[1] if cached and cached[2] == channel else None
            # Record the ATTEMPT even though it failed. Without this an offline machine retries on
            # every single command and pays the full timeout each time, which is exactly the cost
            # the daily cache exists to avoid — and it is worst precisely when the network is worst.
            with contextlib.suppress(OSError):
                marker.parent.mkdir(parents=True, exist_ok=True)
                payload = {"day": today, "channel": channel}
                if latest is not None:
                    payload["latest"] = latest
                marker.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        else:
            with contextlib.suppress(OSError):
                # The parent may not exist yet — a fresh install, or a WHISKERLESS_HOME pointed
                # somewhere new. Without this the write raises, the failure is suppressed by
                # design, and the "once a day" promise silently becomes "every single command",
                # each paying the full network timeout.
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    json.dumps({"day": today, "latest": latest, "channel": channel}) + "\n",
                    encoding="utf-8",
                )
    if latest is None or not _newer(latest, __version__):
        return None
    return (
        f"  a newer whiskerless is out ({latest.lstrip('v')}; this is {__version__}) — "
        f"upgrade with: {_channel_hint()}"
    )
