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

from dataclasses import dataclass
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


def wifi_get_status() -> bytes:
    """WiFiConfigPayload CmdGetStatus (msg=0) — ask for the STA join verdict."""
    # msg=0 is the proto3 default and stays off the wire; the empty arm alone
    # (field 10) selects the command.
    return field_message(10, b"")


# --- prov-scan (stock esp-idf wifi_scan.proto) -------------------------------
# Confirmed against a captured Whisker-app onboarding: the app scans this way and
# pages the results four at a time. See
# docs/devices/litter-robot-4/provisioning/app-onboarding-capture.md.
def wifi_scan_start(
    *, blocking: bool = True, passive: bool = False,
    group_channels: int = 5, period_ms: int = 120,
) -> bytes:
    """WiFiScanPayload CmdScanStart (msg=0) — make the ROBOT scan.

    The defaults are the app's own: scan in groups of 5 channels, 120 ms each.
    Whisker picked them against this hardware, and a scan that is too brisk
    simply misses networks, so they are worth copying rather than improving on.
    """
    inner = (
        field_varint(1, int(blocking))
        + field_varint(2, int(passive))
        + field_varint(3, group_channels)
        + field_varint(4, period_ms)
    )
    return field_message(10, inner)


def wifi_scan_status() -> bytes:
    """WiFiScanPayload CmdScanStatus (msg=2) — has the scan finished?"""
    return field_varint(1, 2) + field_message(12, b"")


def wifi_scan_result(start_index: int, count: int) -> bytes:
    """WiFiScanPayload CmdScanResult (msg=4) — fetch one page of results."""
    inner = field_varint(1, start_index) + field_varint(2, count)
    return field_varint(1, 4) + field_message(14, inner)


@dataclass(frozen=True, slots=True)
class WifiNetwork:
    """One access point the robot can see."""

    ssid: str
    channel: int
    rssi: int
    #: True when the AP advertises any authentication (auth mode != OPEN).
    secured: bool

    @property
    def display(self) -> str:
        """The SSID with control characters escaped, for printing.

        An SSID is arbitrary bytes chosen by whoever runs the access point, and
        valid UTF-8 can still carry newlines and ANSI escapes. Printed raw into a
        chooser list, a nearby AP could forge rows or drive the terminal. The real
        SSID is what gets provisioned; this is only what a human is shown.
        """
        return "".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in self.ssid)

    @property
    def bars(self) -> int:
        """RSSI as 1-4 bars, for showing a list a human can choose from."""
        for floor, bars in ((-60, 4), (-70, 3), (-80, 2)):
            if self.rssi >= floor:
                return bars
        return 1


class WifiStationState(IntEnum):
    """esp-idf ``WifiStationState`` — the STA's answer to GetStatus."""

    CONNECTED = 0
    CONNECTING = 1
    DISCONNECTED = 2
    CONNECTION_FAILED = 3


class WifiConnectFailedReason(IntEnum):
    """esp-idf ``WifiConnectFailedReason`` — why a join gave up."""

    AUTH_ERROR = 0
    NETWORK_NOT_FOUND = 1


@dataclass(frozen=True, slots=True)
class WifiStatus:
    """A decoded RespGetStatus from the stock WiFi provisioning endpoint."""

    state: WifiStationState
    fail_reason: WifiConnectFailedReason | None = None
    ip4: str | None = None


# --- response parsers --------------------------------------------------------
def parse_status(response: bytes) -> int:
    """Top-level protocomm ``status`` (field 2); absent → Success (0)."""
    if not response:
        return 0
    values = read_fields(response).get(2)
    return int(values[0]) if values and isinstance(values[0], int) else 0


