"""Typed Litter-Robot 4 state, decoded from the ``…/state`` named document.

The robot publishes a named JSON document whose field names match what
pylitterbot reads from the cloud. The *values*, however, are the raw int16s the
firmware holds (the int→string contract lives in the cloud Lambda). The exact
local value encoding was not fully captured during reverse-engineering, so every
decoder here tolerates both forms — a raw int or a cloud-style string — and
degrades to ``None`` rather than raising on a partial or surprising payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import const


@dataclass(frozen=True, slots=True)
class LitterRobot4State:
    """A normalized snapshot of robot state. Unknown fields stay in ``raw``."""

    # Status / cycle
    robot_status: str | None = None
    robot_status_raw: Any = None
    robot_cycle_status: str | None = None
    robot_cycle_state: str | None = None
    is_cleaning: bool = False

    # Levels
    waste_drawer_level: int | None = None     # % full (DFILevelPercent)
    litter_level: int | None = None           # % (litterLevelPercentage or derived)
    litter_level_mm: int | None = None        # raw mm (litterLevel)
    # lb. Passed through as-is: the cloud `catWeight` field is already in pounds,
    # but the raw activity register (0x09) is int16/100. If a live `/state` proves
    # the local value is the raw register, divide by 100 here.
    cat_weight: float | None = None

    # Light / panel settings
    night_light_mode: str | None = None
    night_light_brightness: int | None = None  # %
    clean_cycle_wait_minutes: int | None = None
    keypad_lockout: bool | None = None
    panel_sleep_mode: bool | None = None
    panel_sleep_time: int | None = None        # minutes since midnight
    panel_wake_time: int | None = None
    weekday_sleep_enabled: bool | None = None

    # Power / hardware
    unit_power_status: Any = None
    unit_power_type: Any = None
    is_usb_power_on: bool | None = None
    usb_fault_status: int | None = None
    is_bonnet_removed: bool | None = None
    is_night_light_led_on: bool | None = None
    globe_motor_fault: int | None = None
    globe_motor_retract_fault: int | None = None

    # Drawer
    is_dfi_full: bool | None = None
    is_dfi_partial_full: bool | None = None
    dfi_number_of_cycles: int | None = None
    dfi_full_counter: int | None = None
    dfi_trigger_count: int | None = None

    # Odometers
    odometer_power_cycles: int | None = None
    odometer_clean_cycles: int | None = None
    odometer_empty_cycles: int | None = None
    odometer_filter_cycles: int | None = None

    # Sensors / occupancy
    cat_detected: bool | None = None
    sleep_status: Any = None

    # Connectivity / identity (diagnostic)
    wifi_rssi: int | None = None
    esp_firmware: str | None = None
    pic_firmware: str | None = None
    laser_board_firmware: str | None = None
    is_hopper_removed: bool | None = None
    hopper_status: Any = None

    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_state_doc(cls, raw: dict[str, Any]) -> LitterRobot4State:
        """Decode a raw ``…/state`` document into a normalized snapshot."""
        g = raw.get
        robot_status = _enum(g("robotStatus"), const.ROBOT_STATUS, const.ROBOT_STATUS_STRINGS)

        litter_pct = _int(g("litterLevelPercentage"))
        litter_mm = _int(g("litterLevel"))
        if litter_pct is None and litter_mm is not None:
            litter_pct = litter_level_percent_from_mm(litter_mm)

        return cls(
            robot_status=robot_status,
            robot_status_raw=g("robotStatus"),
            robot_cycle_status=_enum(g("robotCycleStatus"), const.ROBOT_CYCLE_STATUS),
            robot_cycle_state=_enum(g("robotCycleState"), const.ROBOT_CYCLE_STATE),
            is_cleaning=robot_status in const.CLEANING_STATUSES,
            waste_drawer_level=_int(g("DFILevelPercent")),
            litter_level=litter_pct,
            litter_level_mm=litter_mm,
            cat_weight=_float(g("catWeight")),
            night_light_mode=_enum(g("nightLightMode"), const.NIGHT_LIGHT_MODE),
            night_light_brightness=_int(g("nightLightBrightness")),
            clean_cycle_wait_minutes=_int(g("cleanCycleWaitTime")),
            keypad_lockout=_bool(g("isKeypadLockout")),
            panel_sleep_mode=_bool(g("isPanelSleepMode")),
            panel_sleep_time=_int(g("panelSleepTime")),
            panel_wake_time=_int(g("panelWakeTime")),
            weekday_sleep_enabled=_bool(g("weekdaySleepModeEnabled")),
            unit_power_status=g("unitPowerStatus"),
            unit_power_type=g("unitPowerType"),
            is_usb_power_on=_bool(g("isUSBPowerOn")),
            usb_fault_status=_int(g("USBFaultStatus")),
            is_bonnet_removed=_bool(g("isBonnetRemoved")),
            is_night_light_led_on=_bool(g("isNightLightLEDOn")),
            globe_motor_fault=_int(g("globeMotorFaultStatus")),
            globe_motor_retract_fault=_int(g("globeMotorRetractFaultStatus")),
            is_dfi_full=_bool(g("isDFIFull")),
            is_dfi_partial_full=_bool(g("isDFIPartialFull")),
            dfi_number_of_cycles=_int(g("DFINumberOfCycles")),
            dfi_full_counter=_int(g("DFIFullCounter")),
            dfi_trigger_count=_int(g("DFITriggerCount")),
            odometer_power_cycles=_int(g("odometerPowerCycles")),
            odometer_clean_cycles=_int(g("odometerCleanCycles")),
            odometer_empty_cycles=_int(g("odometerEmptyCycles")),
            odometer_filter_cycles=_int(g("odometerFilterCycles")),
            cat_detected=_bool(g("catDetect")),
            sleep_status=g("sleepStatus"),
            wifi_rssi=_int(g("wifiRssi")),
            esp_firmware=_str(g("espFirmware")),
            pic_firmware=_str(g("picFirmwareVersion")),
            laser_board_firmware=_str(g("laserBoardVersion")),
            is_hopper_removed=_bool(g("isHopperRemoved")),
            hopper_status=g("hopperStatus"),
            raw=raw,
        )


def litter_level_percent_from_mm(mm: int) -> int:
    """Approximate the cloud litter-level % from the raw mm distance.

    Mirrors the cloud-side derivation (MED confidence): full ≈ 440 mm, ~0.6 mm
    per percent, rounded to the nearest 10 and clamped at 0.
    """
    return max(round((100 - (mm - 440) / 0.6) / 10) * 10, 0)


# --- defensive scalar decoders -----------------------------------------------
def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no", "wake", "none"):
        return False
    return None


def _enum(
    value: Any,
    int_map: dict[int, str],
    string_map: dict[str, str] | None = None,
) -> str | None:
    """Decode an enum field that may be a raw int or a cloud string."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return int_map.get(n, f"unknown_{n}")
    text = str(value).strip().lower()
    if string_map and text in string_map:
        return string_map[text]
    # A stringified int ("13") still resolves through the int map.
    try:
        n = int(text)
    except ValueError:
        return text or None
    return int_map.get(n, f"unknown_{n}")
