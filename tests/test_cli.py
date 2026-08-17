"""The command line, which ships on PyPI and had no tests at all.

Weighted towards the two things that actually cost someone something: the
confirmation prompts standing in front of the destructive actions, and `main`'s
promise to turn a library error into a message and an exit code rather than a
traceback. Value parsing is here too, because `set` writes whatever it parses
straight to a register.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from whiskerless.cli import _build_setting, _parse_bool, _parse_time, _pick_robot, main
from whiskerless.devices.litter_robot_4.models import LitterRobot4State
from whiskerless.devices.litter_robot_4.protocol import (
    ActivityMessage,
    ActivityReading,
    StateMessage,
)
from whiskerless.exceptions import WhiskerlessConnectionError
from whiskerless.safety import Hazard, assert_sendable, classify_code

BASE = ["--serial", "LR4C000001"]


@pytest.fixture(autouse=True)
def _a_broker_to_talk_to() -> None:
    """The store carries the broker now, so every command needs one on file."""
    from whiskerless.profiles import Broker, ProfileStore

    ProfileStore.from_env().save_broker(Broker(host="192.0.2.10"))


class FakeLink:
    """Stands in for a connected link; records what was published."""

    published: ClassVar[list[tuple[str, bool]]] = []

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self) -> FakeLink:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def publish(self, command: Any, *, allow_dangerous: bool = False) -> None:
        # The real link runs the guard here, and a fake that skipped it would let
        # every "the CLI refuses X" test below pass while refusing nothing.
        assert_sendable(command.code, allow_dangerous=allow_dangerous)
        FakeLink.published.append((command.code, allow_dangerous))


@pytest.fixture(scope="module")
def _cli_loop() -> Any:
    """One loop these tests own, so the interpreter's current one is never touched.

    `main` runs asyncio.run, which installs a loop, closes it, and leaves none
    current. That is fine for a real invocation and poison inside a test session:
    these tests are also collected by a plain `pytest` in the Home Assistant env,
    whose fixtures expect a working current loop, and every later module inherits
    whatever this one leaves behind. Running the coroutine here instead means the
    global loop is neither replaced nor closed, and nothing leaks.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _no_broker(_cli_loop: Any) -> Any:
    FakeLink.published = []
    with (
        patch("whiskerless.cli.asyncio.run", _cli_loop.run_until_complete),
        patch("whiskerless.cli.LitterRobot4Link", FakeLink),
    ):
        yield


def _run(*argv: str, answer: str | None = None) -> int:
    """Run the CLI, optionally scripting one answer to a confirmation prompt."""
    if answer is None:
        return main(list(argv))
    with patch("builtins.input", return_value=answer):
        return main(list(argv))


# --- the prompts in front of the destructive actions -------------------------
@pytest.mark.parametrize("command", ["clean-cycle", "empty-cycle"])
def test_an_action_declined_at_the_prompt_sends_nothing(command: str) -> None:
    assert _run(command, *BASE, answer="no") == 1
    assert FakeLink.published == []


@pytest.mark.parametrize(
    ("command", "code"),
    [("clean-cycle", "0x02010201"), ("empty-cycle", "0x02010801")],
)
def test_an_action_confirmed_at_the_prompt_is_sent(command: str, code: str) -> None:
    assert _run(command, *BASE, answer="yes") == 0
    assert FakeLink.published == [(code, False)]


@pytest.mark.parametrize("command", ["clean-cycle", "empty-cycle"])
def test_yes_skips_the_prompt_for_the_recoverable_actions(command: str) -> None:
    """Both are undoable from the same connection, so scripting them is allowed."""
    assert _run(command, *BASE, "--yes") == 0
    assert len(FakeLink.published) == 1


