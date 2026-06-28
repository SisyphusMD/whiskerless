"""Wire codec round-trips and the value-byte-order anchors."""

from __future__ import annotations

import json

import pytest

from whiskerless.devices.litter_robot_4.codec import (
    decode_activity_code,
    encode_command_payload,
    encode_read,
    encode_write,
)
from whiskerless.exceptions import ProtocolError


def test_encode_read() -> None:
    assert encode_read(0x47) == "0x01470000"
    assert encode_read(0x00) == "0x01000000"
    assert encode_read(0xFF) == "0x01FF0000"


def test_encode_write_8bit_lands_in_low_byte() -> None:
    # PROVEN anchor: nightLightBrightness=100 (0x64) -> 0x02190064.
    assert encode_write(0x19, 0x64) == "0x02190064"
    assert encode_write(0x18, 1) == "0x02180001"
    assert encode_write(0xA0, 0) == "0x02A00000"


def test_encode_write_16bit_packs_both_bytes() -> None:
    # panelBrightness packs hi=High, lo=Low; time-of-day is minutes-since-midnight.
    assert encode_write(0x0E, 0x3232) == "0x020E3232"
    assert encode_write(0x1B, 1320) == "0x021B0528"  # 22:00


@pytest.mark.parametrize("value", [-1, 0x10000])
def test_encode_write_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ProtocolError):
        encode_write(0x19, value)


def test_encode_write_rejects_bad_register() -> None:
    with pytest.raises(ProtocolError):
        encode_write(0x100, 0)


def test_command_payload_shape() -> None:
    payload = encode_command_payload("LR4C000001", ["0x02A00000"])
    assert json.loads(payload) == {"serial": "LR4C000001", "data": ["0x02A00000"]}


@pytest.mark.parametrize(
    ("code", "register", "value"),
    [("0xA50001", 0xA5, 1), ("0x330022", 0x33, 0x22), ("0x584100", 0x58, 0x4100)],
)
def test_decode_activity_code(code: str, register: int, value: int) -> None:
    reading = decode_activity_code(code)
    assert (reading.register, reading.value) == (register, value)
    assert reading.hex.lower() == f"0x{register:02x}{value:04x}"


def test_decode_activity_code_rejects_non_hex() -> None:
    with pytest.raises(ProtocolError):
        decode_activity_code("0xZZZZ")
