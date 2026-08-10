"""Litter-Robot 4 protocol constants — registers, opcodes, enums, topics.

Every value here is grounded in the reverse-engineering synthesis (see
``docs/devices/litter-robot-4/``). Confidence tags in comments mirror the
protocol bible: PROVEN (live-tested), HIGH (firmware-decisive), MED/LOW
(inference). The wire grammar and settings encodings are PROVEN; several enum
*integers* are only partially recovered, so decoders here tolerate both the raw
ints the firmware emits and the cloud-style strings, and fall back gracefully.
"""

from __future__ import annotations

from enum import IntEnum

# --- MQTT topics -------------------------------------------------------------
# The robot keeps the stock Whisker topic format after re-provisioning; only the
# broker it points at changes. SERIAL is the device serial / MQTT client-id.
TOPIC_PREFIX = "prod/LR4"


def command_topic(serial: str) -> str:
    """Topic the robot SUBSCRIBES to (we publish commands here)."""
    return f"{TOPIC_PREFIX}/{serial}/command"


def state_topic(serial: str) -> str:
    """Topic the robot PUBLISHES its full named state document to."""
    return f"{TOPIC_PREFIX}/{serial}/state"


def activity_topic(serial: str) -> str:
    """Topic the robot PUBLISHES telemetry / action echoes to."""
    return f"{TOPIC_PREFIX}/{serial}/activity"


def subscribe_topic(serial: str) -> str:
    """Wildcard covering state + activity (+ our own command echoes)."""
    return f"{TOPIC_PREFIX}/{serial}/#"


# --- ESP command opcodes (type-2 macro dispatch) -----------------------------
class Opcode(IntEnum):
    """The 9 ESP macro opcodes. Everything else is a generic register write."""

    REQUEST_STATE = 0xA0       # full named state doc → /state (READ-only)   PROVEN
    # Named for the schedule it was believed to return; a live send answers with
    # {"type": "activity", "wifiRssi": …} and nothing else. Kept under the old name
    # because it is public API.
    REPORT_SCHEDULE = 0xA1     # wifiRssi only → /activity                    PROVEN
    RESET_MB_OTA = 0xA3        # reset / main-board-OTA orchestrator — live: reboots or no-ops   NEVER
    GLOBE_MOTOR_OTA = 0xA4     # globe-motor OTA stager — BRICK RISK          NEVER
    REPORT_WIFI_EVENT = 0xA7   # wifi-event report → /activity (value 0 only) PROVEN
    REPORT_TOF = 0xA9          # ToF / sensor burst → /activity (READ-only)   PROVEN
    MB_FLASH = 0xAC            # main-board flash erase/write — BRICK         NEVER
    HW_RESET = 0xAD            # GPIO16 MCLR pulse + reg 0x30 — full PIC reboot NEVER
    REPORT_VERSION = 0xAE      # board id / firmware report → /activity       PROVEN


# Report macros that publish named JSON and are safe with value 0 (PROVEN live).
REPORT_MACROS: frozenset[int] = frozenset(
    {
        Opcode.REQUEST_STATE,
        Opcode.REPORT_SCHEDULE,
        Opcode.REPORT_WIFI_EVENT,
        Opcode.REPORT_TOF,
        Opcode.REPORT_VERSION,
    }
)


