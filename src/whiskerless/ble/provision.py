"""High-level BLE re-provisioning flow for the Litter-Robot 4.

Replicates the official Whisker app's exact onboarding sequence, substituting
only the broker host (your broker's IP) and the trusted root CA (your CA). The
factory device cert/key are left untouched, so the change is fully reversible by
re-onboarding through the Whisker app.

The WiFi SetConfig+Apply finalize is load-bearing: every attempt that skipped it
wedged the robot (the topic globals are only populated when the provisioning
state machine finalizes). The proven order is:

    DEVICE_ID_SET → WiFi SetConfig+Apply → wait → endpoints → CA → APPLY → REBOOT
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..exceptions import ProvisioningError
from . import messages as m
from .messages import PROV_SERVICE_UUID
from .transport import ProtocommBLE, translated

if TYPE_CHECKING:
    from bleak import BleakClient

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class ProvisioningConfig:
    """Inputs for one robot's re-provisioning."""

    serial: str
    host: str
    ca_pem: str
    wifi_ssid: str = ""
    wifi_pass: str = ""
    command_topic: str | None = None
    device_topic: str | None = None
    swap_topics: bool = False
    write_wifi: bool = True
    wifi_wait: float = 12.0
    chunk_size: int | None = None
    reboot: bool = True

    def __post_init__(self) -> None:
        self.serial = self.check_serial(self.serial)

    @staticmethod
    def check_serial(value: str) -> str:
        """Normalize a typed serial, or explain why it cannot be one.

        The serial becomes the MQTT client-id and both topic segments, so a wrong
        value provisions cleanly and then never appears on the broker — there is
        no error to see. It is worth rejecting early.

        The shape rule is deliberately loose: only two units have ever been seen
        here, both ``LR4C`` + six digits, which is far too small a sample to
        insist on. Requiring some length and some digits is enough to reject the
        model designator printed beside the serial on the same label, which is
        the mistake this actually catches.
        """
        serial = value.strip().upper()
        if not serial.startswith("LR4"):
            raise ProvisioningError(
                f"serial {serial!r} is not a Litter-Robot 4 serial "
                "(expected LR4…, e.g. LR4C123456) — this provisioner only supports the LR4"
            )
        # The hyphen test is what actually catches the label's other line: the
        # designator (LR4-0301-00-US) is long enough and carries enough digits
        # to pass the shape checks below.
        if "-" in serial or len(serial) < 8 or sum(character.isdigit() for character in serial) < 4:
            raise ProvisioningError(
                f"serial {serial!r} looks like the model number, not the serial — the serial is "
                "the longer line, LR4 followed by a letter and six digits (e.g. LR4C123456)"
            )
        return serial

    def resolved_command_topic(self) -> str:
        return self.command_topic or f"prod/LR4/{self.serial}/command"

    def resolved_device_topic(self) -> str:
        # The app points the device (publish) endpoint at /activity; the firmware
        # derives the /state sub-topic from it.
        return self.device_topic or f"prod/LR4/{self.serial}/activity"


@dataclass(slots=True)
class ProvisioningResult:
    success: bool
    device_mac: str | None = None
    steps: list[str] = field(default_factory=list)
    message: str = ""


def _assert_lr4(client: BleakClient) -> None:
    """Refuse any connected device that lacks the LR4 provisioning GATT service.

    Guards the ``--address`` path (which accepts an arbitrary BLE address) and any
    other Whisker model: writing LR4 topics/config onto a different device is
    never safe, so fail before touching an endpoint.
    """
    uuids = {service.uuid.lower() for service in client.services}
    if PROV_SERVICE_UUID not in uuids:
        raise ProvisioningError(
            f"device at {client.address} does not expose the LR4 provisioning service "
            f"({PROV_SERVICE_UUID}) — not a Litter-Robot 4; refusing to provision"
        )


async def read_device_mac(address: str, *, scan_timeout: float = 15.0) -> str | None:
    """Read-only preflight — connect and return the robot's 6-byte MAC."""
    from bleak import BleakClient  # lazy: bleak is the [ble] extra

    async with translated(f"could not read the device id at {address}"), BleakClient(address) as client:
        _assert_lr4(client)
        transport = ProtocommBLE(client)
        await transport.discover_endpoints()
        response = await transport.request(m.EP_WHISKER, m.whisker_device_id_request())
        return _format_mac(m.parse_device_id(response))


