"""The small certificate authority whiskerless runs on your behalf.

Everything on this broker authenticates by certificate, because the robot has no
other option: its firmware has no field for a username or a password. That makes
a CA unavoidable, so whiskerless offers to be one rather than making a first-time
user learn ``openssl`` before their litter box works.

Three kinds of certificate come out of here, and they have different lifetimes:

* **The CA** — generated once, kept forever, in ``~/.whiskerless``. It signs
  everything else. Losing it does not break robots that are already running; it
  costs you the ability to add or re-provision one without visiting every robot
  to install a new CA. That is why it wants a backup.
* **The broker's server certificate** — so the robot can verify the broker it is
  told to trust. Regenerated freely: it is bound to a broker address, not to a
  robot, and nothing has to be re-provisioned when it changes.
* **A robot's client certificate** — minted at provisioning time, written to the
  robot, and then forgotten. Nothing keeps a copy, because nothing needs one: the
  robot holds it, the broker verifies it against the CA, and a replacement is one
  re-provision away. A stored copy would be a second place for a private key to
  leak from and no place it could be used.

RSA-2048 throughout, matching what the Whisker app writes and what the robot's
mbedTLS is known to accept. Not a preference — the app's own device key is
``BEGIN RSA PRIVATE KEY``, and this project does not guess at what firmware will
take.
"""

from __future__ import annotations

import contextlib
import datetime
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .exceptions import WhiskerlessError

#: Key size for everything issued here. See the module docstring.
KEY_BITS = 2048
#: X.509 caps a common name at 64 characters (X.520 ``ub-common-name``), and
#: ``cryptography`` enforces it by raising. A machine whose hostname is long
#: enough to pass it is not a reason for ``setup`` to die with a traceback —
#: the CN is a label for the broker's log, while hostname verification matches
#: against the SAN, which is not length-limited and always carries the full name.
CN_MAX = 64
#: The CA outlives the robots. Renewing it means re-provisioning every robot over
#: BLE, so a short life would buy nothing but bench visits.
CA_DAYS = 3650
#: Leaves match the CA rather than expiring sooner. A robot's certificate cannot
#: be renewed remotely — the slots are writable only over BLE — so an expiry is a
#: scheduled walk to the litter box, and there is no security gained by choosing
#: to take one.
LEAF_DAYS = 3650


@dataclass(frozen=True, slots=True)
class KeyPair:
    """A certificate and its private key, both PEM text."""

    cert_pem: str
    key_pem: str


def _bounded(common_name: str) -> str:
    """``common_name`` cut to what X.509 will accept, on a character boundary.

    Measured in **bytes**, not characters: the limit is on the encoded value, so
    a name of 33 accented characters is 66 bytes and raises while looking well
    short. Truncated on a boundary because half a UTF-8 sequence is not a name.
    """
    encoded = common_name.encode("utf-8")
    if len(encoded) <= CN_MAX:
        return common_name
    return encoded[:CN_MAX].decode("utf-8", errors="ignore")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _serial_number(cert_pem: str) -> int:
    return x509.load_pem_x509_certificate(cert_pem.encode()).serial_number


def _encode(cert: x509.Certificate, key: rsa.RSAPrivateKey) -> KeyPair:
    return KeyPair(
        cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        # TraditionalOpenSSL is "BEGIN RSA PRIVATE KEY" — the exact shape the
        # Whisker app writes into the robot. PKCS#8 is the modern default and is
        # very probably fine, but "probably" is not what this project ships.
        key_pem=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode(),
    )