def test_power_does_not_even_accept_a_yes_flag() -> None:
    """The one prompt --yes must never satisfy, enforced by not existing.

    Power TOGGLES. A robot switched off has left the network and only a person
    at the machine can bring it back, so there is no undo over MQTT and no
    scripting it either. argparse rejecting the flag outright is a stronger
    guarantee than a handler that ignores it — this fails loudly if anyone adds
    --yes to the power subcommand for consistency with its neighbours.
    """
    with pytest.raises(SystemExit) as exit_code:
        _run("power", *BASE, "--yes")
    assert exit_code.value.code == 2
    assert FakeLink.published == []


def test_power_confirmed_at_the_prompt_opts_past_the_guard() -> None:
    """It is the one action classified DANGEROUS, so it must pass the flag on."""
    assert _run("power", *BASE, answer="yes") == 0
    assert FakeLink.published == [("0x02010101", True)]


def test_wifi_toggle_does_not_accept_a_yes_flag_either() -> None:
    """Same reason as power: a robot with its WiFi off has left the network, so
    there is no undo over MQTT and no scripting it."""
    with pytest.raises(SystemExit) as exit_code:
        _run("wifi-toggle", *BASE, "--yes")
    assert exit_code.value.code == 2
    assert FakeLink.published == []


def test_wifi_toggle_confirmed_at_the_prompt_opts_past_the_guard() -> None:
    assert _run("wifi-toggle", *BASE, answer="yes") == 0
    assert FakeLink.published == [("0x02011001", True)]


def test_wifi_toggle_declined_sends_nothing() -> None:
    assert _run("wifi-toggle", *BASE, answer="no") == 1
    assert FakeLink.published == []


