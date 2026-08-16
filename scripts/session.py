"""Full decode of a Whisker-app BLE onboarding session from an Apple .pklg.

Covers the HCI layer (advertising, connection) and every protocomm endpoint,
not just mqtt-config. Secrets are measured, never printed.
"""
from __future__ import annotations

import datetime
import pathlib
import struct
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from pklg import records

# Canonical order, plus the reversed form: 128-bit UUIDs travel little-endian in
# advertising data, so a canonical-only match silently finds nothing.
PROV_SVC = bytes.fromhex("b7ee1c20dcfd4208881314845cac5212")
PROV_SVC_LE = PROV_SVC[::-1]

def t(ts):  # the pklg clock reads UTC-flavoured; render as the wall clock
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%H:%M:%S.%f")[:-3]

def one(fields, tag, default=None):
    got = fields.get(tag)
    return got[0] if got else default

def ad_structures(data: bytes):
    out, i = [], 0
    while i < len(data):
        ln = data[i]
        if ln == 0 or i + 1 + ln > len(data):
            break
        out.append((data[i + 1], data[i + 2:i + 1 + ln]))
        i += 1 + ln
    return out

def hci_events(path):
    """Advertising reports and connection completes.

    Note on iOS: Apple routes LE scan results through vendor-specific events
    (0xFF), not the standard advertising-report subevents, so ``adverts`` is
    usually empty against an iPhone capture even when discovery plainly happened.
    Search the raw file for the service UUID (either byte order) to find them.
    """
    adverts, conns = {}, []
    for ts, rtype, pl in records(path):
        if rtype != 0x01 or len(pl) < 2:
            continue
        code, _ln = pl[0], pl[1]
        if code != 0x3E or len(pl) < 3:
            continue
        sub, body = pl[2], pl[3:]
        if sub == 0x02 and body:                      # LE Advertising Report
            n = body[0]
            off = 1
            for _ in range(n):
                if off + 9 > len(body):
                    break
                etype = body[off]
                addr = body[off + 2:off + 8][::-1]
                dlen = body[off + 8]
                data = body[off + 9:off + 9 + dlen]
                rssi = struct.unpack_from("<b", body, off + 9 + dlen)[0] if off + 9 + dlen < len(body) else 0
                key = addr.hex(":")
                if PROV_SVC in data or PROV_SVC_LE in data or b"LitterRobot" in data:
                    adverts.setdefault(key, []).append((ts, etype, data, rssi))
                off += 10 + dlen
        elif sub == 0x01 and len(body) >= 11:         # LE Connection Complete
            conns.append((ts, body[0], struct.unpack_from("<H", body, 1)[0],
                          body[5:11][::-1].hex(":")))
        elif sub == 0x0A and len(body) >= 11:        # LE ENHANCED Connection Complete
            # What iOS actually emits. The legacy form above is kept for captures
            # from other stacks; a decoder that only knows 0x01 reports no
            # connections at all against an iPhone trace.
            conns.append((ts, body[0], struct.unpack_from("<H", body, 1)[0],
                          body[5:11][::-1].hex(":")))
    return adverts, conns

def att_pdus(path):
    """(ts, conn_handle, direction, pdu) for every reassembled ATT PDU.

    Reassembly state is keyed by (handle, direction): the two directions
    fragment independently and interleave freely, so a single per-handle buffer
    loses whichever side was mid-reassembly when the other one started.
    """
    pending, want = defaultdict(bytes), {}
    for ts, rtype, pl in records(path):
        if rtype not in (0x02, 0x03) or len(pl) < 4:
            continue
        hdr, plen = struct.unpack_from("<HH", pl, 0)
        h, pb = hdr & 0x0FFF, (hdr >> 12) & 0x3
        d = "TX" if rtype == 0x02 else "RX"
        key = (h, d)
        body = pl[4:4 + plen]
        # iOS sends host -> controller with PB=0b00 and receives 0b10; both start.
        if pb in (0x0, 0x2):
            if len(body) < 4:
                continue
            l2len, cid = struct.unpack_from("<HH", body, 0)
            if cid != 0x0004:
                pending.pop(key, None)
                want.pop(key, None)
                continue
            pending[key], want[key] = body[4:], l2len
        elif pb == 0x1 and key in pending:
            pending[key] += body
        else:
            continue
        if key in want and len(pending[key]) >= want[key]:
            yield ts, h, d, pending.pop(key)[:want.pop(key)]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} <capture.pklg> [...]")
    for path in sys.argv[1:]:
        print(f"=== {path} ===")
        adverts, conns = hci_events(path)
        for addr, reports in adverts.items():
            print(f"  advertised by {addr}: {len(reports)} report(s)")
        for ts, status, handle, peer in conns:
            print(f"  {t(ts)} connect handle={handle:#06x} peer={peer} status={status}")
        pdus = 0
        for _ts, _conn, _d, _pdu in att_pdus(path):
            pdus += 1
        print(f"  {pdus} reassembled ATT PDUs")