def generate_ca(common_name: str = "whiskerless local CA") -> KeyPair:
    """Create a self-signed CA."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _bounded(common_name))])
    now = _now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        # Not decoration: Python 3.13 turns on VERIFY_X509_STRICT by default and
        # rejects a CA without keyUsage. A CA lacking it works for the robot's
        # mbedTLS and then fails in our own CLI, which is the worst possible split.
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return _encode(cert, key)


def _issue(
    ca: KeyPair,
    common_name: str,
    *,
    server: bool,
    sans: list[x509.GeneralName] | None = None,
) -> KeyPair:
    try:
        ca_cert = x509.load_pem_x509_certificate(ca.cert_pem.encode())
        ca_key = serialization.load_pem_private_key(ca.key_pem.encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise WhiskerlessError(f"could not read the CA: {exc}") from exc
    if not isinstance(ca_key, rsa.RSAPrivateKey):
        raise WhiskerlessError("the CA private key is not an RSA key")

    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
    now = _now()
    builder = (
        x509.CertificateBuilder()
        # Truncated rather than refused: every caller's name is descriptive, not
        # load-bearing — a robot's serial is bounded well under this by its own
        # validation, and what a TLS peer actually verifies is the SAN.
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _bounded(common_name))]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=LEAF_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
    )
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    return _encode(builder.sign(ca_key, hashes.SHA256()), key)


def issue_server(ca: KeyPair, host: str) -> KeyPair:
    """Issue the broker's server certificate for ``host``.

    The robot checks the hostname against whatever it was provisioned with, so an
    IP goes in as **both** an IP and a DNS SAN: some TLS stacks match an IP
    literal against the DNS list, and covering both costs nothing.
    """
    sans: list[x509.GeneralName] = [x509.DNSName(host)]
    # A real hostname raises here, and the DNS SAN alone is correct for it.
    with contextlib.suppress(ValueError):
        sans.append(x509.IPAddress(ipaddress.ip_address(host)))
    return _issue(ca, host, server=True, sans=sans)


def issue_client(ca: KeyPair, common_name: str) -> KeyPair:
    """Issue a client certificate — a robot's, or this machine's."""
    return _issue(ca, common_name, server=False)


def client_common_name() -> str:
    """What this machine calls itself to the broker.

    The hostname is in there so that two machines running whiskerless are
    distinguishable in the broker's log rather than both being "the CLI".

    Bounded to :data:`CN_MAX`, because a DNS label may be 63 characters and the
    prefix takes it past what X.509 allows — which is a ``ValueError`` out of the
    certificate builder, i.e. `setup` dying on a machine whose only crime is a
    long hostname. Returned already truncated so this reports the name that will
    actually be issued.
    """
    host = ""
    try:
        host = socket.gethostname().split(".")[0].strip()
    except OSError:
        host = ""
    return _bounded(f"whiskerless-{host}") if host else "whiskerless-cli"


def certificate_common_name(cert_pem: str) -> str | None:
    """The CN of a PEM certificate, or None if it has none."""
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
    except ValueError as exc:
        raise WhiskerlessError(f"not a readable certificate: {exc}") from exc
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    value = names[0].value if names else None
    return value if isinstance(value, str) else None


def check_pair(pair: KeyPair) -> None:
    """Refuse a certificate and key that do not belong together.

    Worth checking before a write that cannot be undone from here: a mismatched
    pair provisions cleanly and then fails every TLS handshake afterwards, which
    looks exactly like a robot that died.
    """
    try:
        cert = x509.load_pem_x509_certificate(pair.cert_pem.encode())
        key = serialization.load_pem_private_key(pair.key_pem.encode(), password=None)
    except (ValueError, TypeError) as exc:
        # An encrypted key raises TypeError ("password was not given"); anything
        # malformed raises ValueError. Both are things a person typed a path to.
        raise WhiskerlessError(
            f"could not read that certificate or key: {exc}. An encrypted private "
            f"key is not supported — decrypt it first"
        ) from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise WhiskerlessError("the private key is not an RSA key")
    if cert.public_key().public_numbers() != key.public_key().public_numbers():  # type: ignore[union-attr]
        raise WhiskerlessError("this certificate and private key are not a pair")


def read_pair(cert_path: Path, key_path: Path) -> KeyPair:
    """Load a cert/key pair from disk and verify they match."""
    try:
        pair = KeyPair(
            cert_pem=cert_path.expanduser().read_text(encoding="utf-8"),
            key_pem=key_path.expanduser().read_text(encoding="utf-8"),
        )
    except OSError as exc:
        raise WhiskerlessError(f"could not read {exc.filename}: {exc.strerror}") from exc
    check_pair(pair)
    return pair


def issued_serial(pair: KeyPair) -> str:
    """The certificate's serial number, hex, for recording what was issued.

    Not secret, and the only trace kept of a robot's client certificate. Nothing
    reads it today; it exists so that a certificate revocation list can be built
    later by someone who did not plan for one, which is the situation everybody
    is in when they suddenly want one.
    """
    return f"{_serial_number(pair.cert_pem):x}"
