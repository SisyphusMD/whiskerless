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

Consumers feed :func:`events_from_readings` the readings of one
:class:`~.protocol.ActivityMessage` and react to the typed events.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import ActivityReading
from .const import HOPPER_LINK_DISCONNECTED, Register

__all__ = [
    "CatWeightMeasured",
    "HopperDispensed",
    "HopperLinkChanged",
    "LitterRobotEvent",
    "events_from_readings",
]


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


type LitterRobotEvent = CatWeightMeasured | HopperDispensed | HopperLinkChanged


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
    return events
