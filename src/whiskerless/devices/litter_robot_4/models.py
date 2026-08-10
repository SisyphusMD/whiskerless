"""Typed Litter-Robot 4 state, decoded from the ``…/state`` named document.

The robot publishes a named JSON document whose field names match what
pylitterbot reads from the cloud. The *values*, however, are the raw int16s the
firmware holds (the int→string contract lives in the cloud Lambda). The exact
local value encoding was not fully captured during reverse-engineering, so every
decoder here tolerates both forms — a raw int or a cloud-style string — and
degrades to ``None`` rather than raising on a partial or surprising payload.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    # True when the firmware reported a usable percentage itself, rather than
    # this decoder deriving one from the distance. Consumers with a per-robot
    # calibration should prefer their own derivation over a derived value, but
    # never over the device's own answer.
    litter_level_reported: bool = False
    # lb. Passed through as-is: the cloud `catWeight` field is already in pounds.
    # No captured robot has ever put catWeight in its state document, so this is
    # untested — and the pet-weight sensor deliberately does not fall back to it.
    # The activity register (0x09) is raw and needs CAT_WEIGHT_DIVISOR.
    cat_weight: float | None = None

    # Light / panel settings
    night_light_mode: str | None = None
    night_light_brightness: int | None = None  # %
    clean_cycle_wait_minutes: int | None = None
    keypad_lockout: bool | None = None
    panel_sleep_mode: bool | None = None
    # `0x1B` / `0x1C`. Read-only: the firmware derives them from whichever
    # per-weekday pair below is in force today, so a schedule change has to be
    # written — and verified — against every day.
    panel_sleep_time: int | None = None        # minutes since midnight
    panel_wake_time: int | None = None
    weekday_sleep_enabled: bool | None = None
    weekday_sleep_times: dict[str, int] = field(default_factory=dict)
    weekday_wake_times: dict[str, int] = field(default_factory=dict)

    # Power / hardware
    unit_power_status: Any = None
    unit_power_type: Any = None
    is_usb_power_on: bool | None = None
    usb_fault_status: int | None = None
    is_bonnet_removed: bool | None = None
    is_night_light_led_on: bool | None = None
    display_intensity_high: int | None = None  # panel % in BRIGHT ambient (proven)
    display_intensity_low: int | None = None   # panel % in DARK ambient (proven)
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
        esp_firmware = _str(g("espFirmware"))
        robot_status = _enum(g("robotStatus"), const.ROBOT_STATUS, const.ROBOT_STATUS_STRINGS)
        robot_cycle_status = _enum(g("robotCycleStatus"), const.ROBOT_CYCLE_STATUS)
        # The cycle machine is a fallback for an UNMAPPED robotStatus only. A
        # known-idle status must win over a stale or lagging robotCycleStatus,
        # or a resting robot reports cleaning and loses both litter readings.
        if robot_status is None or robot_status not in const.KNOWN_STATUSES:
            is_cleaning = robot_cycle_status in const.ACTIVE_CYCLE_STATUSES
        else:
            is_cleaning = robot_status in const.CLEANING_STATUSES

        litter_pct = _int(g("litterLevelPercentage"))
        litter_level_reported = litter_pct is not None
        litter_mm = _int(g("litterLevel"))
        if is_cleaning or robot_status in const.LITTER_UNRELIABLE_STATUSES:
            # The ToF sensors read the rotating globe, not the litter bed, while
            # a cycle runs (observed: 574 mm mid-cycle on a 460 mm fill). Suppress
            # rather than publish garbage.
            litter_pct = litter_mm = None
        elif litter_pct is None and litter_mm is not None:
            litter_pct = litter_level_percent_from_mm(litter_mm)

        pic_firmware = _str(g("picFirmwareVersion"))
        if pic_firmware is None:
            # The local state doc carries the PIC identity as four mb* fields;
            # the cloud presents them joined (e.g. "10535.2560.4.4").
            parts = [_int(g(k)) for k in ("mbHardware", "mbBom", "mbSuite", "mbRevision")]
            if all(p is not None for p in parts) and any(parts):
                pic_firmware = ".".join(str(p) for p in parts)

        return cls(
            robot_status=robot_status,
            robot_status_raw=g("robotStatus"),
            robot_cycle_status=robot_cycle_status,
            robot_cycle_state=_enum(g("robotCycleState"), const.ROBOT_CYCLE_STATE),
            is_cleaning=is_cleaning,
            waste_drawer_level=_int(g("DFILevelPercent")),
            litter_level=litter_pct,
            litter_level_mm=litter_mm,
            litter_level_reported=litter_level_reported,
            cat_weight=_float(g("catWeight")),
            night_light_mode=_enum(g("nightLightMode"), const.NIGHT_LIGHT_MODE),
            night_light_brightness=_int(g("nightLightBrightness")),
            clean_cycle_wait_minutes=_int(g("cleanCycleWaitTime")),
            keypad_lockout=_bool(g("isKeypadLockout")),
            panel_sleep_mode=_bool(g("isPanelSleepMode")),
            panel_sleep_time=_int(g("panelSleepTime")),
            panel_wake_time=_int(g("panelWakeTime")),
            weekday_sleep_enabled=_bool(g("weekdaySleepModeEnabled")),
            weekday_sleep_times=_weekday_times(raw, "sleepTime"),
            weekday_wake_times=_weekday_times(raw, "wakeTime"),
            unit_power_status=g("unitPowerStatus"),
            unit_power_type=g("unitPowerType"),
            is_usb_power_on=_bool(g("isUSBPowerOn")),
            usb_fault_status=_int(g("USBFaultStatus")),
            is_bonnet_removed=_bool(g("isBonnetRemoved")),
            is_night_light_led_on=_bool(g("isNightLightLEDOn")),
            display_intensity_high=_int(g("DisplayIntensityHigh")),
            display_intensity_low=_int(g("DisplayIntensityLow")),
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
            esp_firmware=esp_firmware,
            pic_firmware=pic_firmware,
            laser_board_firmware=_str(g("laserBoardVersion")),
            is_hopper_removed=_bool(g("isHopperRemoved")),
            hopper_status=g("hopperStatus"),
            raw=raw,
        )


def litter_level_percent_from_mm(
    mm: int, *, full_mm: int | None = None, empty_mm: int | None = None
) -> int:
    """Convert the raw ToF distance to a litter percentage.

    ``litterLevel`` is a distance, so it RISES as litter drops.

    There is no universal curve. The cloud computes its percentage against a
    per-robot calibrated reference (``optimalLitterLevel``) that is not present
    in the local state document, and measured references differ by ~10 mm across
    robots — enough to move the answer by 15 points. So:

    * ``full_mm`` given — the reading when filled to the line. Mapped to 90%,
      matching how the cloud pins "at optimal", which leaves headroom for an
      overfill to read above it.
    * ``empty_mm`` also given — a true two-point scale, no assumed slope.
    * neither — the inherited approximation, which is the best guess available
      and is why calibrating is worth the one button press.
    """
    if full_mm is not None:
        if empty_mm is not None and empty_mm > full_mm:
            span = empty_mm - full_mm
            return max(min(round((empty_mm - mm) / span * 100), 100), 0)
        # 90% at the line, on the cloud's slope of ~0.6 mm per percent.
        return max(min(round(90 - (mm - full_mm) / 0.6), 100), 0)
    return min(max(round((100 - (mm - 440) / 0.6) / 10) * 10, 0), 100)


# --- defensive scalar decoders -----------------------------------------------
def every_weekday_is(times: Mapping[str, int], minutes: int) -> bool:
    """True only when all seven days report ``minutes``.

    Verifying a schedule write against `0x1B` / `0x1C` is not enough — they mirror
    today alone, so they confirm nothing about the other six registers. A day the
    robot never reported cannot be confirmed either, so an incomplete document is
    a failed verification rather than a pass.
    """
    return len(times) == len(const.WEEKDAYS) and all(
        times.get(day) == minutes for day in const.WEEKDAYS
    )


def _weekday_times(raw: dict[str, Any], prefix: str) -> dict[str, int]:
    """`sleepTimeMonday` … → ``{"monday": 440, …}``, skipping anything unreadable."""
    found = {}
    for day in const.WEEKDAYS:
        minutes = _int(raw.get(f"{prefix}{day.capitalize()}"))
        if minutes is not None:
            found[day] = minutes
    return found


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
