"""The logging filter that puts `scrub()` in front of every record the CLI emits.

Separate from `test_diagnostics.py` because this half needs the CLI: `scrub()` is a pure function
of text, while the filter is how the tool promises a `--debug` log is safe to paste.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from whiskerless.cli import _ScrubbingFilter
from whiskerless.diagnostics import scrub

_HOME = Path("/Users/someone/whiskerless")


def test_debug_records_are_scrubbed_before_they_are_formatted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The filter is the guarantee — scrub() being correct means nothing if records bypass it."""

    logger = logging.getLogger("whiskerless.test-scrub")
    logger.addFilter(_ScrubbingFilter(_HOME))
    with caplog.at_level(logging.DEBUG, logger="whiskerless.test-scrub"):
        logger.debug("robot LR4C123456 at 10.0.0.7")

    assert "LR4C123456" not in caplog.text
    assert "10.0.0.7" not in caplog.text


# --- what provisioning actually emits (found by review, 2026-08-20) -------------------
#
# The patterns were written against the quoted, IPv4 shapes and let the common ones straight
# through: `ssid=HomeNet` unquoted, a broker named rather than numbered, and the robot's MAC.
# A scrubber that misses the network name is worse than no scrubber, because it is the reason the
# person felt safe pasting the log.
@pytest.mark.parametrize(
    ("line", "leaked"),
    [
        ("ssid=HomeNet", "HomeNet"),
        ("ssid: HomeNet", "HomeNet"),
        ('ssid="HomeNet"', "HomeNet"),
        ("network=Guest-2G", "Guest-2G"),
        ("host=mqtt.home.lan", "mqtt.home.lan"),
        ("broker: mqtts://mqtt.home.lan", "mqtt.home.lan"),
        ("connected to AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),
        ("mac 00:1a:2b:3c:4d:5e", "00:1a:2b:3c:4d:5e"),
        ("broker 192.0.2.10:8883", "192.0.2.10"),
    ],
)
def test_the_identifying_value_never_survives(line: str, leaked: str) -> None:
    assert leaked not in scrub(line)


def test_a_logged_exception_object_is_scrubbed_too(tmp_path: Path) -> None:
    """Scrubbing only the str arguments left every other object verbatim — and the BLE paths log
    exception objects, whose text carries the MAC and the serial."""
    record = logging.LogRecord(
        "w", logging.INFO, __file__, 1, "connect failed: %s",
        (OSError("no route to AA:BB:CC:DD:EE:FF for LR4C1234567890"),), None,
    )
    _ScrubbingFilter(tmp_path).filter(record)
    text = record.getMessage()
    assert "AA:BB:CC:DD:EE:FF" not in text
    assert "LR4C1234567890" not in text
    assert "connect failed:" in text


def test_a_broken_format_string_still_scrubs_what_it_can(tmp_path: Path) -> None:
    """A record that cannot be formatted is a bug worth seeing, but not at the price of leaking
    the identifiers it was carrying."""
    record = logging.LogRecord(
        "w", logging.INFO, __file__, 1, "%d robots at %s", ("LR4C1234567890",), None,
    )
    _ScrubbingFilter(tmp_path).filter(record)
    assert "LR4C1234567890" not in record.getMessage()
