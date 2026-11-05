"""Extract a robot's Whisker cloud identity from a capture of the app's BLE onboarding.

The Whisker app writes the robot's cloud identity over BLE protocomm with no
encryption (``no_sec``): the AWS root CA, the device certificate and the device
private key, in chunks, plus the cloud host and the two topic endpoints. This
reads an iOS PacketLogger or Android BTSnoop capture of that session and writes
the identity where the cloud bridge reads it:

    OUT_DIR/root_ca.pem   OUT_DIR/device.crt   OUT_DIR/device.key   (mode 0600)
    OUT_DIR/summary.json  (host, topics, serial: nothing secret)

It prints only facts that are not secret: host, topics, serial, and each file's
length and first line. Works for every robot whose protocomm service follows the
``XXXX000N-…`` characteristic scheme (the Litter-Robot 4 and the Litter-Robot EVO).

usage: python scripts/cloud_identity.py CAPTURE OUT_DIR
"""
from __future__ import annotations

import json
import os
import pathlib
import struct
import sys
from collections import defaultdict

from session import att_pdus

#: Protocomm services: the first two bytes of the service UUID and its last twelve.
#: Characteristic N of a service is the same UUID with bytes 2-3 set to 000N.
SERVICES = {
    "Litter-Robot 4": (b"\xb7\xee", bytes.fromhex("dcfd4208881314845cac5212")),
    "Litter-Robot EVO": (b"\x28\xcb", bytes.fromhex("6c8c43c488ee4da18ca98510")),
}
ENDPOINTS = {1: "prov-session", 2: "prov-config", 3: "proto-ver",
             4: "prov-scan", 5: "mqtt-config", 6: "whisker-config"}
CERT_FILES = {1: "root_ca.pem", 2: "device.crt", 3: "device.key"}
ENDPOINT_TYPES = {1: "cloud_endpoint", 2: "device_endpoint", 3: "host"}

# Field numbers from whisker_mqtt_config.proto / whisker_config.proto.
MQTT_CERT_WRITE, MQTT_ENDPOINT_WRITE = 10, 12
CONFIG_DEVICE_ID_SET = 14


def varint(buf, i):
    out = shift = 0
    while True:
        b = buf[i]
        i += 1
        out |= (b & 0x7F) << shift
        if not b & 0x80:
            return out, i
        shift += 7


def fields(buf):
    """Decode one protobuf message into {field: [values]}; raises on malformed input."""
    out, i = defaultdict(list), 0
    while i < len(buf):
        tag, i = varint(buf, i)
        num, wt = tag >> 3, tag & 7
        if num == 0:
            raise ValueError("field 0")
        if wt == 0:
            v, i = varint(buf, i)
        elif wt == 2:
            ln, i = varint(buf, i)
            if i + ln > len(buf):
                raise ValueError("overrun")
            v, i = buf[i:i + ln], i + ln
        elif wt == 5:
            v, i = buf[i:i + 4], i + 4
        elif wt == 1:
            v, i = buf[i:i + 8], i + 8
        else:
            raise ValueError(f"wire type {wt}")
        out[num].append(v)
    return out


def handle_map(path):
    """Value handle -> (robot, endpoint), from Read By Type responses (characteristic declarations)."""
    out = {}
    for _ts, _conn, d, pdu in att_pdus(path):
        if d != "RX" or len(pdu) < 2 or pdu[0] != 0x09 or pdu[1] != 21:
            continue
        for i in range(2, len(pdu) - 20, 21):
            value_handle = struct.unpack_from("<H", pdu, i + 3)[0]
            uuid = pdu[i + 5:i + 21][::-1]
            for robot, (head, tail) in SERVICES.items():
                if uuid[:2] == head and uuid[4:] == tail and uuid[2] == 0:
                    out[value_handle] = (robot, ENDPOINTS.get(uuid[3], f"endpoint {uuid[3]}"))
    return out


def writes(path):
    """(value_handle, value) for every client write, prepared writes assembled."""
    queued = defaultdict(list)
    for _ts, _conn, d, pdu in att_pdus(path):
        if d != "TX" or not pdu:
            continue
        op = pdu[0]
        if op in (0x12, 0x52) and len(pdu) >= 3:      # Write Request / Write Command
            yield struct.unpack_from("<H", pdu, 1)[0], pdu[3:]
        elif op == 0x16 and len(pdu) >= 5:            # Prepare Write Request
            h, off = struct.unpack_from("<HH", pdu, 1)
            queued[h].append((off, pdu[5:]))
        elif op == 0x18 and len(pdu) >= 2:            # Execute Write Request
            if pdu[1] == 0x01:
                for h, parts in queued.items():
                    buf = bytearray()
                    for off, chunk in sorted(parts):
                        buf[off:off + len(chunk)] = chunk
                    yield h, bytes(buf)
            queued.clear()


def extract(path):
    """Decode the capture into (certs, endpoints, serial, robots seen)."""
    handles = handle_map(path)
    certs, endpoints, serial = {}, {}, None
    for h, value in writes(path):
        _robot, endpoint = handles.get(h, (None, None))
        try:
            msg = fields(value)
        except (ValueError, IndexError):
            continue
        # Without a handle map (a capture that missed discovery), recognize by shape.
        if endpoint in (None, "mqtt-config") and MQTT_CERT_WRITE in msg:
            req = fields(msg[MQTT_CERT_WRITE][0])
            ctype, chunk = req.get(1, [0])[0], req.get(2, [b""])[0]
            total, offset = req.get(3, [0])[0], req.get(4, [0])[0]
            if ctype in CERT_FILES and total:
                slot = certs.get(ctype)
                if slot is None or slot["total"] != total:  # a later onboarding pass restarts the slot
                    slot = certs[ctype] = {"total": total, "buf": bytearray(total)}
                slot["buf"][offset:offset + len(chunk)] = chunk
        elif endpoint in (None, "mqtt-config") and MQTT_ENDPOINT_WRITE in msg:
            req = fields(msg[MQTT_ENDPOINT_WRITE][0])
            if req.get(1, [0])[0] in ENDPOINT_TYPES:
                endpoints[ENDPOINT_TYPES[req[1][0]]] = req.get(2, [b""])[0].decode(errors="replace")
        elif endpoint == "whisker-config" and CONFIG_DEVICE_ID_SET in msg:
            inner = fields(msg[CONFIG_DEVICE_ID_SET][0])
            serial = inner.get(1, [b""])[0].decode(errors="replace") or serial
    return certs, endpoints, serial, sorted({robot for robot, _ in handles.values()})


def write_secret(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def main(argv):
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <capture.pklg or btsnoop_hci.log> <out-dir>")
    certs, endpoints, serial, robots = extract(argv[1])
    out = pathlib.Path(argv[2])
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    print("robot:", ", ".join(robots) or "unknown (no service discovery in the capture)")
    print("serial:", serial or "not seen")
    for name, value in sorted(endpoints.items()):
        print(f"{name}: {value}")
    missing = [name for ctype, name in CERT_FILES.items() if ctype not in certs]
    for ctype, slot in sorted(certs.items()):
        data = bytes(slot["buf"]).rstrip(b"\0")
        write_secret(out / CERT_FILES[ctype], data)
        first = data.split(b"\n", 1)[0].decode(errors="replace")
        print(f"{CERT_FILES[ctype]}: {len(data)} of {slot['total']} bytes, {first}")
    summary = {"serial": serial, **endpoints}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    if missing:
        print("missing:", ", ".join(missing), "(was the whole onboarding captured?)")
        return 1
    print("the capture holds the Wi-Fi passphrase and this private key: delete it now")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
