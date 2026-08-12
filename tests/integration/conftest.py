"""Fixtures for the Whiskerless integration tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.whiskerless.const import (
    CONF_CAT_VISIT_SEEN,
    CONF_DETECTION_RESET_BY,
    CONF_DRAWER_SEEN,
    CONF_PET_WEIGHT_SEEN,
    DETECTION_RESET_REVISION,
    DOMAIN,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from .const import MOCK_CONFIG, MOCK_NAME, MOCK_SERIAL


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Serialize registry entries without their volatile fields.

    A raw DeviceEntry/RegistryEntry repr carries the config entry's ULID, the
    generated row id and created/modified timestamps, all of which differ every
    run — snapshotting those makes the assertion fail on its own second run.
    """
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading the custom integration in tests."""
    return


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

    Modelled as a mature install: the upgrade sweep already ran and the gated
    event sensors have all reported, so tests exercising those entities see
    them enabled. Detection and sweep tests build bare entries of their own.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL,
        data=dict(MOCK_CONFIG),
        options={
            CONF_DETECTION_RESET_BY: DETECTION_RESET_REVISION,
            CONF_DRAWER_SEEN: True,
            CONF_PET_WEIGHT_SEEN: True,
            CONF_CAT_VISIT_SEEN: True,
        },
    )
