"""Semantic events extracted from the ``…/activity`` stream.

Several LR4 facts never appear in the state document and exist ONLY as activity
readings — live-proven on ESP 1.4.4 with a LitterHopper attached:

* **cat weight** (register 0x09): fires once per cat visit, raw int16 / 100 lb.
  The local state doc has no weight field, so this stream is the only source.
* **hopper dispense** (register 0x0C): a burst of phase-tagged values at the
  tail of a clean cycle when the hopper tops up the globe.
* **hopper link** (register 0x57): 0xFFF1 (-15) when the hopper connection is
  lost (detach, or any bonnet movement — the hopper mounts on the bonnet);
  positive values while attached.
* **visit duration** (register 0xBC): seconds of settled weight, once per
  visit at its end. Also the gate for the weight event — visits under ~9 s
  often produce no 0x09 at all (0xBC then still fires, possibly with 0).
* **drawer bay** (register 0x56): waste-drawer removal/re-insert, otherwise
  silent. The state document's DFI fields never flag drawer removal.

Consumers feed :func:`events_from_readings` the readings of one
:class:`~.protocol.ActivityMessage` and react to the typed events.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import ActivityReading
from .const import (
    DRAWER_BAY_INSERTED,
    DRAWER_BAY_REMOVED,
    HOPPER_LINK_DISCONNECTED,
    Register,
)

__all__ = [
    "CatVisitEnded",
    "CatWeightMeasured",
    "DrawerBayChanged",
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
    """A per-visit scale measurement (register 0x09)."""

    weight_lb: float


@dataclass(frozen=True, slots=True)
class HopperDispensed:
    """The hopper dispensed litter (register 0x0C).

    ``raw`` is the phase-tagged wire value (observed as a burst of 2-3 codes per
    dispense, hi-nibble indexed, e.g. 0x010A/0x1059/0x2078); its exact meaning
    is still open, so it is passed through undecoded.
    """

    raw: int


@dataclass(frozen=True, slots=True)
class HopperLinkChanged:
    """Hopper link state (register 0x57): connected, or link lost (-15)."""

    connected: bool
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
class DrawerBayChanged:
    """The waste drawer was removed or re-inserted (register 0x56).

    ``removed`` is None for codes outside the two live-proven values
    (10 = removed, 14 = inserted); ``raw`` always carries the wire value.
    """

    removed: bool | None
    raw: int


type LitterRobotEvent = (
    CatWeightMeasured
    | HopperDispensed
    | HopperLinkChanged
    | CatVisitEnded
    | DrawerBayChanged
)


def events_from_readings(readings: list[ActivityReading]) -> list[LitterRobotEvent]:
    """Extract the semantic events from one activity message's readings.

    Unknown registers are ignored — the activity stream carries a large amount
    of unmapped telemetry that must never break event extraction.
    """
    events: list[LitterRobotEvent] = []
    for reading in readings:
        if reading.register == Register.CAT_WEIGHT:
            if reading.value:  # a 0 reading carries no measurement
                events.append(CatWeightMeasured(weight_lb=reading.value / 100))
        elif reading.register == Register.LITTER_HOPPER_DISPENSED:
            events.append(HopperDispensed(raw=reading.value))
        elif reading.register == Register.HOPPER_LINK:
            events.append(
                HopperLinkChanged(
                    connected=reading.value != HOPPER_LINK_DISCONNECTED,
                    raw=reading.value,
                )
            )
        elif reading.register == Register.CAT_VISIT_DURATION:
            if reading.value <= _VISIT_DURATION_MAX_S:
                events.append(CatVisitEnded(duration_s=reading.value))
        elif reading.register == Register.DRAWER_BAY:
            removed: bool | None = None
            if reading.value == DRAWER_BAY_REMOVED:
                removed = True
            elif reading.value == DRAWER_BAY_INSERTED:
                removed = False
            events.append(DrawerBayChanged(removed=removed, raw=reading.value))
    return events