def test_wifi_toggle_never_claims_the_press_was_confirmed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If the WiFi went off the robot was gone before it could acknowledge
    anything, so claiming otherwise states a fact the transport cannot carry."""
    assert _run("wifi-toggle", *BASE, answer="yes") == 0
    assert "left the network" in capsys.readouterr().out


def test_a_prompt_with_no_one_there_is_a_refusal() -> None:
    """Piped stdin raises EOFError; defaulting to yes would run on a cron job."""
    with patch("builtins.input", side_effect=EOFError):
        assert _run("empty-cycle", *BASE) == 1
    assert FakeLink.published == []


# --- send --------------------------------------------------------------------
def test_send_accepts_a_code_without_the_0x_prefix() -> None:
    assert _run("send", "02A00000", *BASE) == 0
    assert FakeLink.published == [("0x02A00000", False)]


def test_send_refuses_a_never_send_opcode_with_its_own_exit_code() -> None:
    """Exit 2, distinct from a plain failure: a script can tell them apart."""
    assert classify_code("0x02A30000") is Hazard.NEVER
    assert _run("send", "0x02A30000", *BASE, "--allow-dangerous") == 2
    assert FakeLink.published == []


def test_send_refuses_an_unknown_write_unless_told_to() -> None:
    assert _run("send", "0x02300001", *BASE) == 2
    assert _run("send", "0x02300001", *BASE, "--allow-dangerous") == 0


# --- main's error contract ---------------------------------------------------
def test_a_broker_that_cannot_be_reached_is_an_error_not_a_traceback() -> None:
    """It is the most common failure a new user hits, on their first command."""
    with patch.object(FakeLink, "__aenter__", side_effect=WhiskerlessConnectionError("nope")):
        assert _run("clean-cycle", *BASE, "--yes") == 1


def test_an_interrupt_uses_the_conventional_exit_code() -> None:
    with patch.object(FakeLink, "__aenter__", side_effect=KeyboardInterrupt):
        assert _run("clean-cycle", *BASE, "--yes") == 130


# --- value parsing, which lands on a register --------------------------------
@pytest.mark.parametrize(
    ("value", "minutes"),
    [("22:00", 1320), ("07:30", 450), ("0:00", 0), ("1320", 1320)],
)
def test_a_time_becomes_minutes_since_midnight(value: str, minutes: int) -> None:
    (command,) = _build_setting("panel-sleep-time", value)[:1]
    assert command.value == minutes


@pytest.mark.parametrize("value", ["1", "on", "true", "YES", " On "])
def test_the_truthy_spellings_are_all_accepted(value: str) -> None:
    assert _parse_bool(value) is True


@pytest.mark.parametrize("value", ["0", "off", "false", "no", ""])
def test_everything_else_is_false(value: str) -> None:
    assert _parse_bool(value) is False


def test_a_bare_minute_count_is_left_alone() -> None:
    assert _parse_time("90") == 90


def test_night_light_mode_takes_a_name_or_a_number() -> None:
    assert _build_setting("night-light-mode", "auto")[0].value == 2
    assert _build_setting("night-light-mode", "2")[0].value == 2


def test_panel_brightness_applies_one_value_to_both_levels() -> None:
    """The register packs both, and a single number means "the same either way"."""
    (both,) = _build_setting("panel-brightness", "40")
    (split,) = _build_setting("panel-brightness", "40:20")
    assert both.value == (40 << 8) | 40
    assert split.value == (40 << 8) | 20


def test_a_schedule_write_expands_to_every_weekday() -> None:
    """0x1B mirrors today only, so one time has to become seven register writes."""
    assert len(_build_setting("panel-sleep-time", "22:00")) == 7
    assert len(_build_setting("panel-wake-time", "07:00")) == 7


def test_an_unknown_setting_names_itself() -> None:
    with pytest.raises(SystemExit, match="nonsense"):
        _build_setting("nonsense", "1")


# --- provisioning helpers ----------------------------------------------------
def _advert(address: str) -> Any:
    return SimpleNamespace(address=address, rssi=-50, name="Litter-Robot 4")


def test_one_advertising_robot_needs_no_choice() -> None:
    only = _advert("AA:BB:CC:DD:EE:01")
    assert _pick_robot([only], None) is only


def test_an_explicit_address_skips_the_menu() -> None:
    first = _advert("AA:BB:CC:DD:EE:01")
    assert _pick_robot([first, _advert("AA:BB:CC:DD:EE:02")], "AA:BB:CC:DD:EE:FF") is first


def test_an_out_of_range_choice_is_asked_again() -> None:
    """Provisioning re-points a robot's broker, so picking the wrong one is real."""
    first, second = _advert("AA:BB:CC:DD:EE:01"), _advert("AA:BB:CC:DD:EE:02")
    with patch("builtins.input", side_effect=["9", "not a number", "1"]):
        assert _pick_robot([first, second], None) is second


# --- the read/report commands ------------------------------------------------
def _armed(*messages: Any, register: int | None = None, value: int | None = None) -> type:
    """A link whose stream yields `messages` and whose reads answer `value`."""

    class Armed(FakeLink):
        async def request_state(self) -> None:
            return None

        async def read_register(self, reg: int, **_: object) -> int | None:
            return value

        async def messages(self) -> Any:
            for message in messages:
                yield message

    return Armed


def _silent() -> type:
    """A robot that stays connected and simply never speaks."""

    class Silent(FakeLink):
        async def request_state(self) -> None:
            return None

        async def messages(self) -> Any:
            await asyncio.Event().wait()
            yield  # pragma: no cover - unreachable, keeps this a generator


    return Silent


def _state_message(**kw: Any) -> Any:
    return StateMessage(state=LitterRobot4State(**kw), raw={})


