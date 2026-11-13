"""The notification blueprint, loaded by Home Assistant and fed whiskerless_alert events.

A blueprint is only ever checked when someone imports it, so a typo in a template
would otherwise reach a user's phone as silence.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from custom_components.whiskerless.const import DOMAIN, EVENT_ALERT
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

BLUEPRINT = (
    Path(__file__).parents[2] / "blueprints" / "automation" / "whiskerless" / "litter_robot_notifications.yaml"
)


@pytest.fixture
def devices(hass: HomeAssistant) -> dict[str, str]:
    registry = dr.async_get(hass)
    out = {}
    for name, domain in (("phone", "mobile_app"), ("upstairs", DOMAIN), ("downstairs", DOMAIN)):
        entry = MockConfigEntry(domain=domain)
        entry.add_to_hass(hass)
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(domain, name)},
            name="Pixel 9" if name == "phone" else name.title(),
        )
        out[name] = device.id
    return out


async def _automation(hass: HomeAssistant, tmp_path: Path, **inputs: Any) -> list[ServiceCall]:
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints" / "automation" / "whiskerless"
    target.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target / BLUEPRINT.name)
    calls = async_mock_service(hass, "notify", "mobile_app_pixel_9")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"whiskerless/{BLUEPRINT.name}",
                    "input": inputs,
                }
            }
        },
    )
    await hass.async_block_till_done()
    return calls


async def _alert(
    hass: HomeAssistant,
    device_id: str,
    alert: str,
    event: str,
    urgent: bool = False,
    silenced: list[str] | None = None,
) -> None:
    hass.bus.async_fire(
        EVENT_ALERT,
        {
            "device_id": device_id,
            "serial": "LR4X",
            "robot": "Upstairs",
            "alert": alert,
            "event": event,
            "urgent": urgent,
            "message": f"{alert} {event}",
            "details": {},
            "silenced": silenced or [],
        },
    )
    await hass.async_block_till_done()


async def test_an_urgent_fault_is_time_sensitive_and_opens_the_robot(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str]
) -> None:
    family = async_mock_service(hass, "notify", "family")
    calls = await _automation(
        hass, tmp_path, phones=[devices["phone"]], image="/local/whiskerless.png", notify_action="notify.family"
    )
    await _alert(hass, devices["upstairs"], "globe_fault", "raised", urgent=True)
    assert len(calls) == 1
    assert family[0].data == {"title": "Upstairs", "message": "globe_fault raised"}
    data = calls[0].data
    assert data["title"] == "Upstairs"
    assert data["message"] == "globe_fault raised"
    push = data["data"]
    assert push["tag"] == "whiskerless_LR4X_globe_fault"
    assert push["subtitle"] == "whiskerless"
    assert push["color"] == "#0E7C7B"
    assert push["push"] == {"interruption-level": "time-sensitive"}
    assert push["url"] == push["clickAction"] == f"/config/devices/device/{devices['upstairs']}"
    assert push["image"] == "/local/whiskerless.png"
    silence = f"WHISKERLESS_SILENCE|LR4X|globe_fault|{devices['phone']}"
    assert push["actions"] == [
        {"action": silence, "title": "Silence"},
        {"action": "URI", "title": "Open", "uri": push["url"]},
    ]


async def test_without_a_picture_only_silence_is_offered_and_only_where_reminders_follow(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str]
) -> None:
    calls = await _automation(hass, tmp_path, phones=[devices["phone"]], visit=True)
    await _alert(hass, devices["upstairs"], "drawer_full", "raised")
    assert "image" not in calls[-1].data["data"]
    assert [a["title"] for a in calls[-1].data["data"]["actions"]] == ["Silence"]
    await _alert(hass, devices["upstairs"], "visit", "moment")
    assert "actions" not in calls[-1].data["data"]


async def test_a_reminder_skips_phones_that_silenced_it_and_never_breaks_focus(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str]
) -> None:
    calls = await _automation(hass, tmp_path, phones=[devices["phone"]])
    await _alert(hass, devices["upstairs"], "globe_fault", "reminder", urgent=True, silenced=[devices["phone"]])
    assert calls == []
    await _alert(hass, devices["upstairs"], "globe_fault", "reminder", urgent=True)
    push = calls[-1].data["data"]
    assert "push" not in push
    assert push["tag"] == "whiskerless_LR4X_globe_fault"
    assert [a["title"] for a in push["actions"]] == ["Silence"]


async def test_reminders_can_be_turned_off(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str]
) -> None:
    calls = await _automation(hass, tmp_path, phones=[devices["phone"]], reminders=False)
    await _alert(hass, devices["upstairs"], "drawer_full", "reminder")
    assert calls == []


async def test_a_cleared_alert_is_removed_and_offline_says_back_online(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str]
) -> None:
    calls = await _automation(hass, tmp_path, phones=[devices["phone"]])
    await _alert(hass, devices["upstairs"], "drawer_full", "cleared")
    assert calls[-1].data == {"message": "clear_notification", "data": {"tag": "whiskerless_LR4X_drawer_full"}}
    await _alert(hass, devices["upstairs"], "offline", "cleared", urgent=True)
    assert calls[-1].data["message"] == "offline cleared"
    assert "push" not in calls[-1].data["data"]


async def test_a_failed_start_breaks_focus_offers_no_silence_and_announces_recovery(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str]
) -> None:
    calls = await _automation(hass, tmp_path, phones=[devices["phone"]])
    await _alert(hass, devices["upstairs"], "setup_failed", "raised", urgent=True)
    push = calls[-1].data["data"]
    assert push["push"] == {"interruption-level": "time-sensitive"}
    assert "actions" not in push
    await _alert(hass, devices["upstairs"], "setup_failed", "cleared", urgent=True)
    assert calls[-1].data["message"] == "setup_failed cleared"


async def test_unticked_alerts_and_other_robots_are_ignored(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str]
) -> None:
    calls = await _automation(
        hass, tmp_path, phones=[devices["phone"]], robots=[devices["upstairs"]], clear_resolved=False
    )
    await _alert(hass, devices["upstairs"], "visit", "moment")
    await _alert(hass, devices["downstairs"], "drawer_full", "raised")
    await _alert(hass, devices["upstairs"], "drawer_full", "cleared")
    assert calls == []
    await _alert(hass, devices["upstairs"], "drawer_full", "raised")
    assert len(calls) == 1


async def test_quiet_hours_silence_all_but_urgent_alerts_and_drop_reminders(
    hass: HomeAssistant, tmp_path: Path, devices: dict[str, str], freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-11-01 23:30:00+00:00")
    calls = await _automation(hass, tmp_path, phones=[devices["phone"]], quiet_hours=True)
    await _alert(hass, devices["upstairs"], "drawer_full", "raised")
    assert calls[-1].data["data"]["push"] == {"interruption-level": "passive"}
    assert calls[-1].data["data"]["channel"] == "whiskerless_quiet"
    await _alert(hass, devices["upstairs"], "offline", "raised", urgent=True)
    assert calls[-1].data["data"]["push"] == {"interruption-level": "time-sensitive"}
    sent = len(calls)
    await _alert(hass, devices["upstairs"], "offline", "reminder", urgent=True)
    assert len(calls) == sent
    freezer.move_to("2026-11-01 12:00:00+00:00")
    await _alert(hass, devices["upstairs"], "drawer_full", "raised")
    assert "push" not in calls[-1].data["data"]
