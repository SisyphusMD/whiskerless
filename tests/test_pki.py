"""The certificate authority whiskerless runs on the user's behalf.

Everything the robot connects to authenticates by certificate, because the robot
cannot send anything else. These tests pin the properties that make that work —
and the ones that would fail silently at TLS handshake time if they broke.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

from whiskerless import pki
from whiskerless.exceptions import WhiskerlessError


@pytest.fixture(scope="module")
def ca() -> pki.KeyPair:
    """One CA for the whole module — RSA-2048 keygen is not free."""
    return pki.generate_ca()


def _cert(pem: str) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem.encode())


def test_the_ca_can_sign_and_says_so(ca: pki.KeyPair) -> None:
    cert = _cert(ca.cert_pem)
    basic = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
    assert basic.ca is True
    assert usage.key_cert_sign is True


def test_the_ca_carries_key_usage(ca: pki.KeyPair) -> None:
    """Python 3.13 turns on VERIFY_X509_STRICT by default and rejects a CA
    without it. The robot's mbedTLS accepts one either way, so a CA missing this
    works on the robot and then fails in our own CLI — the worst possible split."""
    ext = _cert(ca.cert_pem).extensions.get_extension_for_class(x509.KeyUsage)
    assert ext.critical is True
    assert ext.value.key_cert_sign and ext.value.crl_sign


def test_keys_are_written_in_the_shape_the_robot_is_known_to_accept(ca: pki.KeyPair) -> None:
    """The Whisker app writes `BEGIN RSA PRIVATE KEY` into the robot. PKCS#8 is
    very probably fine and "probably" is not what gets written to flash."""
    assert ca.key_pem.startswith("-----BEGIN RSA PRIVATE KEY-----")


def test_a_server_certificate_covers_an_ip_as_both_kinds_of_name(ca: pki.KeyPair) -> None:
    """The robot checks the hostname against whatever it was provisioned with,
    and some TLS stacks match an IP literal against the DNS list."""
    pair = pki.issue_server(ca, "192.168.1.10")
    sans = _cert(pair.cert_pem).extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert ipaddress.ip_address("192.168.1.10") in sans.get_values_for_type(x509.IPAddress)
    assert "192.168.1.10" in sans.get_values_for_type(x509.DNSName)


def test_a_server_certificate_for_a_hostname_has_no_ip_san(ca: pki.KeyPair) -> None:
    pair = pki.issue_server(ca, "mqtt.example.lan")
    sans = _cert(pair.cert_pem).extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert sans.get_values_for_type(x509.DNSName) == ["mqtt.example.lan"]
    assert sans.get_values_for_type(x509.IPAddress) == []


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        (pki.issue_server, ExtendedKeyUsageOID.SERVER_AUTH),
        (pki.issue_client, ExtendedKeyUsageOID.CLIENT_AUTH),
    ],
)
def test_leaves_declare_what_they_are_for(ca: pki.KeyPair, issue: object, expected: object) -> None:
    """mosquitto's `require_certificate` checks clientAuth; handing it a server
    cert is a mistake that only shows up as a refused connection."""
    pair = issue(ca, "192.168.1.10")  # type: ignore[operator]
    usage = _cert(pair.cert_pem).extensions.get_extension_for_class(
        x509.ExtendedKeyUsage
    ).value
    assert list(usage) == [expected]


def test_leaves_are_not_themselves_authorities(ca: pki.KeyPair) -> None:
    pair = pki.issue_client(ca, "LR4C123456")
    basic = _cert(pair.cert_pem).extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic.ca is False


def test_a_robot_certificate_is_named_for_its_serial(ca: pki.KeyPair) -> None:
    """`use_identity_as_username` turns the CN into the MQTT username, so the
    serial is what the broker logs and what an ACL could bind to."""
    pair = pki.issue_client(ca, "LR4C123456")
    assert pki.certificate_common_name(pair.cert_pem) == "LR4C123456"


def test_leaves_are_signed_by_the_ca(ca: pki.KeyPair) -> None:
    pair = pki.issue_client(ca, "LR4C123456")
    assert _cert(pair.cert_pem).issuer == _cert(ca.cert_pem).subject


def test_every_issued_certificate_is_unique(ca: pki.KeyPair) -> None:
    """Re-provisioning mints a fresh identity rather than reusing one."""
    first, second = pki.issue_client(ca, "LR4C123456"), pki.issue_client(ca, "LR4C123456")
    assert pki.issued_serial(first) != pki.issued_serial(second)
    assert first.key_pem != second.key_pem


def test_this_machine_names_itself_after_its_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two machines running whiskerless should be distinguishable in the broker's
    log, rather than both being "the CLI"."""
    monkeypatch.setattr("socket.gethostname", lambda: "kitchen-pi.local")
    assert pki.client_common_name() == "whiskerless-kitchen-pi"


def test_a_very_long_hostname_does_not_kill_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """X.509 caps a common name at 64 characters and `cryptography` enforces it
    by raising. A DNS label may be 63 on its own, so the prefix is enough to pass
    it — and the whole of `setup` then dies on a machine whose only crime is a
    long hostname. Found on a CI runner, not in review."""
    monkeypatch.setattr("socket.gethostname", lambda: "a" * 63)
    name = pki.client_common_name()
    assert len(name) == pki.CN_MAX
    assert name.startswith("whiskerless-")


