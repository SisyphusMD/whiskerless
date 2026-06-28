"""BLE protocomm frames — byte-exact against the captured Whisker-app traffic."""

from __future__ import annotations

from whiskerless.ble import messages as m


def test_wifi_set_config_matches_app_frame() -> None:
    # Captured app frame: 08 02 62 <len> 0a <ssidlen> <ssid> 12 <passlen> <pass>.
    ssid, password = "ExampleSSID_24", "passwordXXyy"  # 14-char ssid, 12-char pass
    expected = "0802621e0a0e" + ssid.encode().hex() + "120c" + password.encode().hex()
    assert m.wifi_set_config(ssid, password).hex() == expected


def test_wifi_apply_config_matches_app_frame() -> None:
    assert m.wifi_apply_config().hex() == "0804"


def test_proto3_defaults_omitted() -> None:
    # CERT_WRITE has msg=0 (the default) which proto3 omits → starts at arm 10 (0x52).
    cert = m.mqtt_cert_write(m.CertificateType.CERT_AWS_ROOT_CERT, "X", 1, 0, 1)
    assert cert[:1].hex() == "52"
    # Empty oneof arms are still emitted (tag + len 0) so the device sees the arm.
    assert m.mqtt_apply_config().hex() == "08047200"
    assert m.whisker_device_id_request().hex() == "08015200"
    assert m.whisker_reboot().hex() == "08036200"


def test_device_id_set_frame() -> None:
    serial = "LR4C000001"
    expected = "0805" + "72" + format(2 + len(serial), "02x") + "0a" + format(len(serial), "02x") + serial.encode().hex()
    assert m.whisker_device_id_set(serial).hex() == expected


def test_parse_status_absent_is_success() -> None:
    assert m.parse_status(b"") == 0
    assert m.parse_status(m.mqtt_apply_config()) == 0  # no status field on a request


def test_parse_status_reads_field2() -> None:
    # status=4 (InvalidArgument): field 2 varint -> tag 0x10, value 0x04.
    assert m.parse_status(bytes([0x10, 0x04])) == 4


def test_parse_device_id_roundtrip() -> None:
    mac = bytes.fromhex("b48a0a8ac928")
    # Build a DEVICE_ID_RESPONSE: msg=2, arm 11 { field1 (bytes) = mac }.
    from whiskerless.ble.protobuf import field_message, field_varint

    inner = bytes([0x0A, len(mac)]) + mac  # field 1, LEN
    response = field_varint(1, 2) + field_message(11, inner)
    assert m.parse_device_id(response) == mac
