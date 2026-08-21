"""The scrubber that makes --debug output shareable."""

from __future__ import annotations

from pathlib import Path

import pytest

from whiskerless.diagnostics import scrub

_HOME = Path("/Users/someone/whiskerless")


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("connecting to LR4C123456", "LR4C123456", "connecting to"),
        ("broker at 192.168.1.50:8883", "192.168.1.50", "broker at"),
        ('joining SSID "HomeNet"', "HomeNet", "joining"),
        ("subject CN=LR4C999999, O=whiskerless", "LR4C999999", "O=whiskerless"),
    ],
)
def test_identifying_values_are_removed_and_the_rest_survives(
    text: str, gone: str, kept: str
) -> None:
    """A scrubber that eats the message is as useless as one that eats nothing."""
    cleaned = scrub(text, _HOME)

    assert gone not in cleaned
    assert kept in cleaned


def test_the_home_path_becomes_a_tilde() -> None:
    assert scrub(f"store at {_HOME}/robots", _HOME) == "store at ~/robots"


def test_root_is_never_blanked_out() -> None:
    """`str(Path("/"))` is one character; replacing it would shred every absolute path."""
    assert scrub("reading /etc/hosts", Path("/")) == "reading /etc/hosts"


def test_text_with_nothing_sensitive_is_returned_unchanged() -> None:
    assert scrub("waiting for the robot to answer", _HOME) == "waiting for the robot to answer"


def test_an_unlabelled_domain_is_left_alone() -> None:
    """Deliberately not a bare domain pattern. Redacting `github.com` out of a URL in the same log
    would make the output less readable while protecting nothing."""
    line = "see https://github.com/SisyphusMD/whiskerless for details"
    assert scrub(line) == line


def test_an_unquoted_ssid_with_spaces_is_redacted_whole() -> None:
    """Plenty of networks are called "My Home". Stopping at the first space redacted "My" and
    published " Home", which is the half a reader would recognise."""
    assert "Home" not in scrub("ssid=My Home; verifying join")


@pytest.mark.parametrize(
    ("line", "gone"),
    [
        ("host=2001:db8::1234", "db8"),
        ("broker=[2001:db8::1]:8883", "2001"),
        ("connecting to fe80::1", "fe80"),
        ("addr=2001:0db8:0000:0000:0000:ff00:0042:8329", "8329"),
        ("host=::1", "::1"),
    ],
)
def test_ipv6_broker_addresses_are_redacted(line: str, gone: str) -> None:
    """`_HOST` is IPv4-only and the labelled-host pattern stops at the first colon, so an IPv6
    broker published everything after its first group out of a log called redacted."""
    out = scrub(line)
    assert gone not in out
    assert "<redacted-address>" in out


@pytest.mark.parametrize("line", ["at 17:18:57 the run finished", "ratio 1:2:3", "std::vector"])
def test_things_that_merely_look_like_addresses_are_left_alone(line: str) -> None:
    """A three-group run is a timestamp, and no valid IPv6 address has that shape. Redacting it
    would make every log less readable while protecting nothing."""
    assert scrub(line) == line


@pytest.mark.parametrize("serial", ["LR4C123456", "LR4D123456", "LR3C000001"])
def test_every_serial_shape_provisioning_accepts_is_redacted(serial: str) -> None:
    """Provisioning accepts the whole `LR3/LR4<letter>` shape, so a future `LR4D…` was logged by
    the DEVICE_ID_SET step and survived a scrubber that had just promised to redact serials."""
    assert serial not in scrub(f"device {serial} joined")


@pytest.mark.parametrize(
    "line",
    [
        "ssid=My,Home; verifying join",
        "ssid=Plain",
        "network: My Home",
        'ssid=has"a"quote',
        "ssid=trailing; semicolons; everywhere",
    ],
)
def test_an_unquoted_ssid_is_redacted_to_the_end_of_the_line(line: str) -> None:
    """An SSID may contain any octet — comma, semicolon, quote — so every "stop at punctuation"
    rule published the tail of somebody's network name. Unquoted values fail safe."""
    out = scrub(line)
    assert out.endswith("<redacted-network>")
    assert "Home" not in out
    assert "Plain" not in out


def test_a_quoted_ssid_keeps_the_rest_of_the_line() -> None:
    """This project's own provisioning log quotes the value, so the scrubber can end it precisely
    and keep the context that makes the log worth reading."""
    out = scrub("ssid='My,Home'; verifying join (30s)")
    assert "My,Home" not in out
    assert "verifying join (30s)" in out
