"""Fixtures for the Whiskerless integration tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.whiskerless.const import DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import MOCK_CONFIG, MOCK_NAME, MOCK_SERIAL


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
    """A config entry for one robot (serial + display name)."""
    return MockConfigEntry(
        domain=DOMAIN, title=MOCK_NAME, unique_id=MOCK_SERIAL, data=dict(MOCK_CONFIG)
    )
