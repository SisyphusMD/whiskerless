"""The capture scripts: both phone formats feed the same onboarding decoder.

Every capture here is synthetic, built byte by byte: an onboarding of a
Litter-Robot EVO with a made-up serial and placeholder PEM text, no real
identity.
"""

from __future__ import annotations

import json
import stat
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import btsnoop
import capture
import cloud_identity

SERIAL = "LRE-01-40-01-2610-000000"  # synthetic
CONN = 0x0040
CA_PEM = b"-----BEGIN CERTIFICATE-----\nU1lOVEhFVElDIENB\n-----END CERTIFICATE-----\n"
CERT_PEM = b"-----BEGIN CERTIFICATE-----\nU1lOVEhFVElDIERFVklDRQ==\n-----END CERTIFICATE-----\n"
KEY_PEM = b"-----BEGIN RSA PRIVATE KEY-----\nU1lOVEhFVElDIEtFWQ==\n-----END RSA PRIVATE KEY-----\n"


# --- protobuf and ATT building blocks ----------------------------------------


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return _varint(num << 3) + _varint(value)
    return _varint(num << 3 | 2) + _varint(len(value)) + value


def _cert_write(ctype: int, total: int, offset: int, chunk: bytes) -> bytes:
    req = _field(1, ctype) + _field(2, chunk) + _field(3, total) + _field(4, offset) + _field(5, len(chunk))
    return _field(1, 0) + _field(10, req)


def _endpoint_write(etype: int, value: str) -> bytes:
    return _field(1, 2) + _field(12, _field(1, etype) + _field(2, value.encode()))


def _uuid_le(endpoint: int) -> bytes:
    return bytes.fromhex(f"28cb{endpoint:04x}6c8c43c488ee4da18ca98510")[::-1]


def _read_by_type_response(*pairs: tuple[int, int]) -> bytes:
    entries = b"".join(struct.pack("<HBH", handle - 1, 0x0A, handle) + _uuid_le(ep) for handle, ep in pairs)
    return bytes([0x09, 21]) + entries


def _acl(att: bytes, *, received: bool) -> bytes:
    pb = 0x2 if received else 0x0
    l2cap = struct.pack("<HH", len(att), 0x0004) + att
    return struct.pack("<HH", CONN | pb << 12, len(l2cap)) + l2cap


def _onboarding() -> list[tuple[bool, bytes]]:
    """(received, ATT PDU) for a whole synthetic onboarding."""
    mqtt, config = 0x0036, 0x0039
    key_half = len(KEY_PEM) // 2
    pdus = [
        (True, _read_by_type_response((mqtt, 5), (config, 6))),
        (False, bytes([0x12]) + struct.pack("<H", config) + _field(1, 5) + _field(14, _field(1, SERIAL.encode()))),
        (False, bytes([0x12]) + struct.pack("<H", mqtt) + _endpoint_write(3, "iot.invalid")),
        (False, bytes([0x12]) + struct.pack("<H", mqtt) + _endpoint_write(1, f"prod/robots/{SERIAL}/command")),
        (False, bytes([0x12]) + struct.pack("<H", mqtt) + _endpoint_write(2, f"prod/robots/{SERIAL}/activity")),
        (False, bytes([0x12]) + struct.pack("<H", mqtt) + _cert_write(1, len(CA_PEM), 0, CA_PEM)),
        (False, bytes([0x12]) + struct.pack("<H", mqtt) + _cert_write(2, len(CERT_PEM), 0, CERT_PEM)),
        (False, bytes([0x12]) + struct.pack("<H", mqtt) + _cert_write(3, len(KEY_PEM), 0, KEY_PEM[:key_half])),
    ]
    # The second half of the key travels as a prepared write split in two, then executed.
    long_value = _cert_write(3, len(KEY_PEM), key_half, KEY_PEM[key_half:])
    split = len(long_value) // 2
    pdus += [
        (False, bytes([0x16]) + struct.pack("<HH", mqtt, 0) + long_value[:split]),
        (False, bytes([0x16]) + struct.pack("<HH", mqtt, split) + long_value[split:]),
        (False, bytes([0x18, 0x01])),
        (False, bytes([0x12]) + struct.pack("<H", mqtt) + b"\xff\xff"),  # malformed: skipped
        (False, bytes([0x16]) + struct.pack("<HH", mqtt, 0) + b"cancelled"),
        (False, bytes([0x18, 0x00])),  # cancel: the queued write is dropped
    ]
    return pdus


def _pklg(path: Path) -> Path:
    blob = bytearray()
    for i, (received, att) in enumerate(_onboarding()):
        payload = _acl(att, received=received)
        rtype = 0x03 if received else 0x02
        blob += struct.pack(">IIIB", 9 + len(payload), 1_700_000_000 + i, 0, rtype) + payload
    path.write_bytes(bytes(blob))
    return path


def _btsnoop_header(datalink: int = btsnoop.DATALINK_H4) -> bytes:
    return btsnoop.MAGIC + struct.pack(">II", 1, datalink)


def _btsnoop_record(packet: bytes, flags: int, seconds: int) -> bytes:
    stamp = btsnoop.EPOCH_OFFSET_US + seconds * 1_000_000
    return struct.pack(">IIIIq", len(packet), len(packet), flags, 0, stamp) + packet