async def provision_robot(
    address: str,
    config: ProvisioningConfig,
    *,
    dry_run: bool = False,
    on_step: ProgressCallback | None = None,
) -> ProvisioningResult:
    """Re-provision the robot at BLE ``address`` onto your broker."""
    from bleak import BleakClient  # lazy: bleak is the [ble] extra

    if "BEGIN CERTIFICATE" not in config.ca_pem:
        raise ProvisioningError("ca_pem does not look like a PEM certificate")

    result = ProvisioningResult(success=False)

    def step(message: str) -> None:
        # A dry run performs no GATT writes at all, so past-tense lines
        # ("CERT_AWS_ROOT_CERT written") would describe a robot that was never
        # touched — and anyone who scrolls up, or whose terminal truncates, could
        # not tell a simulation from the real thing. Only what a human reads is
        # marked; `steps` stays clean because callers match against it.
        result.steps.append(message)
        shown = f"[dry-run] {message}" if dry_run else message
        log.info("%s", shown)
        if on_step:
            on_step(shown)

    async with translated(f"BLE connection to {address} failed"), BleakClient(address) as client:
        _assert_lr4(client)
        mtu = getattr(client, "mtu_size", 0) or 0
        chunk_size = config.chunk_size or max(64, mtu - 40)
        step(f"connected to {address} (MTU={mtu or '?'}, cert chunk={chunk_size})")

        transport = ProtocommBLE(client, dry_run=dry_run)
        endpoints = await transport.discover_endpoints()
        step(f"endpoints: {sorted(endpoints)}")
        for required in (m.EP_MQTT, m.EP_WHISKER):
            if required not in endpoints:
                raise ProvisioningError(f"required endpoint {required!r} not found on device")

        result.device_mac = _format_mac(
            m.parse_device_id(await transport.request(m.EP_WHISKER, m.whisker_device_id_request()))
        )
        # A dry run short-circuits the GATT read, so there is genuinely nothing to
        # report — but a bare "None" reads like the robot failed to answer.
        step(f"device MAC: {result.device_mac or ('not read (dry-run)' if dry_run else 'unknown')}")

        # 1. client-id = serial (must precede the WiFi finalize).
        await _whisker(transport, m.whisker_device_id_set(config.serial), "DEVICE_ID_SET", dry_run)
        step(f"DEVICE_ID_SET {config.serial}")

        # 2. WiFi finalize — the decisive step.
        if config.write_wifi:
            if not config.wifi_ssid:
                raise ProvisioningError("wifi_ssid is required (or set write_wifi=False)")
            await transport.request(m.EP_PROV_CONFIG, m.wifi_set_config(config.wifi_ssid, config.wifi_pass))
            await transport.request(m.EP_PROV_CONFIG, m.wifi_apply_config())
            step(f"WiFi SetConfig+Apply ssid={config.wifi_ssid}; waiting {config.wifi_wait:.0f}s")
            if not dry_run:
                await asyncio.sleep(config.wifi_wait)

        # 3. endpoints — CLOUD=subscribe(cmd), DEVICE=publish(state/activity).
        cloud_value = config.resolved_command_topic()
        device_value = config.resolved_device_topic()
        if config.swap_topics:
            cloud_value, device_value = device_value, cloud_value
        await _mqtt(transport, m.mqtt_endpoint_write(m.EndpointType.HOST, config.host), "ENDPOINT_HOST", dry_run)
        await _mqtt(transport, m.mqtt_endpoint_write(m.EndpointType.CLOUD_ENDPOINT, cloud_value), "ENDPOINT_CLOUD", dry_run)
        await _mqtt(transport, m.mqtt_endpoint_write(m.EndpointType.DEVICE_ENDPOINT, device_value), "ENDPOINT_DEVICE", dry_run)
        step(f"endpoints: host={config.host} sub={cloud_value} pub={device_value}")

        # 4. our CA into the root-CA slot (device cert/key untouched).
        await _write_cert(transport, config.ca_pem, chunk_size, dry_run)
        step(f"CERT_AWS_ROOT_CERT written ({len(config.ca_pem.encode())} bytes)")

        # 5. commit, then reboot.
        await _mqtt(transport, m.mqtt_apply_config(), "APPLY_CONFIG", dry_run)
        step("APPLY_CONFIG committed")

        if dry_run:
            result.message = "dry-run: no bytes written"
            return result

        if config.reboot:
            try:
                await transport.request(m.EP_WHISKER, m.whisker_reboot())
            except Exception as exc:  # noqa: BLE001 — link loss on reboot is expected
                log.debug("reboot returned no clean response (expected): %s", exc)
            step("DEVICE_REBOOT")

    result.success = True
    result.message = f"reprovisioned; the robot should reconnect MQTT to {config.host}"
    return result


async def _write_cert(transport: ProtocommBLE, pem: str, chunk_size: int, dry_run: bool) -> None:
    total = len(pem.encode("utf-8"))
    offset = 0
    while offset < total:
        piece = pem[offset : offset + chunk_size]
        request = m.mqtt_cert_write(
            m.CertificateType.CERT_AWS_ROOT_CERT,
            piece,
            total_size=total,
            offset=offset,
            size=len(piece.encode("utf-8")),
        )
        await _mqtt(transport, request, f"CERT_WRITE[{offset}]", dry_run)
        offset += len(piece)


async def _mqtt(transport: ProtocommBLE, payload: bytes, label: str, dry_run: bool) -> None:
    response = await transport.request(m.EP_MQTT, payload)
    if not dry_run and (status := m.parse_status(response)) != 0:
        raise ProvisioningError(f"{label} failed: status={status}")


async def _whisker(transport: ProtocommBLE, payload: bytes, label: str, dry_run: bool) -> None:
    response = await transport.request(m.EP_WHISKER, payload)
    if not dry_run and (status := m.parse_status(response)) != 0:
        log.warning("%s returned status=%s", label, status)


def _format_mac(device_id: bytes | None) -> str | None:
    if device_id is None:
        return None
    if len(device_id) == 6:
        return device_id.hex(":")
    return device_id.decode("utf-8", "replace").strip("\x00").strip() or None
