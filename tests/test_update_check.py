"""The out-of-date nudge: unobtrusive, cached, and never wrong in the loud direction."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path, PurePosixPath

import pytest

from whiskerless import update_check


@pytest.mark.parametrize(
    ("latest", "running", "expected"),
    [
        ("v0.10.0", "0.9.0", True),   # a string compare calls this older
        ("v0.2.0", "0.2.0", False),
        ("v0.1.0", "0.2.0", False),
        ("v0.2.1", "0.2.0", True),
        ("not-a-version", "0.2.0", False),
        ("v0.2.0", "garbage", False),
    ],
)
def test_versions_compare_numerically(latest: str, running: str, expected: bool) -> None:
    assert update_check._newer(latest, running) is expected


def test_the_opt_out_short_circuits_before_any_network(tmp_path: Path) -> None:
    assert update_check.check(tmp_path, env={"WHISKERLESS_NO_UPDATE_CHECK": "1"}) is None


def test_todays_cache_is_used_without_touching_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        update_check, "_fetch_latest", lambda: pytest.fail("network touched despite a fresh cache")
    )
    (tmp_path / update_check._MARKER).write_text(
        json.dumps({"day": date.today().isoformat(), "latest": "v99.0.0"})
    )

    message = update_check.check(tmp_path, env={})

    assert message is not None
    assert "99.0.0" in message


def test_a_stale_cache_survives_an_unreachable_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable GitHub must not make an out-of-date install look current."""
    monkeypatch.setattr(update_check, "_fetch_latest", lambda: None)
    (tmp_path / update_check._MARKER).write_text(json.dumps({"day": "1999-01-01", "latest": "v99.0.0"}))

    assert "99.0.0" in (update_check.check(tmp_path, env={}) or "")


def test_a_failed_lookup_with_no_cache_says_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update_check, "_fetch_latest", lambda: None)

    assert update_check.check(tmp_path, env={}) is None


def test_a_corrupt_marker_is_ignored_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update_check, "_fetch_latest", lambda: None)
    (tmp_path / update_check._MARKER).write_text("{not json")

    assert update_check.check(tmp_path, env={}) is None


def test_the_result_is_cached_after_a_successful_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update_check, "_fetch_latest", lambda: "v99.0.0")

    update_check.check(tmp_path, env={})

    stored = json.loads((tmp_path / update_check._MARKER).read_text())
    assert stored == {
        "day": date.today().isoformat(),
        "latest": "v99.0.0",
        # The channel is recorded: a stable and a candidate install can share one home,
        # and an entry that did not say which endpoint produced it was reused by both.
        "channel": "stable",
    }


def test_a_failed_check_still_costs_only_one_attempt_a_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offline machine used to retry on every single command and pay the full timeout each
    time — worst exactly when the network is worst, which is the opposite of what a daily cache
    is for."""
    calls = []

    def _fail() -> None:
        calls.append(1)
        return None

    monkeypatch.setattr(update_check, "_fetch_latest", _fail)
    update_check.check(tmp_path)
    update_check.check(tmp_path)
    assert len(calls) == 1, "the second call went back to the network"


@pytest.mark.parametrize(
    ("latest", "running", "newer"),
    [
        ("v0.2.0", "0.2.0-rc.35", True),      # the case that was silently broken
        ("v0.2.0-rc.36", "0.2.0-rc.35", True),
        ("v0.2.0-rc.1", "0.2.0", False),      # a candidate is never newer than its own release
        ("v0.2.0", "0.2.0", False),
        ("v0.10.0", "0.9.0", True),
    ],
)
def test_a_release_sorts_above_its_own_candidates(latest: str, running: str, newer: bool) -> None:
    """Dropping the suffix made 0.2.0-rc.35 compare EQUAL to 0.2.0, so the people most in need of
    the nudge — everyone on a candidate — were the only ones never told the release had shipped."""
    assert update_check._newer(latest, running) is newer


@pytest.mark.parametrize(
    ("site_dir", "expected"),
    [("site-packages", True), ("dist-packages", True), ("whiskerless", False)],
)
def test_a_pip_install_is_told_to_use_pip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, site_dir: str, expected: bool
) -> None:
    """A system-wide pip puts its console script in /usr/local/bin, where the path rule answered
    "apt/dnf, or re-download the .pkg" — none of which upgrades it. A virtualenv install landed
    somewhere nothing recognised at all."""
    pkg = tmp_path / site_dir / "whiskerless"
    pkg.mkdir(parents=True)
    monkeypatch.setattr(update_check, "__file__", str(pkg / "update_check.py"))
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/whiskerless"])
    hint = update_check._channel_hint()
    assert ("-m pip install --upgrade whiskerless" in hint) is expected


def test_a_candidate_install_asks_the_endpoint_that_returns_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/releases/latest` excludes prereleases, so a machine on rc.35 could never be told about
    rc.36 — the candidate channel was invisible to the people testing it."""
    asked: list[str] = []

    class _Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return json.dumps(
            [{"tag_name": "v0.2.0-rc.36"}, {"tag_name": "v0.2.0-rc.35"}]
        ).encode()

    def _open(url, timeout=None):
        asked.append(url)
        return _Response()

    monkeypatch.setattr(update_check.urllib.request, "urlopen", _open)
    assert update_check._fetch_latest("0.2.0-rc.35") == "v0.2.0-rc.36"
    assert "releases?" in asked[0]


