"""The safety guard — the one chokepoint every send funnels through."""

from __future__ import annotations

import pytest

from whiskerless.exceptions import (
    DangerousCommandError,
    MotorCommandError,
    NeverSendError,
    ProtocolError,
)
from whiskerless.safety import Hazard, assert_sendable, classify_code


@pytest.mark.parametrize(
    ("code", "hazard"),
    [
        ("0x02A00000", Hazard.SAFE),       # requestState
        ("0x01470000", Hazard.SAFE),       # type-1 read
        ("0x02180001", Hazard.SAFE),       # settings write
        ("0x02A10000", Hazard.SAFE),       # report macro, value 0
        ("0x02A30000", Hazard.MOTOR),      # clean cycle
        ("0x02AC0000", Hazard.NEVER),      # MB flash
        ("0x02A40001", Hazard.NEVER),      # globe-motor OTA
        ("0x02AD0000", Hazard.NEVER),      # hardware reset
        ("0x02300001", Hazard.DANGEROUS),  # power candidate (control band)
        ("0x02A70003", Hazard.DANGEROUS),  # report macro with non-zero jump index
        ("0x00120000", Hazard.NOOP),       # type nibble not 1/2
    ],
)
def test_classify(code: str, hazard: Hazard) -> None:
    assert classify_code(code) == hazard


@pytest.mark.parametrize("code", ["0x02AC0000", "0x02A40001", "0x02AD0000"])
def test_never_send_is_unconditional(code: str) -> None:
    # No combination of flags lets a brick/reset-class command through.
    with pytest.raises(NeverSendError):
        assert_sendable(code, allow_motor=True, allow_dangerous=True)


def test_motor_requires_optin() -> None:
    with pytest.raises(MotorCommandError):
        assert_sendable("0x02A30000")
    assert assert_sendable("0x02A30000", allow_motor=True) is Hazard.MOTOR


def test_dangerous_requires_optin() -> None:
    with pytest.raises(DangerousCommandError):
        assert_sendable("0x02300001")
    assert assert_sendable("0x02300001", allow_dangerous=True) is Hazard.DANGEROUS


def test_safe_always_allowed() -> None:
    assert assert_sendable("0x02A00000") is Hazard.SAFE
    assert assert_sendable("0x01470000") is Hazard.SAFE


@pytest.mark.parametrize("code", ["0xA50001", "0x02A0000", "not-hex", ""])
def test_parse_rejects_malformed(code: str) -> None:
    with pytest.raises(ProtocolError):
        classify_code(code)
