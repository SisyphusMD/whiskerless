"""The EVO's half of the safety chokepoint."""

from __future__ import annotations

import pytest

from whiskerless.exceptions import DangerousCommandError, ProtocolError
from whiskerless.safety import (
    CommandType,
    Hazard,
    assert_evo_sendable,
    classify_evo,
    classify_evo_code,
    parse_evo_code,
)


def test_parse_splits_type_bank_register_value() -> None:
    assert parse_evo_code("0x0202010808") == (CommandType.WRITE, 0x02, 0x01, 0x0808)
    assert parse_evo_code(" 0x0101200000 ") == (CommandType.READ, 0x01, 0x20, 0)


def test_an_unknown_type_byte_is_a_noop() -> None:
    assert parse_evo_code("0x0702010808")[0] is CommandType.NOOP
    assert classify_evo_code("0x0702010808") is Hazard.NOOP


@pytest.mark.parametrize("code", ["0x02010808", "0x020201080800", "0202010808", "0x02020108G8"])
def test_anything_but_the_evo_width_is_refused(code: str) -> None:
    """An LR4 element is the classic mistake: the EVO parses it at the wrong address."""
    with pytest.raises(ProtocolError):
        parse_evo_code(code)


@pytest.mark.parametrize(
    "code",
    [
        "0x0202010808",  # panel brightness
        "0x0202090007",  # cycle delay
        "0x02020A0001",  # lockout
        "0x0202100041",  # sleep days
        "0x02021E02D0",  # saturday wake
        "0x0202020005",  # clock weekday
        "0x020208001A",  # clock year
        "0x020103000A",  # clean cycle
        "0x020103000B",  # empty cycle
        "0x020103000C",  # change filter
        "0x0201220001",  # drawer reset
        "0x0201140001",  # power on
        "0x0101200000",  # any read
    ],
)
def test_the_apps_commands_are_safe(code: str) -> None:
    assert classify_evo_code(code) is Hazard.SAFE
    assert assert_evo_sendable(code) is Hazard.SAFE


@pytest.mark.parametrize(
    "code",
    [
        "0x0201140000",  # power off
        "0x0201010201",  # a panel press: reported, never written
        "0x0201030004",  # a status value that is not an action
        "0x02021F0001",  # past the sleep registers
        "0x0205010001",  # an unexplored bank
    ],
)
def test_everything_else_needs_the_override(code: str) -> None:
    assert classify_evo_code(code) is Hazard.DANGEROUS
    with pytest.raises(DangerousCommandError):
        assert_evo_sendable(code)
    assert assert_evo_sendable(code, allow_dangerous=True) is Hazard.DANGEROUS


def test_classify_takes_parsed_fields() -> None:
    assert classify_evo(CommandType.WRITE, 0x02, 0x09, 3) is Hazard.SAFE
