"""Fixtures for the Whiskerless integration tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.whiskerless.const import (
    CONF_CAT_VISIT_SEEN,
    CONF_DRAWER_SEEN,
    CONF_PET_WEIGHT_SEEN,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion
from syrupy.location import PyTestLocation

from whiskerless.devices.litter_robot_4.derive import Evidence

from .const import MOCK_CONFIG, MOCK_NAME, MOCK_SERIAL


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Serialize registry entries without their volatile fields.

    A raw DeviceEntry/RegistryEntry repr carries the config entry's ULID, the
    generated row id and created/modified timestamps, all of which differ every
    run — snapshotting those makes the assertion fail on its own second run.

    Each harness keeps its own set: Core changes how registry entries serialize
    (2026.11 renamed a device's config entry fields), so one set cannot match the
    oldest Core and the newest at once, and a change on the newest is something a
    person should read before accepting.
    """
    return snapshot.use_extension(_LegSnapshots)


try:
    import pytest_homeassistant  # noqa: F401
except ImportError:
    _ON_CURRENT_HARNESS = False
else:
    _ON_CURRENT_HARNESS = True


class _LegSnapshots(HomeAssistantSnapshotExtension):
    """Sibling folders, and neither inside the harness's default `snapshots/`: syrupy searches a
    snapshot folder recursively and fails a run on any snapshot it did not use, and the default
    extension searches `snapshots/` in every run, so a set under it would fail both legs."""

    @classmethod
    def dirname(cls, *, test_location: PyTestLocation) -> str:
        leg = "current_core" if _ON_CURRENT_HARNESS else "oldest_core"
        return str(Path(test_location.filepath).parent / f"snapshots_{leg}")


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading the custom integration in tests."""
    return


@pytest.fixture(autouse=True)
def _stop_the_mqtt_misc_loop(hass: HomeAssistant) -> Generator[None]:
    """Stop the MQTT client's one-second housekeeping timer when a test ends.

    The harness's mock client opens a socket and never closes it, so the timer that only a socket
    close cancels outlives the test, and newer harnesses fail every MQTT test on it. A test using
    nothing but the harness's own `mqtt_mock` does the same, so it is not this integration's timer;
    the cleanup check stays on for everything else.
    """
    yield
    client = getattr(hass.data.get("mqtt"), "client", None)
    timer = getattr(client, "_misc_timer", None)
    if timer is not None:
        timer.cancel()
        client._misc_timer = None  # type: ignore[union-attr]


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Patch async_setup_entry so config-flow tests don't start a real coordinator."""
    with patch(
        "custom_components.whiskerless.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture
def state_payload() -> str:
    """A recorded LR4 `/state` document."""
    return (Path(__file__).parent / "fixtures" / "lr4_state.json").read_text(encoding="utf-8")


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for one robot (serial + display name).

    Modelled as a mature install whose gated event sensors have all reported,
    each sighting carrying what proved it, so tests exercising those entities
    see them enabled. Detection tests build their own entries.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL,
        data=dict(MOCK_CONFIG),
        options={
            CONF_DRAWER_SEEN: str(Evidence.DRAWER_MOVED),
            CONF_PET_WEIGHT_SEEN: str(Evidence.CAT_WEIGHT),
            CONF_CAT_VISIT_SEEN: str(Evidence.OCCUPANCY),
        },
    )