# --- PIC registers (flat namespace; type-1 read / type-2 write) --------------
class Register(IntEnum):
    """PIC register file. READ side is well-decoded; only the writable settings
    bank below is exposed for writes."""

    # Panel buttons. Read as telemetry for months before anyone tried writing it;
    # writing the code the robot emits for a button synthesises that press.
    PANEL_BUTTON = 0x01
    IS_DEBUG_MODE_ACTIVE = 0x05      # 64800-tick countdown when armed (not a bool)
    RTC_CHIP_ID = 0x06
    UNIT_POWER_TYPE = 0x07
    # Panel brightness, packed: hi-byte = DisplayIntensityHigh, lo-byte =
    # DisplayIntensityLow. High/Low name the AMBIENT light level, not the
    # brightness rank — behaviorally PROVEN on a live 1.4.4 robot with a
    # two-observation test: hi-byte forced to 5 → panel maximally dim in
    # daylight (hi = brightness in a BRIGHT room); at stock 40/50 in a
    # darkened room the panel stepped slightly BRIGHTER (lo = brightness in
    # a DARK room). Yes: the stock config is brighter at night (40/50).
    PANEL_BRIGHTNESS = 0x0E
    CAT_WEIGHT = 0x09                # activity: raw / CAT_WEIGHT_DIVISOR = lb
    LITTER_HOPPER_DISPENSED = 0x0C   # activity
    CLEAN_CYCLE_WAIT_TIME = 0x16     # minutes (direct)
    IS_KEYPAD_LOCKOUT = 0x17         # 0/1
    NIGHT_LIGHT_MODE = 0x18          # 0=off 1=on 2=auto
    NIGHT_LIGHT_BRIGHTNESS = 0x19    # 0–100 % (direct, clamped)
    IS_PANEL_SLEEP_MODE = 0x1A       # 0/1
    PANEL_SLEEP_TIME = 0x1B          # minutes-since-midnight (16-bit)
    PANEL_WAKE_TIME = 0x1C           # minutes-since-midnight (16-bit)
    WEEKDAY_SLEEP_MODE_ENABLED = 0x1D  # per-day bitmask, see WEEKDAY_SLEEP_ALL_DAYS
    # 0x1E–0x2B: per-weekday sleep/wake, see WEEKDAY_SCHEDULE_REGS
    UNIT_POWER_STATUS = 0x31
    SLEEP_STATUS = 0x32
    ROBOT_STATUS = 0x34
    GLOBE_MOTOR_FAULT_STATUS = 0x35
    CAT_DETECT = 0x37
    IS_USB_POWER_ON = 0x38
    USB_FAULT_STATUS = 0x39
    IS_BONNET_REMOVED = 0x3A
    IS_NIGHT_LIGHT_LED_ON = 0x3B
    ODOMETER_POWER_CYCLES = 0x3D
    ODOMETER_CLEAN_CYCLES = 0x3E
    ODOMETER_EMPTY_CYCLES = 0x3F
    ODOMETER_FILTER_CYCLES = 0x40
    IS_DFI_RESET_PENDING = 0x41      # read-only — NOT writable (0x02410001 is a no-op)
    DFI_NUMBER_OF_CYCLES = 0x42      # cycles since the firmware last DETECTED a
                                     # drawer empty. Not cleared by the empty itself
                                     # or by Reset; the firmware zeroes it (with
                                     # 0x45/0x46) on the first post-empty cycle whose
                                     # measurement confirms the drop — live-seen
                                     # twice, one and two cycles after a bag change
    # The drawer gauge is measurement-only on 1.4.4: it is read by three lasers
    # during the CYCLE_DFI phase (globe inverted) and NOT cleared by emptying
    # the drawer or pressing Reset — it self-corrects on the next cycle.
    # Percent tracks the primary raw laser (activity reg 0x48) at ≈ 0.70×raw
    # (r = 0.999 over a 38-cycle capture).
    DFI_LEVEL_PERCENT = 0x43         # waste drawer % (derived, see above)
    IS_DFI_FULL = 0x44
    DFI_FULL_COUNTER = 0x45
    DFI_TRIGGER_COUNT = 0x46
    LITTER_LEVEL = 0x47              # mm
    IS_DFI_PARTIAL_FULL = 0x4B       # one drawer SECTOR reads high while the rest
                                     # don't (three lasers = three sectors) — seen
                                     # live when a fresh bag liner bunched under
                                     # one laser: 21 % overall yet partial-full=1
    GLOBE_MOTOR_RETRACT_FAULT_STATUS = 0x4D
    ROBOT_CYCLE_STATUS = 0x4E
    ROBOT_CYCLE_STATE = 0x4F
    # Hopper link/state channel (activity only; not in the state document).
    # Live-observed on ESP 1.4.4 with a LitterHopper: 0xFFF1 (-15) = link lost
    # (fires on hopper detach AND bonnet lift — the hopper rides on the bonnet);
    # positive values (19/30/35-48/87) form an init/measurement sequence whose
    # exact meaning is still open. See docs/devices/litter-robot-4/registers.md.
    HOPPER_LINK = 0x57
    TOF1 = 0x58
    TOF2 = 0x59
    TOF3 = 0x5A
    # Waste-drawer bay events (activity only). Near-silent except when the drawer
    # moves; the value does NOT say which way — see DrawerBayMoved.
    DRAWER_BAY = 0x56
    # Visit duration in seconds of settled weight on the scale (activity only;
    # fires once at visit end alongside the 0xB9 closure marker). Live-proven
    # against narrated visits: forced <5 s placements report 0, natural visits
    # 9-21 s. It also gates CAT_WEIGHT: ~9 s+ always produced a weight event,
    # 8 s and below often none. A Reset button press emits an unrelated large
    # value (592 observed) on the same register — see events.py's cap.
    CAT_VISIT_DURATION = 0xBC


# WEEKDAY_SLEEP_MODE_ENABLED (0x1D) is a per-day BITMASK, not a boolean: bit i
# enables the schedule for WEEKDAYS[i], Sunday-first, matching the 0x1E+2i layout.
# A panel long-press of Cycle (the 8-hour sleep) sets it to 0x7F — every day —
# which is what revealed the shape. Writing 1 enables Sunday alone, so a naive
# "on" looks like it works if you happen to test on a Sunday and does nothing
# for the rest of the week.
WEEKDAY_SLEEP_ALL_DAYS = 0x7F