def test_state_prints_the_decoded_document(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("whiskerless.cli.LitterRobot4Link", _armed(_state_message(litter_level=62))):
        assert _run("state", *BASE) == 0
    out = capsys.readouterr().out
    assert "state:" in out
    assert "litter_level = 62" in out


def test_state_reports_a_robot_that_never_answers(capsys: pytest.CaptureFixture[str]) -> None:
    """The commonest real failure: the robot is event-driven and simply quiet."""
    with patch("whiskerless.cli.LitterRobot4Link", _silent()):
        assert _run("state", *BASE, "--timeout", "0.01") == 1
    assert "no state document" in capsys.readouterr().err


def test_read_prints_the_value_in_both_bases(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("whiskerless.cli.LitterRobot4Link", _armed(value=20)):
        assert _run("read", "0x16", *BASE) == 0
    assert "= 20 (0x0014)" in capsys.readouterr().out


def test_read_reports_a_register_that_does_not_echo(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("whiskerless.cli.LitterRobot4Link", _armed(value=None)):
        assert _run("read", "0x16", *BASE) == 1
    assert "no echo" in capsys.readouterr().err


def test_monitor_prints_activity_until_its_time_is_up(capsys: pytest.CaptureFixture[str]) -> None:
    activity = ActivityMessage(readings=(ActivityReading(register=0x16, value=20, source="0x160014"),))
    with patch("whiskerless.cli.LitterRobot4Link", _armed(activity)):
        assert _run("monitor", *BASE, "--duration", "0.05") == 0
    out = capsys.readouterr().out
    assert "0x160014" in out, "the raw code is the point of a capture session"


# --- set ---------------------------------------------------------------------
def test_set_reports_a_verified_write(capsys: pytest.CaptureFixture[str]) -> None:
    class Ok(FakeLink):
        async def apply_setting(self, *_: object, **__: object) -> bool:
            return True

    with patch("whiskerless.cli.LitterRobot4Link", Ok):
        assert _run("set", "clean-cycle-wait", "20", *BASE) == 0
    assert "(verified)" in capsys.readouterr().out


def test_set_reports_a_write_that_never_committed(capsys: pytest.CaptureFixture[str]) -> None:
    class Never(FakeLink):
        async def apply_setting(self, *_: object, **__: object) -> bool:
            return False

    with patch("whiskerless.cli.LitterRobot4Link", Never):
        assert _run("set", "clean-cycle-wait", "20", *BASE) == 1
    assert "not confirmed" in capsys.readouterr().err


def test_a_derived_register_says_where_the_real_setting_lives(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """0x1A is computed from the weekday schedule, so it accepts and discards.

    Without the hint the user retries the same doomed write, which is exactly
    what happened before the register was understood.
    """

    class Never(FakeLink):
        async def apply_setting(self, *_: object, **__: object) -> bool:
            return False

    with patch("whiskerless.cli.LitterRobot4Link", Never):
        assert _run("set", "panel-sleep-mode", "on", *BASE) == 1
    assert "weekday-sleep-enabled" in capsys.readouterr().err


# --- provision, the irreversible one -----------------------------------------
def _ble(robots: list[Any], *, result: Any = None, mac: str | None = "aa:bb") -> Any:
    """Patch the whole ble facade the provision handler imports."""
    outcome = result or SimpleNamespace(success=True, message="reprovisioned", steps=[])

    async def _scan(**_: object) -> list[Any]:
        return robots

    async def _read_mac(_address: str) -> str | None:
        return mac

    async def _provision(*_a: object, on_step: Any = None, **_k: object) -> Any:
        # The confirmation screen lives inside provision_robot now, because the
        # network is only known once the BLE link is open. A fake that skipped it
        # would make every prompt test pass without a prompt.
        confirm = _k.get("confirm")
        config = _a[1] if len(_a) > 1 else None
        if confirm is not None and config is not None and not confirm(config):
            return SimpleNamespace(
                success=False, message="aborted before anything was written", steps=[]
            )
        if on_step:
            on_step("connected")
        return outcome

    return patch.multiple(
        "whiskerless.ble",
        scan=_scan,
        read_device_mac=_read_mac,
        provision_robot=_provision,
    )


def _prov_args(tmp_path: Any) -> list[str]:
    """A provision onto a machine `setup` has already prepared.

    The broker and the certificate authority are established by `whiskerless
    setup`, a separate command — three files have to reach the broker and it has
    to restart before a robot can use them, and a robot in pairing mode cannot be
    kept waiting for that.
    """
    from whiskerless.profiles import ProfileStore

    store = ProfileStore.from_env()
    if not store.has_ca_cert():
        store.save_ca_cert_only("-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n")
    return [
        "provision", "--serial", "LR4C000001",
        "--wifi-ssid", "home", "--wifi-pass", "secret",
    ]


def test_provision_stops_when_nothing_is_advertising(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """The robot only advertises in pairing mode, so this is the usual first try."""
    with _ble([]):
        assert _run(*_prov_args(tmp_path), "--yes") == 1
    assert "Connect button" in capsys.readouterr().err


def test_provision_declined_at_the_prompt_changes_nothing(tmp_path: Any) -> None:
    robot = SimpleNamespace(address="AA:01", rssi=-40, name="LR4")
    with _ble([robot]):
        assert _run(*_prov_args(tmp_path), answer="no") == 1


def test_provision_confirmed_runs_and_reports(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    robot = SimpleNamespace(address="AA:01", rssi=-40, name="LR4")
    with _ble([robot]):
        assert _run(*_prov_args(tmp_path), "--yes") == 0
    out = capsys.readouterr().out
    assert "RE-PROVISION" in out, "the confirmation must state what is about to happen"
    assert "reprovisioned" in out


def test_a_dry_run_is_a_success_even_though_it_provisioned_nothing(tmp_path: Any) -> None:
    """Otherwise the rehearsal looks like a failure and people skip it."""
    robot = SimpleNamespace(address="AA:01", rssi=-40, name="LR4")
    failed = SimpleNamespace(success=False, message="dry-run: no bytes written", steps=[])
    with _ble([robot], result=failed):
        assert _run(*_prov_args(tmp_path), "--yes", "--dry-run") == 0


def test_a_real_run_that_fails_is_reported_as_a_failure(tmp_path: Any) -> None:
    robot = SimpleNamespace(address="AA:01", rssi=-40, name="LR4")
    failed = SimpleNamespace(success=False, message="nope", steps=[])
    with _ble([robot], result=failed):
        assert _run(*_prov_args(tmp_path), "--yes") == 1


def test_a_serial_from_another_model_never_reaches_the_radio(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Validated before the slow scan, and reported rather than raised."""
    args = _prov_args(tmp_path)
    args[args.index("LR4C000001")] = "LR3C000001"
    with _ble([]):
        assert _run(*args, "--yes") == 1
    assert "LR4" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("setting", "value", "register"),
    [
        ("keypad-lockout", "on", 0x17),
        ("panel-sleep-mode", "on", 0x1A),
        ("weekday-sleep-enabled", "on", 0x1D),
        ("clean-cycle-wait", "20", 0x16),
        ("night-light-brightness", "30", 0x19),
    ],
)
def test_every_setting_name_builds_a_write_for_its_register(
    setting: str, value: str, register: int
) -> None:
    """The choices list and this map are separate; a name in one and not the other
    reaches _build_setting and exits with a bare SystemExit."""
    (command,) = _build_setting(setting, value)
    assert command.register == register


def test_monitor_stops_cleanly_when_its_window_closes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The timeout is the exit path, not an error — a capture session just ends."""
    with patch("whiskerless.cli.LitterRobot4Link", _silent()):
        assert _run("monitor", *BASE, "--duration", "0.01") == 0
    assert "monitoring" in capsys.readouterr().out


def test_power_declined_at_the_prompt_sends_nothing() -> None:
    """The only way to say no to the one action with no undo."""
    assert _run("power", *BASE, answer="no") == 1
    assert FakeLink.published == []


def test_state_gives_up_when_the_stream_ends_without_a_document(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A broker that closes the subscription is not a state document."""
    with patch("whiskerless.cli.LitterRobot4Link", _armed()):
        assert _run("state", *BASE, "--timeout", "5") == 1
    capsys.readouterr()
