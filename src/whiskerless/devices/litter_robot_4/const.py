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
    # Dispense-choreography burst (activity only). NOT proof a hopper exists:
    # two 1.1.75 robots that both carry one disagree — one emits the burst most
    # cycles, the other never has — see events.HopperDispensed.
    LITTER_HOPPER_DISPENSED = 0x0C
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
    # Status annunciator (activity only): fires alongside state transitions,
    # naming the event. See STATUS_ANNUNCIATIONS for the live-labeled values.
    STATUS_ANNUNCIATOR = 0x0B
    ODOMETER_POWER_CYCLES = 0x3D
    ODOMETER_CLEAN_CYCLES = 0x3E
    ODOMETER_EMPTY_CYCLES = 0x3F
    # Counts filter-change WIZARD ENTRIES, stamped at wizard start (live: 2→3
    # the moment the panel combo registered). NOT a cycles-since-filter
    # countdown — the app's "replace filter" nag must be computed cloud-side,
    # so a local robot never nags and this only moves when the wizard runs.
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
    # Activity-only registers, named from a 50-hour two-robot capture. Nothing
    # consumes these yet; naming them stops a decoder reporting them as unknown
    # and gives future work somewhere to hang evidence.
    CYCLE_PHASE_SECONDS = 0x3C       # per-phase elapsed seconds within a cycle
    DRAWER_LASER_1 = 0x48            # the primary laser DFI_LEVEL_PERCENT tracks
    DRAWER_LASER_2 = 0x49
    DRAWER_LASER_3 = 0x4A
    VISIT_WEIGHT_HOLD_SECONDS = 0x6F  # matches the weight-on-scale span 9/9
    VISIT_CLOSE_KIND = 0xB9          # 1 below a 0xBC of ~19, 2 above ~23
    ROBOT_CYCLE_STATUS = 0x4E
    ROBOT_CYCLE_STATE = 0x4F
    # Hopper subsystem channel (activity only; not in the state document), and
    # NOT a link state — nothing derives connectivity from it. -15 was long read
    # as "link lost on detach AND bonnet lift"; it fired on neither of two
    # narrated bonnet lifts, and did fire for opening the hopper's own drawer.
    # Positives arrive with the hopper sitting on a bench. -17/-30/-31 unexplained.
    # See docs/devices/litter-robot-4/registers.md.
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
# 100, matching the cloud field's units. Briefly 50, on the strength of one
# reading: raw 408 attributed to Nahla (~8.1 lb on a household scale), where
# only /50 gives a whole cat. A 23h37m capture then produced seven distinct
# raws (666-1095) that /50 turns into 13.3-21.9 lb — double every cat in the
# household (owner-attributed range ~8-12 lb) — while /100 gives 6.7-11.0 lb
# and reads raw 809 as 8.09 lb, matching Nahla's weigh-in exactly. That makes
# the lone 408 (~half of 809) the anomaly, not the units. If weights ever look
# halved again, suspect another 408-style partial reading before this divisor.
CAT_WEIGHT_DIVISOR = 100


# PANEL_BUTTON (0x01) values, as emitted by the robot on a physical press and
# accepted back as a synthesised one. Structure (proven by an owner-narrated
# combo capture on 1.4.4): hi byte = button BITMASK, lo byte = press TYPE.
# Buttons OR together for combos — the filter-change chord emitted 0x0A02 =
# (Cycle 0x02 | Empty 0x08) with press type 02.
#
#   button bits: 0x02 Cycle · 0x04 Reset · 0x08 Empty (combo-proven)
#   press types: 0x01 short press · 0x02 long press (3 s hold)
#
# 0x010000 is what the register reads between presses.
#
# Only press type 01 can be synthesised. Writing type 02 produces no event at
# all, while an unknown type (00) is normalised to 01 and performed — so the
# firmware recognises the long press and declines it rather than defaulting.
# Every hold-only chord, the filter wizard included, is therefore out of reach
# from MQTT; see ROBOT_STATUS 14 / ROBOT_CYCLE_STATUS 14-15 for what the
# physical chord does.
PANEL_BUTTON_CYCLE = 0x0201
PANEL_BUTTON_RESET = 0x0401
# Captured from a physical Empty press, never yet written. Cycle and Reset are
# proven as writes and this differs from them only in the button bit, at the
# same press type, so it is expected to work — but expected is not proven, and
# the cost of being wrong is a globe that dumps its litter into the drawer.
PANEL_BUTTON_EMPTY = 0x0801
# Power TOGGLES: one press turns a running robot off, the next turns it back on.
# PROVEN as a write and shown equivalent to a finger in the same capture — the
# write emitted 0x010101 and so did the physical press that restored the robot
# 143 seconds later. A robot switched off this way cannot be switched back on
# over MQTT, because it is no longer on the network.
PANEL_BUTTON_POWER = 0x0101
# Connect TOGGLES the robot's WiFi. The write lands (the robot was gone 0.8 s
# later, panel light white) but can never be ECHOED the way the others were: the
# press destroys the transport that would report it, in both directions. So this
# is proven by disappearance, not by a register read, and there is no way to make
# it stronger. Recovery is a physical press — nothing over MQTT reaches a robot
# that is off the network.
#
# A LONG Connect press is onboarding mode and is refused outright (see safety.py);
# only this short one is reachable, and long presses cannot be written at all.
PANEL_BUTTON_CONNECT = 0x1001


