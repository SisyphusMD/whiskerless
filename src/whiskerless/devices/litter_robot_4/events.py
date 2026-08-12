"""Semantic events extracted from the ``…/activity`` stream.

Several LR4 facts never appear in the state document and exist ONLY as activity
readings — live-proven on ESP 1.4.4 with a LitterHopper attached:

* **cat weight** (register 0x09): raw int16 / 100 lb, reported around qualifying
  visits. Short visits can omit it, and 1.1.75 has repeated or delayed readings.
  The local state doc has no weight field, so this stream is the only source.
* **hopper dispense** (register 0x0C): a burst of phase-tagged values at the
  tail of a clean cycle. Not proof a hopper exists — a hopperless 1.1.75 robot
  emits the same burst — so corroborate with 0x57 before treating it as
  hopper data.
* **hopper link** (register 0x57): 0xFFF1 (-15) when the hopper connection is
  lost (detach, or any bonnet movement — the hopper mounts on the bonnet);
  positive values while attached.
* **visit duration** (register 0xBC): seconds of settled weight, once per
  visit at its end. Also the gate for the weight event — visits under ~9 s
  often produce no 0x09 at all (0xBC then still fires, possibly with 0).
* **drawer bay** (register 0x56): the waste drawer moved, otherwise silent.
  Which way it moved is not recoverable — see :class:`DrawerBayMoved`.

Consumers feed :func:`events_from_readings` the readings of one
:class:`~.protocol.ActivityMessage` and react to the typed events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .codec import ActivityReading
from .const import (
    CAT_WEIGHT_DIVISOR,
    HOPPER_LINK_DISCONNECTED,
    Register,
)

__all__ = [
    "CatVisitEnded",
    "CatWeightMeasured",
    "DrawerBayMoved",
    "HopperDispensed",
    "HopperLinkChanged",
    "LitterRobotEvent",
    "events_from_readings",
]

# 0xBC values above this are not visit durations: real visits measured 0-25 s,
# while a panel Reset press emitted 592 on the same register (tare context).
# The cap keeps a stuck-cat outlier while dropping the button artifacts.
_VISIT_DURATION_MAX_S = 300


@dataclass(frozen=True, slots=True)
class CatWeightMeasured:
    """A scale measurement reported around a visit (register 0x09)."""

    weight_lb: float


@dataclass(frozen=True, slots=True)
class HopperDispensed:
    """One phase of a hopper dispense (register 0x0C).

    A dispense is a burst of 2-3 hi-nibble-indexed codes (e.g.
    0x010A/0x1059/0x2078). ``phase`` is the hi-nibble, ``value`` the low
    12 bits, ``raw`` the wire value. Phase semantics from an 11-day capture
    spanning a full hopper drain:

    * phase 0 — routine step marker (266/271/276 observed, invariant)
    * phase 1 — **the hopper's own fill gauge**: 89-92 while maintained near
      the owner's ~90% target, declining monotonically (76→66) as the hopper
      ran down. Unitless until the empty/refill anchors calibrate it.
    * phase 2 — routine step marker (119-121 observed, invariant)

    The burst is NOT evidence a hopper is attached: a hopperless 1.1.75 robot
    emits it most cycles (phase-1 values 58-84), while the hopper-attached
    1.1.75 has never emitted 0x0C. Treat phase 1 as a fill gauge only after
    0x57 has corroborated the hardware.
    """

    raw: int
    phase: int
    value: int


@dataclass(frozen=True, slots=True)
class HopperLinkChanged:
    """Hopper link state (register 0x57).

    Positive values are the healthy per-visit choreography (9-110 observed so far).
    Negative values are faults, of which only -15 is characterized (detach, and
    any bonnet movement — the hopper mounts on the bonnet). A second negative,
    -30, recurs on 1.1.75 with the hopper attached and healthy — mostly inside
    clean cycles, once after a visit — so the fault space is wider than one code.

    ``connected`` is therefore tri-state: ``None`` for a negative we cannot
    name, rather than forcing an unrecognized fault to read as connected.
    """

    connected: bool | None
    raw: int


@dataclass(frozen=True, slots=True)
class CatVisitEnded:
    """A cat visit ended (register 0xBC): seconds of settled scale weight.

    Fires whether or not the visit was long enough to yield a weight event
    (under ~9 s the firmware usually withholds 0x09 but still reports the
    duration, including 0 for a hop-through).
    """

    duration_s: int


@dataclass(frozen=True, slots=True)
class DrawerBayMoved:
    """The waste drawer moved (register 0x56). Direction is NOT knowable.

    Three rounds of narrated pulls failed to separate removal from insertion:
    codes 10, 11, 13, 14, 15, 16, 17 and 28 all appeared, with removals and
    insertions sharing values, and seating the drawer fully sometimes emitting
    nothing at all. Three successive attempts to name a removal code each held
    until the next capture contradicted them.

    A direct read answers ~78 whether the drawer is in or out, so position is not
    recoverable that way either — the register reports the *event*, not a state.
    Hence this carries only ``raw`` and the fact that something happened. Note
    that a type-1 read of 0x56 also produces a reading here; nothing in this
    library issues one.
    """

    raw: int


# PEP 695 `type` syntax is 3.12+; the library floor is 3.11 (the integration,
# which runs on HA's 3.13, uses it freely).
LitterRobotEvent: TypeAlias = (
    CatWeightMeasured
    | HopperDispensed
    | HopperLinkChanged
    | CatVisitEnded
    | DrawerBayMoved
)


def _hopper_connected(value: int) -> bool | None:
    """Resolve a 0x57 reading to link state, or None when the code is unknown."""
    if value == HOPPER_LINK_DISCONNECTED:
        return False
    # int16: the fault codes are negative, the healthy choreography positive.
    return True if value < 0x8000 else None


def events_from_readings(readings: list[ActivityReading]) -> list[LitterRobotEvent]:
    """Extract the semantic events from one activity message's readings.

    Unknown registers are ignored — the activity stream carries a large amount
    of unmapped telemetry that must never break event extraction.
    """
    events: list[LitterRobotEvent] = []
    for reading in readings:
        if reading.register == Register.CAT_WEIGHT:
            if reading.value:  # a 0 reading carries no measurement
                events.append(CatWeightMeasured(weight_lb=reading.value / CAT_WEIGHT_DIVISOR))
        elif reading.register == Register.LITTER_HOPPER_DISPENSED:
            events.append(
                HopperDispensed(
                    raw=reading.value,
                    phase=reading.value >> 12,
                    value=reading.value & 0x0FFF,
                )
            )
        elif reading.register == Register.HOPPER_LINK:
            events.append(
                HopperLinkChanged(
                    connected=_hopper_connected(reading.value),
                    raw=reading.value,
                )
            )
        elif reading.register == Register.CAT_VISIT_DURATION:
            if reading.value <= _VISIT_DURATION_MAX_S:
                events.append(CatVisitEnded(duration_s=reading.value))
        elif reading.register == Register.DRAWER_BAY:
            events.append(DrawerBayMoved(raw=reading.value))
    return events
