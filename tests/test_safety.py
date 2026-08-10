"""The safety guard — the one chokepoint every send funnels through."""

from __future__ import annotations

import pytest

from whiskerless.devices.litter_robot_4 import commands
from whiskerless.exceptions import DangerousCommandError, NeverSendError, ProtocolError
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
        assert_sendable(code, allow_dangerous=True)


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

    @pytest.mark.parametrize(
        "build", [commands.clean_cycle, commands.panel_reset, commands.empty_cycle]
    )
    def test_the_routine_presses_are_ungated(self, build: object) -> None:
        """A written press IS a panel press, so the guard adds nothing to it.

        These were once gated behind an ``allow_motor`` flag invented when the
        globe trigger was thought to be an unknown macro opcode. Writing 0x01
        reproduces the code the panel emits and the firmware's pinch, cat-detect
        and bonnet interlocks sit downstream of it, so the gate protected against
        a hazard that does not exist — and every caller passed the flag anyway.
        """
        assert assert_sendable(build().code) is Hazard.SAFE  # type: ignore[operator]

    def test_power_is_the_one_press_that_still_needs_an_opt_in(self) -> None:
        """Every other action can be undone from the same connection; this cannot.

        Power toggles, and a robot switched off has left the network, so nothing
        over MQTT can switch it back on.
        """
        code = commands.power_toggle().code
        assert classify_code(code) is Hazard.DANGEROUS
        with pytest.raises(DangerousCommandError):
            assert_sendable(code)
        assert assert_sendable(code, allow_dangerous=True) is Hazard.DANGEROUS

    @pytest.mark.parametrize("value", [0x1001, 0x0000, 0x0601, 0x0201 | 0x0800])
    def test_unrecognised_button_values_stay_refused(self, value: int) -> None:
        """Classification is by VALUE: an unlisted combination is still untested."""
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
            assert_sendable(code, allow_dangerous=True)

    def test_the_shipped_actions_are_still_reachable(self) -> None:
        for code in ("0x02010201", "0x02010401", "0x02010801"):
            assert_sendable(code)


@pytest.mark.parametrize("code", ["0x02ZZ0000", "0x0218000G", "0xGG180001"])
def test_a_non_hex_command_is_refused_before_it_is_classified(code: str) -> None:
    """Shape is checked first, so a typo cannot fall through to a hazard verdict.

    Every send is built by this library, so a malformed code means a caller
    hand-wrote one — `whiskerless send` is exactly that path.
    """
    with pytest.raises(ProtocolError, match="non-hex"):
        assert_sendable(code, allow_dangerous=True)


def test_an_unrecognised_type_nibble_is_a_no_op_not_a_write() -> None:
    """The firmware acts on type 1 and 2 and ignores the rest.

    Classifying an unknown nibble as anything else would either refuse a command
    that does nothing, or — far worse — reason about it as though the register
    and value mattered.
    """
    # Type nibble 3 with an opcode that would be NEVER if it were a real write.
    assert classify_code("0x03A30000") is Hazard.NOOP
    assert_sendable("0x03A30000")