# HOPPER_LINK (0x57) value historically read as "hopper disconnected" (int16 -15).
#
# That reading is not safe. A narrated 2026-08-11 session produced -15 for a full
# hopper detach AND for merely pulling the hopper's drawer, so a routine refill makes
# this read disconnected; nothing on the wire announces reconnection. Positives fire
# on a robot with the hopper physically in the owner's hand, so they prove nothing
# either. Other negatives stay unnamed: -30 (0xFFE2) recurs on an idle robot with the
# hopper attached and dispensing normally, and -17/-31 appeared once each.
HOPPER_LINK_DISCONNECTED = 0xFFF1

# STATUS_ANNUNCIATOR (0x0B) values (the "random housekeeping" values were never
# random — 102 is dusk/dawn and light switches). Documentation-grade: nothing
# consumes these yet, but they turn a formerly-opaque chatter register into
# named events for future decoding work.
# Value 8 has 10 live emissions (8 on one robot, 2 on the other) and no label yet;
# 12 has never been seen here, but neither has the filter wizard that would raise it.
STATUS_ANNUNCIATIONS: dict[int, str] = {
    7: "bonnet_removed",
    9: "cat_detected",
    12: "filter_wizard_waiting",
    20: "cycle_running",
    22: "ready",
    102: "night_light_changed",   # fires with IS_NIGHT_LIGHT_LED_ON transitions
    # 105 was labeled "fires on a Reset press". It has now failed to appear across
    # NINE Reset presses on two robots, in 230 annunciator readings. Whatever
    # raises it, a Reset press alone does not.
    105: "reset_tare",
}

# LITTER_HOPPER_DISPENSED (0x0C) phase whose value is the hopper's own fill
# gauge (see events.HopperDispensed).
HOPPER_DISPENSE_FILL_PHASE = 1

# Fill-gauge bands from a full live drain-to-refill arc (11 days, ESP 1.4.4):
# 89-92 maintained · 76→66 draining · 66-70 flatlined EMPTY (floor reading of
# the bare auger; the firmware itself never flags empty and keeps running a
# normal dispense every cycle) · 84 immediately after a refill (fresh litter
# mounds unevenly before dispenses redistribute it). The bands don't overlap;
# <= this threshold means empty. Only meaningful once 0x57 has corroborated
# that a hopper exists: a second 1.1.75 robot's phase-1 values (58-84 observed)
# land in the same range without any drain behind them.
HOPPER_FILL_EMPTY_MAX = 72


# Per-weekday sleep/wake registers (0x1E–0x2B). Sun→Sat, sleep-then-wake per day.
# The layout and round-trip are live-proven on 1.1.75; other firmware has not been
# checked. See docs/devices/litter-robot-4/compatibility.md.
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
# pylitterbot's LitterBoxStatus lists names this map has no int for: `offline`,
# `drawer_full`, `paused`, `cat_sensor_interrupted`, `cat_sensor_fault`, and
# `empty_cycle` (which only the string form below has produced). Useful as
# CANDIDATES for a newly observed int, and nothing stronger — that vocabulary is
# what the cloud presents, computed from several fields, not an enumeration of
# this register. `paused` is the proof: a paused cycle holds robotStatus 10 and
# says so through robotCycleState 4. Do not force an unmapped int onto one of
# these names because the list is short.
ROBOT_STATUS: dict[int, str] = {
    4: "ready",               # live-captured, 1.1.75 + 1.4.4
    5: "bonnet_removed",      # live-captured, 1.4.4
    6: "cat_sensor_timing",   # post-visit countdown, early tick (1.4.4 + 1.1.75)
    # Follows the scale, not the globe: 1.1.75 held 7 for 2h15m with the ToF
    # reading an undisturbed litter bed the whole time.
    7: "cat_sensor_timing",   # countdown / weight-hold, red panel light (1.4.4 + 1.1.75)
    10: "clean_cycle",        # live-captured, 1.1.75 + 1.4.4
    # The earlier capture walked 1 -> 3 -> 2 -> 13 across a panel Power off AND
    # on, which could not say which half was which, so all three shared a slug.
    # 2026-08-16 ran the halves separately on 1.1.75 — a written 0x02010101 to
    # power down, a physical press to power up — and they split cleanly:
    #   down: 0x340001 then 0x340003, unitPowerStatus (0x31) 1 -> 0
    #   up:   0x340002 then ready (4), unitPowerStatus 0 -> 1
    # So 1 and 3 are the down-stroke and 2 is the up-stroke. 13 did not appear on
    # that boot, which is why it keeps its own slug rather than joining 2.
    #
    # 13 is the automatic cycle a robot runs on boot — NOT the ordinary clean
    # cycle (10). It belongs in CLEANING_STATUSES because the globe is turning:
    # unmapped, the ToF readings taken mid-rotation publish as a real litter level.
    1: "powering_down",
    2: "powering_up",
    3: "powering_down",
    13: "power_up_cycle",     # live-captured, 1.1.75
    # The filter-change wizard, held for the whole wizard: the park rotation, the
    # indefinite wait, and the Reset-triggered ride home. Captured end to end on
    # 1.4.4 by CryingPecan. Routed through LITTER_UNRELIABLE_STATUSES rather than
    # CLEANING_STATUSES because the globe sits inverted and still for minutes —
    # not cycling, but certainly not measuring litter either.
    14: "changing_filter",    # live-captured, 1.4.4
    25: "cat_detected",       # weight on the scale / cat inside (1.4.4 + 1.1.75)
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
    # Filter-change wizard phases (owner-narrated chord, 1.4.4): 14 while
    # rotating to the dump-position park, 15 while parked waiting for the
    # human — indefinitely; bonnet removal during the wait triggers nothing.
    # The Reset-triggered return leg reuses the normal 4→5 (level/home) rails
    # with robotStatus still 14 throughout. Deliberately NOT in
    # ACTIVE_CYCLE_STATUSES: the wizard is never a clean cycle.
    14: "filter_park",
    15: "filter_wait",
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
