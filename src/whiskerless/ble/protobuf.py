"""A tiny pure-Python protobuf codec — just enough for protocomm provisioning.

The provisioning endpoints speak protobuf, but pulling in the full ``protobuf``
runtime (and a ``protoc`` build step) for a handful of fixed messages is
overkill. These helpers encode/decode exactly the field shapes the LR4
``mqtt-config`` / ``whisker-config`` / ``prov-config`` endpoints use.

Critically, this matches proto3 wire semantics: scalar fields equal to their
default (0 / "") are **omitted**, which is what the firmware's protobuf-c
decoder and the official app both produce. Message (oneof-arm) fields are always
emitted — even when empty — because their presence selects the oneof arm.
"""

from __future__ import annotations

from collections.abc import Iterator

WIRE_VARINT = 0
WIRE_LEN = 2


def encode_varint(value: int) -> bytes:
    """LEB128 unsigned varint."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return encode_varint(field << 3 | wire)


def field_varint(field: int, value: int) -> bytes:
    """A varint field, omitted when zero (proto3 default)."""
    if value == 0:
        return b""
    return _tag(field, WIRE_VARINT) + encode_varint(value)


def field_string(field: int, value: str) -> bytes:
    """A string field, omitted when empty (proto3 default)."""
    if not value:
        return b""
    data = value.encode("utf-8")
    return _tag(field, WIRE_LEN) + encode_varint(len(data)) + data


def field_message(field: int, data: bytes) -> bytes:
    """A length-delimited sub-message — always emitted (selects a oneof arm)."""
    return _tag(field, WIRE_LEN) + encode_varint(len(data)) + data


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def iter_fields(data: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield ``(field_number, wire_type, value)`` for a serialized message.

    Varints come back as ``int``; length-delimited as ``bytes``. Other wire
    types (fixed32/64, groups) are not used by these endpoints and are skipped.
    """
    pos = 0
    end = len(data)
    while pos < end:
        key, pos = _read_varint(data, pos)
        field = key >> 3
        wire = key & 0x07
        if wire == WIRE_VARINT:
            value, pos = _read_varint(data, pos)
            yield field, wire, value
        elif wire == WIRE_LEN:
            length, pos = _read_varint(data, pos)
            chunk = data[pos : pos + length]
            pos += length
            yield field, wire, chunk
        elif wire == 5:  # fixed32
            pos += 4
        elif wire == 1:  # fixed64
            pos += 8
        else:
            break  # unsupported / malformed — stop rather than misread


def read_fields(data: bytes) -> dict[int, list[int | bytes]]:
    """Collect a message into ``{field_number: [values...]}``."""
    fields: dict[int, list[int | bytes]] = {}
    for field, _wire, value in iter_fields(data):
        fields.setdefault(field, []).append(value)
    return fields