def parse_wifi_status(response: bytes) -> WifiStatus | None:
    """Decode a prov-config RespGetStatus (arm 11); ``None`` if it isn't one.

    The verdict lives in the response's oneof: ``connected`` (field 11, carries
    the STA's IP) or ``fail_reason`` (field 10 — emitted even for its zero value
    AuthError, because oneof presence is explicit). ``sta_state`` (field 2)
    alone cannot prove success: its zero value *is* Connected, which proto3
    omits, so an empty status is ambiguous — with neither oneof arm present,
    only the explicit intermediate states (connecting/disconnected/failed) are
    reported and anything else reads as "no verdict yet".
    """
    if not response:
        return None
    arm = read_fields(response).get(11)
    if not arm or not isinstance(arm[0], bytes):
        return None
    fields = read_fields(arm[0])
    connected = fields.get(11)
    if connected and isinstance(connected[0], bytes):
        ip_values = read_fields(connected[0]).get(1)
        ip4 = None
        if ip_values and isinstance(ip_values[0], bytes):
            ip4 = ip_values[0].decode("utf-8", "replace") or None
        return WifiStatus(WifiStationState.CONNECTED, ip4=ip4)
    fail = fields.get(10)
    if fail and isinstance(fail[0], int):
        try:
            reason: WifiConnectFailedReason | None = WifiConnectFailedReason(fail[0])
        except ValueError:
            reason = None
        return WifiStatus(WifiStationState.CONNECTION_FAILED, fail_reason=reason)
    sta = fields.get(2)
    if sta and isinstance(sta[0], int) and sta[0] in (1, 2, 3):
        return WifiStatus(WifiStationState(sta[0]))
    return None


def parse_scan_status(response: bytes) -> tuple[bool, int] | None:
    """Decode RespScanStatus (arm 13) into ``(finished, result_count)``."""
    if not response:
        return None
    arm = read_fields(response).get(13)
    if not arm or not isinstance(arm[0], bytes):
        return None
    fields = read_fields(arm[0])
    finished = fields.get(1)
    count = fields.get(2)
    return (
        bool(finished[0]) if finished and isinstance(finished[0], int) else False,
        int(count[0]) if count and isinstance(count[0], int) else 0,
    )


def parse_scan_results(response: bytes) -> list[WifiNetwork]:
    """Decode one RespScanResult page (arm 15) into networks.

    Entries with an unreadable or empty SSID are dropped rather than surfaced: a
    hidden network cannot be chosen from a list by name anyway, and the field is
    raw bytes that need not be valid UTF-8.
    """
    if not response:
        return []
    arm = read_fields(response).get(15)
    if not arm or not isinstance(arm[0], bytes):
        return []
    found = []
    for entry in read_fields(arm[0]).get(1, []):
        if not isinstance(entry, bytes):
            continue
        fields = read_fields(entry)
        raw = fields.get(1)
        if not raw or not isinstance(raw[0], bytes):
            continue
        try:
            ssid = raw[0].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not ssid:
            continue
        channel = fields.get(2)
        rssi = fields.get(3)
        auth = fields.get(5)
        # RSSI is an int32 sign-extended into a varint, so a negative arrives as
        # a huge unsigned value; fold it back rather than reporting +18446744073709551565 dBm.
        raw_rssi = int(rssi[0]) if rssi and isinstance(rssi[0], int) else 0
        if raw_rssi >= 1 << 63:
            raw_rssi -= 1 << 64
        found.append(
            WifiNetwork(
                ssid=ssid,
                channel=int(channel[0]) if channel and isinstance(channel[0], int) else 0,
                rssi=raw_rssi,
                # proto3 omits the zero default, and auth mode 0 IS "open" — so an
                # absent field means an open network, not an unknown one. Defaulting
                # to secured would put a lock beside every open AP in the list.
                secured=bool(auth[0]) if auth and isinstance(auth[0], int) else False,
            )
        )
    return found


def parse_device_id(response: bytes) -> bytes | None:
    """Extract device_id bytes from a DEVICE_ID_RESPONSE (arm 11, field 1)."""
    arm = read_fields(response).get(11)
    if not arm or not isinstance(arm[0], bytes):
        return None
    inner = read_fields(arm[0]).get(1)
    return inner[0] if inner and isinstance(inner[0], bytes) else None
