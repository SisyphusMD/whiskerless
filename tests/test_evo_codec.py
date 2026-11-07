"""The EVO's banked wire format, in both directions.

Fixtures are synthetic: the codes are the documented encodings, and the serial
is one of the invented examples.
"""

from __future__ import annotations

import json

import pytest

from whiskerless.devices.litter_robot_evo import const
from whiskerless.devices.litter_robot_evo.codec import (
    ActivityReading,
    decode_activity_code,
    encode_command_payload,
    encode_read,
    encode_write,
)
from whiskerless.exceptions import ProtocolError

SERIAL = "LRE-01-40-01-2610-000000"


def test_a_write_is_type_bank_register_and_a_16_bit_value() -> None:
    assert encode_write(0x02, 0x01, 0x0808) == "0x0202010808"
    assert encode_write(0x01, 0x03, 0x000A) == "0x020103000A"


def test_a_read_carries_a_zero_value() -> None:
    assert encode_read(0x01, 0x20) == "0x0101200000"


@pytest.mark.parametrize(("bank", "register"), [(0x100, 0x01), (0x01, -1)])
def test_out_of_range_addresses_are_refused(bank: int, register: int) -> None:
    with pytest.raises(ProtocolError, match="byte range"):
        encode_write(bank, register, 0)


def test_out_of_range_values_are_refused() -> None:
    with pytest.raises(ProtocolError, match="16-bit"):
        encode_write(0x02, 0x01, 0x10000)


def test_the_payload_names_the_serial_and_lists_every_element() -> None:
    payload = json.loads(encode_command_payload(SERIAL, ["0x0202090003", "0x02020A0001"]))
    assert payload == {"serial": SERIAL, "data": ["0x0202090003", "0x02020A0001"]}


def test_telemetry_decodes_bank_register_and_value() -> None:
    reading = decode_activity_code("0x02010808")
    assert (reading.bank, reading.register, reading.value) == (0x02, 0x01, 0x0808)
    assert reading.address == (0x02, 0x01)
    assert reading.hex == "0x02010808"


def test_the_weight_sensor_is_read_as_signed() -> None:
    assert decode_activity_code("0x051BFFD6").signed_value == -42
    assert decode_activity_code("0x051B0037").signed_value == 55


def test_a_reading_without_its_source_spells_itself_at_full_width() -> None:
    assert ActivityReading(bank=0x01, register=0x02, value=0x16).hex == "0x01020016"


@pytest.mark.parametrize("code", ["0x020808", "0x0202010808", "02010808xx", "0x0201_808", "0x0201080G"])
def test_anything_but_eight_hex_digits_is_refused(code: str) -> None:
    with pytest.raises(ProtocolError):
        decode_activity_code(code)


def test_topics_default_to_the_apps_prefix_and_take_another() -> None:
    assert const.command_topic(SERIAL) == f"prod/robots/{SERIAL}/command"
    assert const.activity_topic(SERIAL) == f"prod/robots/{SERIAL}/activity"
    assert const.event_topic(SERIAL) == f"prod/robots/{SERIAL}/event"
    assert const.subscribe_topic(SERIAL, prefix="prod/LR4") == f"prod/LR4/{SERIAL}/#"


def test_the_sleep_registers_run_sunday_first_sleep_then_wake() -> None:
    assert const.SLEEP_SCHEDULE_REGS["sunday"] == (0x11, 0x12)
    assert const.SLEEP_SCHEDULE_REGS["saturday"] == (0x1D, 0x1E)
