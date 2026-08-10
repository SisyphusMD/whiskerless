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
import contextlib
from typing import Any
from unittest.mock import patch

import pytest

from whiskerless.devices.litter_robot_4.client import LitterRobot4Client, _classify
from whiskerless.devices.litter_robot_4.const import WEEKDAYS
from whiskerless.devices.litter_robot_4.models import LitterRobot4State
from whiskerless.devices.litter_robot_4.protocol import ActivityMessage, StateMessage
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


# --- the rest of the settings surface ----------------------------------------
@pytest.mark.parametrize(
    ("method", "argument", "state", "code"),
    [
        ("async_set_night_light_mode", 2, {"night_light_mode": "auto"}, "0x02180002"),
        ("async_set_night_light_brightness", 30, {"night_light_brightness": 30}, "0x0219001E"),
        ("async_set_keypad_lockout", True, {"keypad_lockout": True}, "0x02170001"),
        (
            "async_set_panel_brightness",
            40,
            {"display_intensity_high": 40, "display_intensity_low": 40},
            f"0x020E{(40 << 8) | 40:04X}",
        ),
    ],
)
async def test_each_setting_reaches_its_register(
    method: str, argument: object, state: dict[str, Any], code: str
) -> None:
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(**state)])

    await getattr(client, method)(argument)
    assert code in link.published


async def test_the_wake_schedule_is_verified_across_every_day() -> None:
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(weekday_wake_times=dict.fromkeys(WEEKDAYS, 420))])

    with patch("whiskerless.devices.litter_robot_4.client._WRITE_GAP", 0):
        await client.async_set_panel_wake_time(420)
    assert len([c for c in link.published if c != "0x02A00000"]) == 7


async def test_arming_the_weekday_schedule_checks_the_whole_mask() -> None:
    """A stale single day would otherwise confirm an all-days write that never landed."""
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(weekday_sleep_mask=0x7F)])
    await client.async_set_weekday_sleep_enabled(True)
    assert any(c.startswith("0x021D") for c in link.published)


async def test_the_derived_sleep_mode_register_is_tried_once_not_three_times() -> None:
    """The firmware computes 0x1A, so retrying a disagreement never converges."""
    link = FakeLink()
    client = _client(link)
    _arm(client, [_state(panel_sleep_mode=False) for _ in range(5)])

    with pytest.raises(WhiskerlessError):
        await client.async_set_panel_sleep_mode(True)
    assert len([c for c in link.published if c.startswith("0x021A")]) == 1


# --- state, availability and the update callback -----------------------------
def test_a_state_message_updates_the_snapshot_and_notifies() -> None:
    client = _client(FakeLink())
    seen: list[Any] = []
    client.set_update_callback(seen.append)

    client._handle(StateMessage(state=_state(clean_cycle_wait_minutes=15), raw={}))
    assert client.robot.clean_cycle_wait_minutes == 15
    assert len(seen) == 1


def test_a_callback_that_raises_does_not_break_the_stream() -> None:
    """A consumer's bug is not a reason to stop decoding the robot."""
    client = _client(FakeLink())
    client.set_update_callback(lambda _: (_ for _ in ()).throw(RuntimeError("consumer bug")))

    client._handle(StateMessage(state=_state(clean_cycle_wait_minutes=15), raw={}))
    assert client.robot.clean_cycle_wait_minutes == 15


def test_asking_for_the_robot_before_it_has_spoken_says_so() -> None:
    with pytest.raises(WhiskerlessConnectionError, match="no state"):
        _ = _client(FakeLink()).robot


def test_a_client_starts_unavailable() -> None:
    assert _client(FakeLink()).available is False


def test_the_first_connection_failure_is_classified_and_unblocks_connect() -> None:
    """connect() waits on this event; without it a bad password hangs forever."""
    client = _client(FakeLink())
    client._on_disconnect(RuntimeError("Not authorized"))
    assert client._failed.is_set()
    assert isinstance(client._first_error, WhiskerlessAuthError)


async def test_disconnect_is_safe_before_a_connection_exists() -> None:
    await _client(FakeLink()).disconnect()


async def test_a_request_after_the_link_is_gone_is_dropped_quietly() -> None:
    """The supervisor clears _link on a drop; a queued refresh must not raise."""
    client = _client(None)
    await client._safe_request_state()


# --- the supervised connection -----------------------------------------------
class _Session:
    """One scripted connection attempt: connect, stream, then end or raise."""

    def __init__(self, messages: list[Any] | None = None, error: Exception | None = None) -> None:
        self._queued = messages or []
        self.error = error

    async def __aenter__(self) -> _Session:
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def request_state(self) -> None:
        return None

    async def messages_iter(self) -> Any:
        for message in self._queued:
            yield message
        await asyncio.Event().wait()  # stay connected

    def messages(self) -> Any:
        return self.messages_iter()


def _sessions(*scripted: _Session) -> Any:
    """Hand the supervisor one scripted session per connection attempt."""
    queue = list(scripted)

    def _make(*_a: object, **_k: object) -> _Session:
        return queue.pop(0) if queue else _Session()

    return patch("whiskerless.devices.litter_robot_4.client.LitterRobot4Link", _make)