# CAT_WEIGHT (0x09) raw-to-pounds divisor.
#
# The inherited value was 100, taken from the cloud field's units and never
# checked against a weighed animal. Measured on 2026-08-10: the robot reported
# raw 408 twice for a visit by Nahla, who weighs ~8.1 lb on a household scale.
# 408/100 = 4.08 lb (half the cat); 408/50 = 8.16 lb.
#
# ONE comparison, against a home weigh-in that carries its own error — but a
# factor of 1.99 is not weighing error. Treated as the better of two estimates
# rather than settled: a second cat, or a second robot, would confirm it. If a
# reported weight ever looks like double the animal, this is the first suspect.
CAT_WEIGHT_DIVISOR = 50


# PANEL_BUTTON (0x01) values, as emitted by the robot on a physical press and
# accepted back as a synthesised one. The trailing 01 is the press; 0x010000 is
# what the register reads between presses.
PANEL_BUTTON_CYCLE = 0x0201
PANEL_BUTTON_RESET = 0x0401

# HOPPER_LINK (0x57) value meaning "hopper disconnected" (int16 -15, live-PROVEN
# on detach/reattach and bonnet lift/reseat).
#
# Other negatives are NOT disconnections and must stay unnamed: -30 (0xFFE2) recurs
# on an idle robot with the hopper attached and dispensing normally, so treating any
# negative as a fault would report a working hopper as gone.
HOPPER_LINK_DISCONNECTED = 0xFFF1

# LITTER_HOPPER_DISPENSED (0x0C) phase whose value is the hopper's own fill
# gauge (see events.HopperDispensed).
HOPPER_DISPENSE_FILL_PHASE = 1

# Fill-gauge bands from a full live drain-to-refill arc (11 days, ESP 1.4.4):
# 89-92 maintained · 76→66 draining · 66-70 flatlined EMPTY (floor reading of
# the bare auger; the firmware itself never flags empty and keeps running a
# normal dispense every cycle) · 84 immediately after a refill (fresh litter
# mounds unevenly before dispenses redistribute it). The bands don't overlap;
# <= this threshold means empty.
HOPPER_FILL_EMPTY_MAX = 72


# Per-weekday sleep/wake registers (0x1E–0x2B). Sun→Sat, sleep-then-wake per day.
# ASSUMED layout (the round-trip is PROVEN; the exact day ordering is inferred —
# see docs/devices/litter-robot-4/compatibility.md before trusting day labels).
WEEKDAYS: tuple[str, ...] = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)
WEEKDAY_SCHEDULE_REGS: dict[str, tuple[int, int]] = {
    day: (0x1E + 2 * i, 0x1F + 2 * i) for i, day in enumerate(WEEKDAYS)
}


# --- Enums (firmware emits raw ints; decoders also accept cloud strings) ------
# robotStatus (0x34). One map for every firmware: 1.1.75 and 1.4.4 agree on every
# value either has been observed to emit, so there is deliberately no version
# gate here. Values are tagged with the firmware they were captured on.
ROBOT_STATUS: dict[int, str] = {
    4: "ready",               # live-captured, 1.1.75 + 1.4.4
    5: "bonnet_removed",      # live-captured, 1.4.4
    6: "cat_sensor_timing",   # post-visit countdown, early tick (1.4.4)
    7: "cat_sensor_timing",   # countdown / weight-hold, red panel light (1.4.4)
    10: "clean_cycle",        # live-captured, 1.1.75 + 1.4.4
    # Power-up, captured end to end on 1.1.75 across a panel Power off/on:
    # robotStatus walks 1 -> 3 -> 2 -> 13, odometerPowerCycles ticking in the same
    # burst. Which of 1/2/3 means what is unresolved, so all three share a slug.
    #
    # 13 is the automatic cycle a robot runs on boot — NOT the ordinary clean
    # cycle (10). It belongs in CLEANING_STATUSES because the globe is turning:
    # unmapped, the ToF readings taken mid-rotation publish as a real litter level.
    1: "powering_up",
    2: "powering_up",
    3: "powering_up",
    13: "power_up_cycle",     # live-captured, 1.1.75
    # The filter-change wizard, held for the whole wizard: the park rotation, the
    # indefinite wait, and the Reset-triggered ride home. Captured end to end on
    # 1.4.4 by CryingPecan. Routed through LITTER_UNRELIABLE_STATUSES rather than
    # CLEANING_STATUSES because the globe sits inverted and still for minutes —
    # not cycling, but certainly not measuring litter either.
    14: "changing_filter",    # live-captured, 1.4.4
    25: "cat_detected",       # weight on the scale / cat inside (1.4.4)
}
ROBOT_STATUS_STRINGS: dict[str, str] = {
    "robot_idle": "ready",
    "robot_clean": "clean_cycle",
    "robot_find_dump": "clean_cycle",
    "robot_empty": "empty_cycle",
    "robot_cat_detect": "cat_detected",
    "robot_cat_detect_delay": "cat_sensor_timing",
    "robot_bonnet": "bonnet_removed",
    "robot_power_up": "powering_up",
    "robot_power_down": "powering_down",
    "robot_power_off": "off",
    # The filter-change wizard parks the globe inverted and waits. Both forms
    # decode: this string from a cloud-connected robot, and the local int 14 above.
    "robot_change_filter": "changing_filter",
}
# Status values that mean the globe is actively cycling.
CLEANING_STATUSES: frozenset[str] = frozenset(
    {"clean_cycle", "empty_cycle", "power_up_cycle"}
)

