"""`whiskerless evo`: each action reaches the link with the right command, and the
guard and model checks hold. The link is faked; the serial is an invented example."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from whiskerless.cli import _parse_clock, main
from whiskerless.devices.litter_robot_evo.codec import decode_activity_code
from whiskerless.devices.litter_robot_evo.protocol import (
    ActivityMessage,
    EventMessage,
    PawprintMessage,
)
from whiskerless.exceptions import WhiskerlessError
from whiskerless.robot_profiles import Broker, RobotProfileStore
from whiskerless.safety import assert_evo_sendable

SERIAL = "LRE-01-40-01-2610-000000"
BASE = ["--serial", SERIAL]


class FakeEvoLink:
    """Records publishes; answers `apply` with a scripted echo."""

    published: ClassVar[list[tuple[str, ...]]] = []
    prefixes: ClassVar[list[str]] = []
    echo: ClassVar[int | None] = None
    script: ClassVar[list[Any]] = []
    readings: ClassVar[list[Any] | None] = None

    def __init__(self, _settings: object, serial: str, *, topic_prefix: str) -> None:
        assert serial == SERIAL
        FakeEvoLink.prefixes.append(topic_prefix)

    async def __aenter__(self) -> FakeEvoLink:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def publish_many(self, commands: Any, *, allow_dangerous: bool = False) -> None:
        for command in commands:
            assert_evo_sendable(command.code, allow_dangerous=allow_dangerous)
        FakeEvoLink.published.append(tuple(command.code for command in commands))

    async def publish_code(self, code: str, *, allow_dangerous: bool = False) -> None:
        assert_evo_sendable(code, allow_dangerous=allow_dangerous)
        FakeEvoLink.published.append((code,))

    async def read_all(self, *, timeout: float) -> list[Any] | None:
        FakeEvoLink.published.append(("read_all",))
        return FakeEvoLink.readings

    async def apply(self, command: Any, *, timeout: float) -> int | None:
        FakeEvoLink.published.append((command.code,))
        return command.value if FakeEvoLink.echo is None else FakeEvoLink.echo

    async def messages(self) -> AsyncGenerator[Any]:
        for message in FakeEvoLink.script:
            yield message
        await asyncio.sleep(3600)


@pytest.fixture(scope="module")
def _cli_loop() -> Any:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _fake_link(_cli_loop: Any) -> Any:
    RobotProfileStore.from_env().save_broker(Broker(host="192.0.2.10"))
    FakeEvoLink.published = []
    FakeEvoLink.prefixes = []
    FakeEvoLink.echo = None
    FakeEvoLink.script = []
    FakeEvoLink.readings = None
    with (
        patch("whiskerless.cli.asyncio.run", _cli_loop.run_until_complete),
        patch("whiskerless.cli.LitterRobotEvoLink", FakeEvoLink),
    ):
        yield


def test_brightness_is_applied_and_confirmed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "brightness", "8", "1", *BASE]) == 0
    assert FakeEvoLink.published == [("0x0202010801",)]
    assert FakeEvoLink.prefixes == ["prod/robots"]
    assert "applied" in capsys.readouterr().out


def test_a_substituted_echo_is_reported_as_a_failure(capsys: pytest.CaptureFixture[str]) -> None:
    FakeEvoLink.echo = 0x0832
    assert main(["evo", "brightness", "8", "1", *BASE]) == 1
    assert "instead of" in capsys.readouterr().out


def test_no_echo_is_a_failure(capsys: pytest.CaptureFixture[str]) -> None:
    async def silent(self: FakeEvoLink, command: Any, *, timeout: float) -> None:
        return None

    with patch.object(FakeEvoLink, "apply", silent):
        assert main(["evo", "cycle-delay", "7", *BASE]) == 1
    assert "no echo" in capsys.readouterr().err


def test_cycle_delay_and_lockout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "cycle-delay", "15", *BASE]) == 0
    assert main(["evo", "lockout", "on", "--topic-prefix", "prod/LR4", *BASE]) == 0
    assert FakeEvoLink.published == [("0x020209000F",), ("0x02020A0001",)]
    assert FakeEvoLink.prefixes[-1] == "prod/LR4"


def test_a_sleep_schedule_is_one_message_mask_last() -> None:
    assert main(["evo", "sleep", "--days", "sunday", "saturday", "--sleep", "00:00", "--wake", "12:00", *BASE]) == 0
    (sent,) = FakeEvoLink.published
    assert len(sent) == 15
    assert sent[-1] == "0x0202100041"


@pytest.mark.parametrize(
    ("action", "code"),
    [("clean-cycle", "0x020103000A"), ("change-filter", "0x020103000C"), ("reset-drawer", "0x0201220001")],
)
def test_actions(action: str, code: str) -> None:
    assert main(["evo", action, *BASE]) == 0
    assert FakeEvoLink.published == [(code,)]


def test_power_off_needs_the_override(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "power", "off", *BASE]) == 2
    assert "refused by safety guard" in capsys.readouterr().err
    assert main(["evo", "power", "off", "--allow-dangerous", *BASE]) == 0
    assert main(["evo", "power", "on", *BASE]) == 0
    assert FakeEvoLink.published == [("0x0201140000",), ("0x0201140001",)]


def test_send_is_guarded_and_prefixes_0x(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "send", "0202010808", *BASE]) == 0
    assert "safe" in capsys.readouterr().out
    assert main(["evo", "send", "0x0201010201", *BASE]) == 2
    assert main(["evo", "send", "0x0201010201", "--allow-dangerous", *BASE]) == 0
    assert FakeEvoLink.published == [("0x0202010808",), ("0x0201010201",)]


def test_state_reads_every_readable_register_and_prints_it(capsys: pytest.CaptureFixture[str]) -> None:
    FakeEvoLink.readings = [decode_activity_code("0x01030004"), decode_activity_code("0x02090007")]
    assert main(["evo", "state", *BASE]) == 0
    out = capsys.readouterr().out
    assert FakeEvoLink.published == [("read_all",)]
    assert "robot_status = ready" in out
    assert "cycle_delay_minutes = 7" in out


def test_state_fails_without_a_reply(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "state", *BASE]) == 1
    assert "no reply to the reads" in capsys.readouterr().err


def test_monitor_prints_messages_and_what_was_reported(capsys: pytest.CaptureFixture[str]) -> None:
    FakeEvoLink.script = [
        ActivityMessage(readings=[decode_activity_code("0x02010801"), decode_activity_code("0x02110000")]),
        ActivityMessage(readings=[decode_activity_code("0x02090000")], query=True),
        EventMessage(event_type="cycle", readings=[decode_activity_code("0x01030004")]),
        EventMessage(event_type="", readings=[]),
        PawprintMessage(message_type="pet_profile_request"),
        PawprintMessage(message_type=""),
    ]
    assert main(["evo", "monitor", "--duration", "0.05", *BASE]) == 0
    out = capsys.readouterr().out
    assert "panel_brightness=2049" in out
    assert "sleep_sunday" in out
    assert "query: " in out
    assert "event cycle" in out
    assert "pawprint: pet_profile_request" in out
    assert "led_brightness = 1" in out
    assert "robot_status = ready" in out


def test_an_lr4_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "clean-cycle", "--serial", "LR4C123456"]) == 1
    assert "not a Litter-Robot EVO" in capsys.readouterr().err
    assert FakeEvoLink.published == []


def test_a_bad_time_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "sleep", "--days", "monday", "--sleep", "25:00", *BASE]) == 1
    assert main(["evo", "sleep", "--days", "monday", "--wake", "noon", *BASE]) == 1
    assert FakeEvoLink.published == []


def test_parse_clock() -> None:
    assert _parse_clock("12:00") == 720
    with pytest.raises(WhiskerlessError):
        _parse_clock("12:60")


def test_an_empty_cycle_asks_first(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("builtins.input", return_value="no"):
        assert main(["evo", "empty-cycle", *BASE]) == 1
    assert "aborted" in capsys.readouterr().err
    with patch("builtins.input", return_value="yes"):
        assert main(["evo", "empty-cycle", *BASE]) == 0
    assert FakeEvoLink.published == [("0x020103000B",)]


def test_yes_skips_the_empty_cycle_prompt() -> None:
    with patch("builtins.input", side_effect=AssertionError("prompted")):
        assert main(["evo", "empty-cycle", "--yes", *BASE]) == 0
    assert FakeEvoLink.published == [("0x020103000B",)]


def test_set_clock_sends_the_given_time_as_one_message() -> None:
    assert main(["evo", "set-clock", "--at", "2026-01-30T08:01:28", *BASE]) == 0
    (sent,) = FakeEvoLink.published
    assert sent == (
        "0x0202020005", "0x0202030008", "0x0202040001", "0x020205001C",
        "0x020206001E", "0x0202070001", "0x020208001A",
    )


def test_set_clock_defaults_to_now() -> None:
    assert main(["evo", "set-clock", *BASE]) == 0
    (sent,) = FakeEvoLink.published
    assert len(sent) == 7


def test_set_clock_refuses_a_malformed_time(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evo", "set-clock", "--at", "noon", *BASE]) == 2
    assert "--at must be" in capsys.readouterr().err
    assert FakeEvoLink.published == []
