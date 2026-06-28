"""Switch platform for Whiskerless."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_4 import LitterRobot4State

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity, exception_handler

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class WhiskerlessSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Whiskerless switch."""

    value_fn: Callable[[LitterRobot4State], bool | None]
    set_fn: Callable[[WhiskerlessCoordinator, bool], Awaitable[None]]


SWITCHES: tuple[WhiskerlessSwitchEntityDescription, ...] = (
    WhiskerlessSwitchEntityDescription(
        key="keypad_lockout",
        translation_key="keypad_lockout",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.keypad_lockout,
        set_fn=lambda coordinator, on: coordinator.async_set_keypad_lockout(on),
    ),
    WhiskerlessSwitchEntityDescription(
        key="panel_sleep_mode",
        translation_key="panel_sleep_mode",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.panel_sleep_mode,
        set_fn=lambda coordinator, on: coordinator.async_set_panel_sleep_mode(on),
    ),
    WhiskerlessSwitchEntityDescription(
        key="weekday_sleep",
        translation_key="weekday_sleep",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.weekday_sleep_enabled,
        set_fn=lambda coordinator, on: coordinator.async_set_weekday_sleep_enabled(on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless switches."""
    coordinator = entry.runtime_data
    async_add_entities(WhiskerlessSwitch(coordinator, description) for description in SWITCHES)


class WhiskerlessSwitch(WhiskerlessEntity, SwitchEntity):
    """A Whiskerless switch."""

    entity_description: WhiskerlessSwitchEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessSwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    @override
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._robot)

    @exception_handler
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, True)

    @exception_handler
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, False)
