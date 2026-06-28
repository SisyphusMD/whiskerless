"""protocomm endpoint message builders + parsers (no BLE dependency).

Field numbers come from the firmware's protobuf-c descriptors; the WiFi
SetConfig/Apply frames are byte-identical to a captured Whisker-app session, and
the full mqtt-config/whisker-config sequence has re-provisioned a real robot
end-to-end. The exact oneof-arm tags and Certificate/Endpoint enum values are
high-confidence but worth re-checking if a future firmware changes the schema.
The endpoints:

* ``whisker-config`` — set/get the device id (serial), reboot.
* ``mqtt-config``   — write certs / endpoints, apply config.
* ``prov-config``   — stock esp-idf WiFi provisioning (SetConfig / ApplyConfig).
"""

from __future__ import annotations

from enum import IntEnum

from .protobuf import field_message, field_string, field_varint, read_fields

# --- protocomm endpoint names (from protocomm_add_endpoint) ------------------
EP_SESSION = "prov-session"
EP_PROV_CONFIG = "prov-config"
EP_PROV_SCAN = "prov-scan"
EP_PROTO_VER = "proto-ver"
EP_MQTT = "mqtt-config"
EP_WHISKER = "whisker-config"

# Intrinsic to every LR4's protocomm GATT service — the device-agnostic match
# (stable across robots/hosts/OSes; far more reliable than the weak advert name).
PROV_SERVICE_UUID = "b7ee1c20-dcfd-4208-8813-14845cac5212"
ADVERTISER_NAME = "LitterRobot4"


class CertificateType(IntEnum):
    CERT_AWS_ROOT_CERT = 1  # server-trust root CA — provision OUR CA here
    CERT_DEVICE_CERT = 2    # factory identity — do NOT touch
    CERT_DEVICE_KEY = 3     # factory identity — do NOT touch


class EndpointType(IntEnum):
    CLOUD_ENDPOINT = 1   # device SUBSCRIBES (command topic)
    DEVICE_ENDPOINT = 2  # device PUBLISHES (state/activity topic)
    HOST = 3             # broker host (TLS SNI / hostname-verify target)


# --- whisker-config ----------------------------------------------------------
def whisker_device_id_request() -> bytes:
    """DEVICE_ID_REQUEST (read-only preflight); returns the 6-byte MAC."""
    return field_varint(1, 1) + field_message(10, b"")


def whisker_device_id_set(serial: str) -> bytes:
    """DEVICE_ID_SET — sets the MQTT client-id to the device serial."""
    inner = field_string(1, serial)
    return field_varint(1, 5) + field_message(14, inner)


def whisker_reboot() -> bytes:
    """DEVICE_REBOOT."""
    return field_varint(1, 3) + field_message(12, b"")


# --- mqtt-config -------------------------------------------------------------
def mqtt_cert_write(
    cert_type: CertificateType,
    chunk: str,
    total_size: int,
    offset: int,
    size: int,
) -> bytes:
    """CERT_WRITE — one chunk of a credential (msg=0 is the proto3 default)."""
    inner = (
        field_varint(1, int(cert_type))
        + field_string(2, chunk)
        + field_varint(3, total_size)
        + field_varint(4, offset)
        + field_varint(5, size)
    )
    return field_varint(1, 0) + field_message(10, inner)


def mqtt_endpoint_write(endpoint_type: EndpointType, value: str) -> bytes:
    """ENDPOINT_WRITE — set a host/topic endpoint string."""
    inner = field_varint(1, int(endpoint_type)) + field_string(2, value)
    return field_varint(1, 2) + field_message(12, inner)


def mqtt_apply_config() -> bytes:
    """APPLY_CONFIG — commit staged certs + endpoints to NVS."""
    return field_varint(1, 4) + field_message(14, b"")


# --- prov-config (stock esp-idf WiFi provisioning) ---------------------------
def wifi_set_config(ssid: str, passphrase: str) -> bytes:
    """WiFiConfigPayload SetConfig (msg=2) with ssid/passphrase."""
    inner = field_string(1, ssid) + field_string(2, passphrase)
    return field_varint(1, 2) + field_message(12, inner)


def wifi_apply_config() -> bytes:
    """WiFiConfigPayload ApplyConfig (msg=4) — brings the STA up."""
    return field_varint(1, 4)


# --- response parsers --------------------------------------------------------
def parse_status(response: bytes) -> int:
    """Top-level protocomm ``status`` (field 2); absent → Success (0)."""
    if not response:
        return 0
    values = read_fields(response).get(2)
    return int(values[0]) if values and isinstance(values[0], int) else 0


def parse_device_id(response: bytes) -> bytes | None:
    """Extract device_id bytes from a DEVICE_ID_RESPONSE (arm 11, field 1)."""
    arm = read_fields(response).get(11)
    if not arm or not isinstance(arm[0], bytes):
        return None
    inner = read_fields(arm[0]).get(1)
    return inner[0] if inner and isinstance(inner[0], bytes) else None
