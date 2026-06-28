"""Diagnostics redaction."""

from __future__ import annotations

import pytest
from custom_components.whiskerless.const import CONF_SERIAL
from custom_components.whiskerless.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")

REDACTED = "**REDACTED**"


async def test_diagnostics(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["entry"][CONF_SERIAL] == REDACTED
    assert diagnostics["available"] is True
    # Decoded state is kept; the raw firmware doc is dropped.
    assert diagnostics["state"]["waste_drawer_level"] == 35
    assert "raw" not in diagnostics["state"]