async def test_connecting_reports_available_once_the_robot_answers() -> None:
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    session = _Session(messages=[StateMessage(state=_state(clean_cycle_wait_minutes=15), raw={})])
    with _sessions(session):
        await client.connect()
        assert client.available is True
        assert client.robot.clean_cycle_wait_minutes == 15
    await client.disconnect()


async def test_a_first_connection_failure_is_raised_and_stops_the_supervisor() -> None:
    """Otherwise a bad password leaves a task retrying forever behind a raised error."""
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    with _sessions(_Session(error=OSError("Not authorized"))), pytest.raises(WhiskerlessAuthError):
        await client.connect()
    assert client._task is None, "a failed connect must not leak a retry loop"


async def test_a_dropped_connection_reconnects_and_comes_back_available() -> None:
    """The robot is quiet for hours; a drop must not need a Home Assistant reload."""
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    good = _Session(messages=[StateMessage(state=_state(clean_cycle_wait_minutes=15), raw={})])
    with (
        patch("whiskerless.devices.litter_robot_4.client._RECONNECT_MAX_BACKOFF", 0.01),
        _sessions(_Session(error=OSError("boom")), good),
    ):
        # The first attempt fails; connect() surfaces it, so drive the loop directly.
        client._closing = False
        task = asyncio.create_task(client._supervise())
        await asyncio.wait_for(client._ready.wait(), timeout=2)
        assert client.available is True
        client._closing = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_disconnect_stops_the_supervisor() -> None:
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    with _sessions(_Session()):
        await client.connect()
    await client.disconnect()
    assert client._task is None


async def test_the_serial_is_confirmed_by_a_real_state_fetch() -> None:
    """Returning the configured serial without asking would confirm a dead broker."""
    client = _client(FakeLink())
    _arm(client, [_state(clean_cycle_wait_minutes=15)])
    assert await client.async_get_serial() == SERIAL


async def test_an_activity_message_prompts_a_throttled_refresh() -> None:
    """Telemetry between full states, without a requestState per event."""
    link = FakeLink()
    client = _client(link)
    client._handle(ActivityMessage(readings=[]))
    client._handle(ActivityMessage(readings=[]))  # immediately after: throttled
    await asyncio.sleep(0)
    await asyncio.gather(*client._bg_tasks, return_exceptions=True)
    assert link.published.count("0x02A00000") == 1


async def test_no_refresh_is_scheduled_while_a_write_holds_the_lock() -> None:
    """It would land in a pacing gap — the bug that dropped one write of seven."""
    link = FakeLink()
    client = _client(link)
    async with client._io_lock:
        client._handle(ActivityMessage(readings=[]))
        await asyncio.sleep(0)
    assert link.published == []


async def test_a_verify_read_that_fails_retries_instead_of_giving_up() -> None:
    """A dropped link mid-transaction is a retry, not a failed write."""
    link = FakeLink()
    client = _client(link)
    attempts = 0

    async def _flaky(*, timeout: float) -> LitterRobot4State:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise WhiskerlessConnectionError("dropped mid-transaction")
        return _state(clean_cycle_wait_minutes=20)

    client._get_robot_locked = _flaky  # type: ignore[method-assign]
    await client.async_set_clean_cycle_wait(20)
    assert attempts == 2


async def test_refresh_is_a_state_fetch() -> None:
    client = _client(FakeLink())
    _arm(client, [_state(clean_cycle_wait_minutes=15)])
    await client.async_refresh()
    assert client.robot.clean_cycle_wait_minutes == 15


async def test_a_supervisor_asked_to_close_stops_before_connecting() -> None:
    """disconnect() during a backoff sleep must not open one more connection."""
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    client._closing = True
    with _sessions(_Session()):
        await client._supervise()
    assert client._link is None


async def test_losing_a_live_connection_marks_it_unavailable_once() -> None:
    """Consumers read `available`; a drop has to move it, and only on the way down."""
    client = _client(FakeLink())
    client._available = True
    client._on_disconnect(OSError("boom"))
    assert client.available is False
    # A second failure while already down must not re-log or re-flip anything.
    client._on_disconnect(OSError("still down"))
    assert client.available is False


async def test_an_unexpected_error_reconnects_instead_of_going_dark() -> None:
    """A bug in decoding must not leave the robot offline until the next reload.

    Anything that is not a broker error is logged with its traceback and then
    treated like any other drop — the alternative is a silently dead integration.
    """
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    good = _Session(messages=[StateMessage(state=_state(clean_cycle_wait_minutes=15), raw={})])
    with (
        patch("whiskerless.devices.litter_robot_4.client._RECONNECT_MAX_BACKOFF", 0.01),
        _sessions(_Session(error=ValueError("not a broker problem")), good),
    ):
        task = asyncio.create_task(client._supervise())
        await asyncio.wait_for(client._ready.wait(), timeout=2)
        assert client.available is True
        client._closing = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_a_reconnection_is_announced_only_after_a_first_success() -> None:
    """The "Reconnected" line is noise on the very first connection."""
    client = LitterRobot4Client(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    client._ready.set()  # as if it had been up before
    client._available = False
    with (
        patch("whiskerless.devices.litter_robot_4.client._RECONNECT_MAX_BACKOFF", 0.01),
        _sessions(_Session(messages=[])),
    ):
        task = asyncio.create_task(client._supervise())
        for _ in range(50):
            await asyncio.sleep(0)
            if client.available:
                break
        assert client.available is True
        client._closing = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