def test_the_cap_is_bytes_not_characters(ca: pki.KeyPair) -> None:
    """The limit is on the ENCODED value, so 33 accented characters is 66 bytes
    and raises while looking well short of 64 — an accented hostname is not
    exotic. Cut on a character boundary, because half a UTF-8 sequence is not a
    name any parser will take."""
    pair = pki.issue_client(ca, "é" * 40)
    name = pki.certificate_common_name(pair.cert_pem) or ""
    assert len(name.encode("utf-8")) <= pki.CN_MAX
    assert name == "é" * 32  # a whole number of characters, not a split one


def test_a_ca_name_is_capped_too(ca: pki.KeyPair) -> None:
    """`generate_ca` builds its subject directly, so the guard on the leaf path
    does not cover it."""
    made = pki.generate_ca("a" * 100)
    assert len(pki.certificate_common_name(made.cert_pem) or "") == pki.CN_MAX


def test_an_over_long_name_is_truncated_rather_than_raising(ca: pki.KeyPair) -> None:
    """The guard sits at the builder too, so no caller can reach the raise —
    and the SAN, which is what a TLS peer actually verifies, is not affected."""
    pair = pki.issue_server(ca, "x" * 80 + ".example.lan")
    cert = _cert(pair.cert_pem)
    assert len(pki.certificate_common_name(pair.cert_pem) or "") == pki.CN_MAX
    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert sans.get_values_for_type(x509.DNSName) == ["x" * 80 + ".example.lan"]


@pytest.mark.parametrize("failure", [lambda: "", lambda: (_ for _ in ()).throw(OSError)])
def test_a_machine_with_no_usable_hostname_still_has_a_name(
    monkeypatch: pytest.MonkeyPatch, failure: object
) -> None:
    monkeypatch.setattr("socket.gethostname", failure)
    assert pki.client_common_name() == "whiskerless-cli"


def test_a_mismatched_certificate_and_key_are_refused(ca: pki.KeyPair) -> None:
    """A mismatched pair provisions cleanly and then fails every handshake, which
    looks exactly like a robot that died. Worth catching before an unrecoverable
    write."""
    other = pki.issue_client(ca, "LR4C999999")
    mixed = pki.KeyPair(cert_pem=pki.issue_client(ca, "LR4C123456").cert_pem, key_pem=other.key_pem)
    with pytest.raises(WhiskerlessError, match="not a pair"):
        pki.check_pair(mixed)


def test_a_matching_pair_passes(ca: pki.KeyPair) -> None:
    pki.check_pair(pki.issue_client(ca, "LR4C123456"))


def test_something_that_is_not_a_certificate_says_so() -> None:
    with pytest.raises(WhiskerlessError, match="not a readable certificate"):
        pki.certificate_common_name("hello")


def test_a_certificate_without_a_common_name_reads_as_none(ca: pki.KeyPair) -> None:
    """Nothing whiskerless issues is nameless, but a CA someone brings might be."""
    import datetime

    from cryptography import x509 as _x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.UTC)
    nameless = (
        _x509.CertificateBuilder()
        .subject_name(_x509.Name([]))
        .issuer_name(_x509.Name([]))
        .public_key(key.public_key())
        .serial_number(_x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem = nameless.public_bytes(serialization.Encoding.PEM).decode()
    assert pki.certificate_common_name(pem) is None


def test_a_pair_round_trips_through_disk(ca: pki.KeyPair, tmp_path: Path) -> None:
    (tmp_path / "c.pem").write_text(ca.cert_pem)
    (tmp_path / "k.pem").write_text(ca.key_pem)
    loaded = pki.read_pair(tmp_path / "c.pem", tmp_path / "k.pem")
    assert loaded.cert_pem == ca.cert_pem


def test_a_missing_file_is_explained_rather_than_traced(tmp_path: Path) -> None:
    with pytest.raises(WhiskerlessError, match="could not read"):
        pki.read_pair(tmp_path / "nope.pem", tmp_path / "also-nope.pem")


def test_a_non_rsa_ca_is_refused(tmp_path: Path) -> None:
    """Everything here is RSA because that is what the robot is known to take."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    ca = pki.generate_ca()
    bad = pki.KeyPair(
        cert_pem=ca.cert_pem,
        key_pem=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    with pytest.raises(WhiskerlessError, match="not an RSA key"):
        pki.issue_client(bad, "LR4C123456")


def test_check_pair_refuses_a_non_rsa_key(ca: pki.KeyPair) -> None:
    """A separate guard from the one in issuing: this is the path a user's own
    supplied pair takes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    bad = pki.KeyPair(
        cert_pem=ca.cert_pem,
        key_pem=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    with pytest.raises(WhiskerlessError, match="not an RSA key"):
        pki.check_pair(bad)


@pytest.mark.parametrize("broken", ["not a pem at all", ""])
def test_unreadable_pem_is_explained_not_traced(ca: pki.KeyPair, broken: str) -> None:
    """`main()` turns WhiskerlessError into one line; a raw ValueError from the
    crypto layer would come out as a traceback for ordinary bad input."""
    with pytest.raises(WhiskerlessError, match="could not read"):
        pki.check_pair(pki.KeyPair(cert_pem=ca.cert_pem, key_pem=broken))
    with pytest.raises(WhiskerlessError, match="could not read the CA"):
        pki.issue_client(pki.KeyPair(cert_pem=ca.cert_pem, key_pem=broken), "LR4C123456")


def test_an_encrypted_private_key_says_so(ca: pki.KeyPair) -> None:
    """cryptography raises TypeError for a key that needs a password, which is not
    a shape `main()` catches — and "decrypt it first" is the actionable answer."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    locked = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.BestAvailableEncryption(b"hunter2"),
    ).decode()
    with pytest.raises(WhiskerlessError, match="encrypted private key"):
        pki.check_pair(pki.KeyPair(cert_pem=ca.cert_pem, key_pem=locked))
