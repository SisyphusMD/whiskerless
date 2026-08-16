"""Async MQTT transport shared by the CLI and the Home Assistant integration.

Thin wrapper around :mod:`aiomqtt` that knows how to build the TLS context the
re-provisioned robot expects: server-cert verification against *our* CA, with an
option to skip hostname matching (needed when reaching the broker through a
port-forward / tunnel where the SNI no longer matches the cert SAN).
"""

from __future__ import annotations

import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path

import aiomqtt

DEFAULT_TLS_PORT = 8883


@dataclass(frozen=True, slots=True)
class MqttSettings:
    """Everything needed to open a connection to the robot's broker."""

    host: str
    port: int = DEFAULT_TLS_PORT
    tls: bool = True
    ca_cert_path: str | None = None
    ca_cert_data: str | None = None
    verify_hostname: bool = True
    # No username/password. The Litter-Robot cannot send credentials at all — its
    # firmware has no field for them — so the listener it connects to has to
    # authenticate by certificate. Rather than run two auth schemes against one
    # broker, whiskerless presents a client certificate like the robot does.
    client_cert_data: str | None = None
    client_key_data: str | None = None
    client_id: str | None = None
    keepalive: int = 60


def build_tls_context(settings: MqttSettings) -> ssl.SSLContext | None:
    """Build the SSL context for ``settings`` (or ``None`` for a plaintext link)."""
    if not settings.tls:
        return None
    if settings.ca_cert_data or settings.ca_cert_path:
        # Passing the CA to create_default_context skips load_default_certs, so
        # this context trusts ONLY the pinned CA — correct for a broker on your
        # own network, and it keeps the relaxation below off the system roots.
        # ca_cert_data wins when both are set, as it always has.
        context = ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH,
            cafile=(
                None
                if settings.ca_cert_data or settings.ca_cert_path is None
                else str(Path(settings.ca_cert_path))
            ),
            cadata=settings.ca_cert_data,
        )
        # Python 3.13+ enables VERIFY_X509_STRICT by default, which rejects a CA
        # lacking a keyUsage extension — including CAs built from this project's
        # own documented openssl recipe. That CA is written into the robot's
        # flash during BLE provisioning and cannot be rotated without a physical
        # bench visit, and the robot's own mbedTLS accepts it, so refusing here
        # strands the user with no remedy. Chain verification and hostname
        # checking both stay on.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    else:
        context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    # Our own client certificate, when there is one. A broker configured the way
    # this project now recommends runs `require_certificate true`, so the CLI has
    # to identify itself the same way the robot does. Loaded from memory via a
    # temporary file because ssl has no load_cert_chain-from-string: the key is
    # written 0600 and unlinked immediately, so it exists on disk only inside
    # this call.
    if settings.client_cert_data and settings.client_key_data:
        with tempfile.TemporaryDirectory() as scratch:
            pair = Path(scratch) / "client.pem"
            # Joined with an explicit newline: a PEM that arrived through .strip()
            # has no trailing one, and "-----END CERTIFICATE----------BEGIN" is
            # not parseable even though both halves are valid.
            pair.write_text(
                settings.client_cert_data.rstrip("\n") + "\n" + settings.client_key_data
            )
            pair.chmod(0o600)
            context.load_cert_chain(pair)
    # Hostname matching is optional because the robot's broker is often reached by
    # IP or through a port-forward; the CA check always stands.
    if not settings.verify_hostname:
        context.check_hostname = False
    return context


def create_client(settings: MqttSettings) -> aiomqtt.Client:
    """Construct (but do not connect) an :class:`aiomqtt.Client` for ``settings``."""
    return aiomqtt.Client(
        hostname=settings.host,
        port=settings.port,
        identifier=settings.client_id,
        tls_context=build_tls_context(settings),
        keepalive=settings.keepalive,
    )
