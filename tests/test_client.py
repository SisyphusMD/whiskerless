"""The library's push client — a third copy of the write-verify-retry pattern.

`link.apply_setting`, the Home Assistant coordinator's `_write_and_verify`, and
this module's `_write_batch` all solve the same firmware quirk over different
transports. This one is exported as public API and has no in-repo consumer, so
it is the copy most likely to drift out of agreement with the other two without
anyone noticing.

The supervised reconnect loop is deliberately not covered here: faking a broker
that drops and returns tests the fake more than the client. What is pinned is
the write contract and the error classification a caller actually branches on.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from whiskerless.devices.litter_robot_4.client import LitterRobot4Client, _classify
from whiskerless.devices.litter_robot_4.const import WEEKDAYS
from whiskerless.devices.litter_robot_4.models import LitterRobot4State
from whiskerless.exceptions import (
    WhiskerlessAuthError,
    WhiskerlessConnectionError,
    WhiskerlessError,
)
from whiskerless.mqtt import MqttSettings

SERIAL = "LR4C000001"


class FakeLink:
    """Records publishes; the client drives state through the client's own event."""

    def __init__(self) -> None:
        self.published: list[str] = []

    async def publish(self, command: Any, **_: object) -> None:
        self.published.append(command.code)

    async def request_state(self) -> None:
        self.published.append("0x02A00000")


def _client(link: FakeLink | None) -> LitterRobot4Client:
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    client._link = link  # type: ignore[assignment]
    return client


def _arm(client: LitterRobot4Client, states: list[LitterRobot4State]) -> None:
    """Answer each request_state with the next scripted state document."""
    original = client._get_robot_locked

    async def _next(*, timeout: float) -> LitterRobot4State:
        client._robot = states.pop(0) if states else client._robot
        assert client._robot is not None
        return client._robot

    assert original is not None
    client._get_robot_locked = _next  # type: ignore[method-assign]


def _state(**kw: Any) -> LitterRobot4State:
    return LitterRobot4State(**kw)


async def test_a_setting_that_commits_immediately_is_written_once() -> None:
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(clean_cycle_wait_minutes=20)])

    await client.async_set_clean_cycle_wait(20)
    assert link.published == ["0x02160014"]


async def test_a_setting_that_commits_late_is_retried() -> None:
    """The same latency the other two implementations retry through."""
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(clean_cycle_wait_minutes=15), _state(clean_cycle_wait_minutes=20)])

    await client.async_set_clean_cycle_wait(20)
    assert link.published == ["0x02160014", "0x02160014"]


async def test_a_setting_that_never_commits_raises_after_three_attempts() -> None:
    """Bounded at the same count as the coordinator and the CLI link."""
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(clean_cycle_wait_minutes=15) for _ in range(5)])

    with pytest.raises(WhiskerlessError, match="did not commit"):
        await client.async_set_clean_cycle_wait(20)
    assert link.published.count("0x02160014") == 3


async def test_a_batch_write_is_paced_and_verified_as_one_transaction() -> None:
    """A schedule is seven registers; one of seven was seen dropping unpaced."""
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(weekday_sleep_times=dict.fromkeys(WEEKDAYS, 1290))])

    with patch("whiskerless.devices.litter_robot_4.client._WRITE_GAP", 0):
        await client.async_set_panel_sleep_time(1290)

    writes = [c for c in link.published if c != "0x02A00000"]
    assert len(writes) == 7
    assert all(c.endswith(f"{1290:04X}") for c in writes)


async def test_writing_while_disconnected_says_so_rather_than_crashing() -> None:
    client = _client(None)
    with pytest.raises(WhiskerlessConnectionError, match="not connected"):
        await client.async_set_clean_cycle_wait(20)


async def test_reading_while_disconnected_says_so_rather_than_crashing() -> None:
    client = _client(None)
    with pytest.raises(WhiskerlessConnectionError, match="not connected"):
        await client.async_get_robot()


async def test_a_silent_robot_with_nothing_cached_is_a_connection_error() -> None:
    """Never having heard from it is different from holding a stale reading."""
    client = _client(FakeLink())
    with pytest.raises(WhiskerlessConnectionError, match="no state"):
        await client.async_get_robot(timeout=0.01)


async def test_a_silent_robot_with_a_cached_reading_returns_it() -> None:
    """A heartbeat that times out must not discard what the robot last said."""
    client = _client(FakeLink())
    client._robot = _state(clean_cycle_wait_minutes=15)
    assert (await client.async_get_robot(timeout=0.01)).clean_cycle_wait_minutes == 15


@pytest.mark.parametrize(
    "text", ["Not authorized", "unauthorized", "bad user name or password", "PASSWORD rejected"]
)
def test_a_credentials_failure_is_told_apart_from_an_unreachable_broker(text: str) -> None:
    """A caller retries a connection error forever and must not retry a bad password."""
    assert isinstance(_classify(RuntimeError(text)), WhiskerlessAuthError)


def test_anything_else_is_a_connection_error() -> None:
    assert isinstance(_classify(OSError("timed out")), WhiskerlessConnectionError)


def test_a_library_error_passes_through_unchanged() -> None:
    original = WhiskerlessError("already ours")
    assert _classify(original) is original


def test_the_client_id_is_distinct_from_the_robots_own() -> None:
    """The robot connects as its serial; colliding would disconnect one of them."""
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    assert client._settings.client_id == f"whiskerless-ha-{SERIAL}"
    assert client._settings.client_id != SERIAL


def test_an_explicit_client_id_is_respected() -> None:
    settings = MqttSettings(host="192.0.2.10", port=8883, client_id="mine")
    assert LitterRobot4Client(settings, SERIAL)._settings.client_id == "mine"


async def test_the_write_lock_serialises_a_read_against_a_transaction() -> None:
    """A read landing in a pacing gap is the bug the lock exists for."""
    client = _client(FakeLink())
    async with client._io_lock:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await client.async_get_robot()