def _btsnoop(path: Path) -> Path:
    blob = bytearray(_btsnoop_header())
    for i, (received, att) in enumerate(_onboarding()):
        blob += _btsnoop_record(b"\x02" + _acl(att, received=received), int(received), 1_700_000_000 + i)
    path.write_bytes(bytes(blob))
    return path


# --- readers -----------------------------------------------------------------


def test_both_formats_yield_the_same_acl_records(tmp_path: Path) -> None:
    from_pklg = list(capture.records(_pklg(tmp_path / "a.pklg")))
    from_snoop = list(capture.records(_btsnoop(tmp_path / "b.log")))
    assert [(r[1], r[2]) for r in from_pklg] == [(r[1], r[2]) for r in from_snoop]
    assert from_snoop[0][0] == pytest.approx(1_700_000_000)
    assert {r[1] for r in from_snoop} == {0x02, 0x03}


def test_btsnoop_maps_h4_commands_and_events_and_skips_the_rest(tmp_path: Path) -> None:
    path = tmp_path / "h4.log"
    path.write_bytes(
        _btsnoop_header()
        + _btsnoop_record(b"\x01\x03\x0c\x00", 0x2, 1)   # HCI command
        + _btsnoop_record(b"\x04\x0e\x01\x00", 0x3, 2)   # HCI event
        + _btsnoop_record(b"\x03\x00", 0x0, 3)           # SCO: not decoded
        + _btsnoop_record(b"", 0x0, 4)                   # empty: skipped
        + struct.pack(">IIIIq", 50, 50, 0, 0, 0) + b"truncated"
    )
    assert [r[1] for r in btsnoop.records(path)] == [0x00, 0x01]


def test_btsnoop_reads_unencapsulated_hci(tmp_path: Path) -> None:
    path = tmp_path / "raw.log"
    path.write_bytes(
        _btsnoop_header(btsnoop.DATALINK_HCI)
        + _btsnoop_record(b"\x03\x0c\x00", 0x2, 1)  # command
        + _btsnoop_record(b"\x0e\x01\x00", 0x3, 2)  # event
        + _btsnoop_record(b"\x40\x00\x00\x00", 0x1, 3)  # received ACL
    )
    assert [r[1] for r in btsnoop.records(path)] == [0x00, 0x01, 0x03]


def test_btsnoop_refuses_other_files(tmp_path: Path) -> None:
    (tmp_path / "x").write_bytes(b"not a capture at all")
    with pytest.raises(ValueError, match="not a BTSnoop"):
        list(btsnoop.records(tmp_path / "x"))
    (tmp_path / "y").write_bytes(_btsnoop_header(datalink=1))
    with pytest.raises(ValueError, match="datalink"):
        list(btsnoop.records(tmp_path / "y"))


# --- the onboarding decoder --------------------------------------------------


@pytest.mark.parametrize("build", [_pklg, _btsnoop], ids=["pklg", "btsnoop"])
def test_identity_is_extracted_from_either_format(build, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "identity"
    assert cloud_identity.main(["cloud_identity.py", str(build(tmp_path / "capture")), str(out)]) == 0
    assert (out / "root_ca.pem").read_bytes() == CA_PEM
    assert (out / "device.crt").read_bytes() == CERT_PEM
    assert (out / "device.key").read_bytes() == KEY_PEM
    for name in ("root_ca.pem", "device.crt", "device.key"):
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o600
    summary = json.loads((out / "summary.json").read_text())
    assert summary == {
        "serial": SERIAL,
        "host": "iot.invalid",
        "cloud_endpoint": f"prod/robots/{SERIAL}/command",
        "device_endpoint": f"prod/robots/{SERIAL}/activity",
    }
    printed = capsys.readouterr().out
    assert "Litter-Robot EVO" in printed
    assert "U1lOVEhFVElDIEtFWQ" not in printed  # the key body is never printed


def test_a_partial_capture_reports_what_is_missing(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "partial.pklg"
    payload = _acl(bytes([0x12]) + struct.pack("<H", 0x0036) + _endpoint_write(3, "iot.invalid"), received=False)
    path.write_bytes(struct.pack(">IIIB", 9 + len(payload), 1, 0, 0x02) + payload)
    assert cloud_identity.main(["cloud_identity.py", str(path), str(tmp_path / "out")]) == 1
    printed = capsys.readouterr().out
    assert "unknown (no service discovery" in printed
    assert "missing: root_ca.pem, device.crt, device.key" in printed


def test_usage_is_explained() -> None:
    with pytest.raises(SystemExit, match="usage"):
        cloud_identity.main(["cloud_identity.py"])


@pytest.mark.parametrize("bad", [b"\x00", b"\x0b", b"\x0a\xff"])
def test_protobuf_decoder_rejects_malformed_input(bad: bytes) -> None:
    with pytest.raises((ValueError, IndexError)):
        cloud_identity.fields(bad)


def test_protobuf_decoder_reads_fixed_width_fields() -> None:
    decoded = cloud_identity.fields(b"\x0d\x01\x02\x03\x04\x11" + bytes(8))
    assert decoded[1] == [b"\x01\x02\x03\x04"] and decoded[2] == [bytes(8)]
