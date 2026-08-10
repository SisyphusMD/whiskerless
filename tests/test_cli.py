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
from whiskerless.exceptions import WhiskerlessConnectionError
from whiskerless.safety import Hazard, assert_sendable, classify_code

BASE = ["--host", "192.0.2.10", "--serial", "LR4C000001"]


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
def _spare_loop() -> Any:
    """One loop for the whole module, reinstalled after each test.

    `main` runs asyncio.run, which closes the loop it created and leaves none
    current. Harmless for the library env, but these tests are also collected by
    a plain `pytest` in the Home Assistant env, and its fixtures expect a loop to
    exist — without one they fail in setup from the second test on. Shared rather
    than made per-test so this does not abandon an open loop on every test.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _no_broker(_spare_loop: Any) -> Any:
    FakeLink.published = []
    with patch("whiskerless.cli.LitterRobot4Link", FakeLink):
        yield
    asyncio.set_event_loop(_spare_loop)


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