# Statuses where the ToF sensors are not looking at a level litter bed, so any
# litter reading is meaningless. Broader than CLEANING_STATUSES: the
# filter-change wizard parks the globe inverted for minutes at a time without
# ever being a clean cycle.
LITTER_UNRELIABLE_STATUSES: frozenset[str] = CLEANING_STATUSES | frozenset({"changing_filter"})

# Every slug the decoder produces from a value it actually recognized. An
# unmapped int decodes to "unknown_N" and an unseen cloud string passes through
# verbatim (the firmware has string families we have never captured, e.g. the
# filter-change wizard) — in both cases the status is not understood and
# is_cleaning must defer to the cycle machine rather than assume "not cleaning".
KNOWN_STATUSES: frozenset[str] = frozenset(ROBOT_STATUS.values()) | frozenset(
    ROBOT_STATUS_STRINGS.values()
)

NIGHT_LIGHT_MODE: dict[int, str] = {0: "off", 1: "on", 2: "auto"}  # PROVEN
# ESP 1.4.4 marches cycleStatus 2→3→4→5→1 per cycle (live-observed, 15/15).
# Phase names from the cloud's own strings, captured live during an
# app-triggered cycle on a cloud-connected 1.4.4 robot:
# CYCLE_DUMP → CYCLE_DFI → CYCLE_LEVEL → CYCLE_HOME → CYCLE_IDLE.
# NOTE: on 1.4.x, 3 = the DFI (drawer measurement) phase — the legacy "home"
# label for 3 does not match this firmware; 5 is the home/return phase (this
# is also when the LitterHopper dispenses: during CYCLE_LEVEL, value 4).
ROBOT_CYCLE_STATUS: dict[int, str] = {
    0: "init",
    1: "idle",
    2: "dump",
    3: "home",    # legacy label; on ESP >= 1.4 this phase is CYCLE_DFI
    4: "level",   # CYCLE_LEVEL (hopper dispenses here)
    5: "home",    # CYCLE_HOME
}
# ESP 1.4.4 also emits transient 12 (0x0C) / 15 (0x0F) states mid-cycle.
ROBOT_CYCLE_STATE: dict[int, str] = {
    1: "idle",
    2: "cycle",
    3: "cycle",
    # 4 = safety pause: a cat entered mid-cycle and the globe halted.
    # Owner-witnessed live (2026-07-31): cat jumped into a running cycle →
    # cat-detect burst + state 4, globe stopped; robotStatus stayed at
    # clean-cycle (10) throughout, so this state is the ONLY pause signal.
    # A Cycle press resumed, re-running the phase ladder from the top
    # without a second odometer tick. Every other capture of 4 (10/10)
    # coincided with cat-detect activity mid-cycle.
    4: "cat_interrupt",
    12: "cycle",  # ESP 1.4.x dump/return excursion
    15: "cycle",  # ESP 1.4.x dump/return excursion
}
# cycleStatus values that mean a cycle is actively running (used as a fallback
# is_cleaning signal when robotStatus is an unmapped int).
ACTIVE_CYCLE_STATUSES: frozenset[str] = frozenset({"dump", "home", "level", "cycle"})

# nightLightBrightness presets pylitterbot uses (the % is direct, these are labels).
BRIGHTNESS_PRESETS: dict[str, int] = {"low": 25, "medium": 50, "high": 100}

# clean-cycle wait-time minutes the app offers.
# Register 0x16 holds plain minutes; the robot accepts any value in this range
# (live-tested at 3, 7 and 20), and the app exposes the whole span.
CLEAN_CYCLE_WAIT_MIN_MINUTES = 3
CLEAN_CYCLE_WAIT_MAX_MINUTES = 30