def test_a_stable_install_still_asks_for_the_latest_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    class _Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return json.dumps({"tag_name": "v0.3.0"}).encode()

    def _open(url, timeout=None):
        asked.append(url)
        return _Response()

    monkeypatch.setattr(update_check.urllib.request, "urlopen", _open)
    assert update_check._fetch_latest("0.2.0") == "v0.3.0"
    assert asked[0].endswith("/releases/latest")


def test_a_draft_release_is_never_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return json.dumps(
            [{"tag_name": "v0.9.0-rc.1", "draft": True}, {"tag_name": "v0.2.0-rc.36"}]
        ).encode()

    monkeypatch.setattr(update_check.urllib.request, "urlopen", lambda *a, **k: _Response())
    assert update_check._fetch_latest("0.2.0-rc.35") == "v0.2.0-rc.36"


def test_the_candidate_formula_is_named_for_a_candidate_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`whiskerless-rc` is a separate formula, and a machine on the candidate channel normally does
    not have the stable one installed at all."""
    monkeypatch.setattr(sys, "argv", ["/opt/homebrew/Cellar/whiskerless-rc/0.2.0/bin/whiskerless"])
    assert "whiskerless-rc" in update_check._channel_hint()
    monkeypatch.setattr(sys, "argv", ["/opt/homebrew/Cellar/whiskerless/0.2.0/bin/whiskerless"])
    assert update_check._channel_hint().endswith("tap/whiskerless")


def test_a_windows_shaped_path_still_names_the_tool_that_owns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`str(Path(...))` uses backslashes on Windows, so every POSIX-shaped test below could never
    match and a normal pipx install was told to upgrade with the managed venv's own pip."""
    monkeypatch.setattr(
        update_check.Path, "resolve", lambda self: PurePosixPath(str(self).replace("\\", "/"))
    )
    monkeypatch.setattr(sys, "argv", [r"C:\Users\a\pipx\venvs\whiskerless\Scripts\whiskerless.exe"])
    assert update_check._channel_hint() == "pipx upgrade whiskerless"


def test_a_candidate_run_does_not_answer_for_a_stable_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both channels can share one WHISKERLESS_HOME. A cache entry that did not record its
    endpoint let an rc run advertise a prerelease to a stable install whose upgrade command
    cannot install one."""
    marker = tmp_path / ".update-check"
    marker.write_text(
        json.dumps({"day": date.today().isoformat(), "latest": "v9.9.9-rc.1", "channel": "rc"})
    )
    calls: list[str] = []
    monkeypatch.setattr(update_check, "_fetch_latest", lambda *a: calls.append("fetched") or None)
    update_check.check(tmp_path, env={})
    assert calls == ["fetched"], "the other channel's cached answer was reused"


def test_the_two_channels_keep_separate_daily_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both installs can share one home. A single marker was overwritten on every switch, so
    alternating them refetched on every command and paid the full timeout each time."""
    (tmp_path / ".update-check").write_text(
        json.dumps({"day": date.today().isoformat(), "latest": "v1.0.0", "channel": "stable"})
    )
    (tmp_path / ".update-check-rc").write_text(
        json.dumps({"day": date.today().isoformat(), "latest": "v2.0.0-rc.1", "channel": "rc"})
    )
    calls: list[str] = []
    monkeypatch.setattr(update_check, "_fetch_latest", lambda *a: calls.append("fetched") or None)
    update_check.check(tmp_path, env={})
    assert calls == [], "a cached answer for this channel was ignored"
    assert (tmp_path / ".update-check-rc").exists(), "the other channel's cache was overwritten"


def test_a_standalone_linux_binary_is_told_to_re_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """The standalone Linux build is installed by copying it to /usr/local/bin. Neither apt/dnf
    nor a .pkg can upgrade that, and both were being suggested."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/whiskerless"])
    assert "re-download the binary" in update_check._channel_hint()


def test_a_packaged_install_is_told_to_use_its_package_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The .deb and .rpm install the SAME frozen binary, to /usr/bin. Testing `sys.frozen` first
    told every apt and dnf user to re-download a raw binary instead of upgrading in place."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "argv", ["/usr/bin/whiskerless"])
    assert update_check._channel_hint() == "your package manager (apt/dnf)"


def test_the_macos_package_is_told_to_re_download_the_pkg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/whiskerless"])
    assert update_check._channel_hint() == "re-download the .pkg"
