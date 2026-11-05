"""Minimal BTSnoop (Android "Bluetooth HCI snoop log") reader.

File layout, all big-endian: an 8-byte magic ``btsnoop\\0``, u32 version (1),
u32 datalink (1002 = HCI UART/H4, 1001 = un-encapsulated HCI). Then records of
u32 original length, u32 included length, u32 flags, u32 cumulative drops,
i64 timestamp in microseconds since 0000-01-01, and the packet.

Flags: bit 0 set = received (controller to host), bit 1 set = command or event
rather than data. H4 packets start with a type byte: 0x01 command, 0x02 ACL,
0x04 event.

:func:`records` yields the same ``(seconds, type, payload)`` tuples as
:mod:`pklg`, with the PacketLogger type codes (0x00 command, 0x01 event,
0x02 ACL sent, 0x03 ACL received), so the decoders downstream are format-blind.
"""
from __future__ import annotations

import pathlib
import struct

MAGIC = b"btsnoop\0"
DATALINK_H4 = 1002
DATALINK_HCI = 1001
#: Microseconds between 0000-01-01 and the Unix epoch, as BTSnoop counts them.
EPOCH_OFFSET_US = 0x00DCDDB30F2F8000

_H4_COMMAND, _H4_ACL, _H4_EVENT = 0x01, 0x02, 0x04
_PKLG_COMMAND, _PKLG_EVENT, _PKLG_ACL_TX, _PKLG_ACL_RX = 0x00, 0x01, 0x02, 0x03


def records(path):
    blob = pathlib.Path(path).read_bytes()
    if blob[:8] != MAGIC:
        raise ValueError(f"{path}: not a BTSnoop file")
    _version, datalink = struct.unpack_from(">II", blob, 8)
    if datalink not in (DATALINK_H4, DATALINK_HCI):
        raise ValueError(f"{path}: unsupported BTSnoop datalink {datalink}")
    off = 16
    while off + 24 <= len(blob):
        _orig, incl, flags, _drops, stamp = struct.unpack_from(">IIIIq", blob, off)
        packet = blob[off + 24: off + 24 + incl]
        off += 24 + incl
        if len(packet) < incl:
            break
        received = bool(flags & 0x1)
        if datalink == DATALINK_H4:
            if not packet:
                continue
            kind, packet = packet[0], packet[1:]
        elif flags & 0x2:
            kind = _H4_EVENT if received else _H4_COMMAND
        else:
            kind = _H4_ACL
        if kind == _H4_ACL:
            rtype = _PKLG_ACL_RX if received else _PKLG_ACL_TX
        elif kind == _H4_COMMAND:
            rtype = _PKLG_COMMAND
        elif kind == _H4_EVENT:
            rtype = _PKLG_EVENT
        else:
            continue
        yield (stamp - EPOCH_OFFSET_US) / 1e6, rtype, packet
