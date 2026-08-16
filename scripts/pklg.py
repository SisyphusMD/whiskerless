"""Minimal Apple PacketLogger (.pklg) reader.

Record layout, all big-endian: u32 length (covers everything after itself),
u32 seconds, u32 microseconds, u8 type, then payload.
"""
from __future__ import annotations

import datetime
import pathlib
import struct

TYPES = {0x00: "HCI_CMD", 0x01: "HCI_EVT", 0x02: "ACL_TX", 0x03: "ACL_RX",
         0x0a: "NOTE", 0x0b: "NOTE", 0xfb: "STR", 0xfc: "STR", 0xfe: "STR", 0xff: "STR"}

def records(path):
    blob = pathlib.Path(path).read_bytes()
    off = 0
    while off + 13 <= len(blob):
        (length,) = struct.unpack_from(">I", blob, off)
        if length < 9 or off + 4 + length > len(blob):
            break
        sec, usec = struct.unpack_from(">II", blob, off + 4)
        rtype = blob[off + 12]
        payload = blob[off + 13: off + 4 + length]
        yield sec + usec / 1e6, rtype, payload
        off += 4 + length

if __name__ == "__main__":
    import sys
    from collections import Counter
    for path in sys.argv[1:]:
        times, kinds, n = [], Counter(), 0
        for ts, rtype, _payload in records(path):
            n += 1
            times.append(ts)
            kinds[TYPES.get(rtype, f"0x{rtype:02x}")] += 1
        if not times:
            print(f"{path}: no records parsed")
            continue
        lo = datetime.datetime.fromtimestamp(min(times))
        hi = datetime.datetime.fromtimestamp(max(times))
        print(f"{path.split('/')[-1]}")
        print(f"  {n} records   {lo:%H:%M:%S} -> {hi:%H:%M:%S}  ({(max(times)-min(times))/60:.1f} min)")
        print(f"  {dict(kinds.most_common())}")
