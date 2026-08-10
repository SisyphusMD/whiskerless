"""The safety guard — the one chokepoint every send funnels through."""

from __future__ import annotations

import pytest

from whiskerless import safety
from whiskerless.devices.litter_robot_4 import commands
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
        ("0x02A30000", Hazard.NEVER),      # reset / MB-OTA orchestrator (was mislabeled cleanCycle)
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


@pytest.mark.parametrize("code", ["0x02A30000", "0x02AC0000", "0x02A40001", "0x02AD0000"])
def test_never_send_is_unconditional(code: str) -> None:
    # No combination of flags lets a brick/reset-class command through.
    with pytest.raises(NeverSendError):
        assert_sendable(code, allow_motor=True, allow_dangerous=True)


def test_motor_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # No opcode is currently proven to drive the globe (MOTOR_OPCODES is empty); the
    # old 0xA3 guess turned out to reset the robot. This exercises the gate a future,
    # confirmed cleanCycle trigger will use by standing in a placeholder opcode.
    monkeypatch.setattr(safety, "MOTOR_OPCODES", frozenset({0xB7}))
    with pytest.raises(MotorCommandError):
        assert_sendable("0x02B70000")
    assert assert_sendable("0x02B70000", allow_motor=True) is Hazard.MOTOR


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


class TestPanelButton:
    """`0x01` is classified by VALUE — the same register does two different jobs."""

    def test_the_clean_cycle_needs_the_motor_gate(self) -> None:
        code = commands.clean_cycle().code
        assert classify_code(code) is Hazard.MOTOR
        with pytest.raises(MotorCommandError):
            assert_sendable(code)
        assert_sendable(code, allow_motor=True)

    def test_reset_is_motor_gated_too(self) -> None:
        """It looks harmless and is not.

        From idle Reset only acknowledges an alarm, but during a cycle it releases
        a cat-detect pause — the interlock holding the globe still while something
        is inside. An automation firing it blind could restart a cycle over a cat.
        """
        code = commands.panel_reset().code
        assert classify_code(code) is Hazard.MOTOR
        with pytest.raises(MotorCommandError):
            assert_sendable(code)
        assert_sendable(code, allow_motor=True)

    @pytest.mark.parametrize("value", [0x0101, 0x0801, 0x1001, 0x0000])
    def test_every_other_button_stays_refused(self, value: int) -> None:
        """Only the two proven values are allowed through.

        The remaining bits are untested and one of them may be power, which could
        take the robot off the network with no remote way back.
        """
        code = f"0x0201{value:04X}"
        assert classify_code(code) is Hazard.DANGEROUS
        with pytest.raises(DangerousCommandError):
            assert_sendable(code)


class TestPanelButtonNeverSend:
    """`0x01` can factory-reset the robot, which is why it is whitelisted by value.

    Whisker documents the panel combos: Reset+Empty held is a factory reset, which
    wipes the broker configuration whiskerless depends on and needs a BLE
    re-provision to undo. It differs from the clean cycle by two bits.
    """

    @pytest.mark.parametrize(
        ("code", "what"),
        [
            ("0x02010C02", "factory reset (Reset+Empty long)"),
            ("0x02011002", "onboarding mode (Connect long)"),
            ("0x02011402", "simulate plug pull (Reset+Connect long)"),
        ],
    )
    def test_destructive_combos_cannot_be_sent_at_all(self, code: str, what: str) -> None:
        assert classify_code(code) is Hazard.NEVER
        with pytest.raises(NeverSendError):
            assert_sendable(code, allow_motor=True, allow_dangerous=True)

    def test_the_shipped_actions_are_still_reachable(self) -> None:
        for code in ("0x02010201", "0x02010401"):
            assert_sendable(code, allow_motor=True)
