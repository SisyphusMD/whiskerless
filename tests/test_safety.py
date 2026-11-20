"""The safety guard — the one chokepoint every send funnels through."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from whiskerless.devices.litter_robot_4 import commands
from whiskerless.devices.litter_robot_4.commands import Command
from whiskerless.exceptions import DangerousCommandError, NeverSendError, ProtocolError
from whiskerless.safety import (
    NEVER_SEND_OPCODES,
    NEVER_SEND_REGISTERS,
    PANEL_BUTTON_NEVER,
    SAFE_SETTING_VALUES,
    Hazard,
    assert_sendable,
    classify_code,
)


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
        ("0x022D0001", Hazard.NEVER),      # PIC factory reset (UART reference)
        ("0x022D0000", Hazard.NEVER),      # refused at any value, not just 1
        ("0x012D0000", Hazard.SAFE),       # reading it is still a read
        ("0x02300001", Hazard.DANGEROUS),  # power candidate (control band)
        ("0x02A70003", Hazard.DANGEROUS),  # report macro with non-zero jump index
        ("0x00120000", Hazard.DANGEROUS),  # type byte not 01/02
        ("0x03180001", Hazard.DANGEROUS),  # unknown type on a safe settings register
        ("0x12A00000", Hazard.DANGEROUS),  # high type digit set: not a type-2 write
        ("0x021A0001", Hazard.SAFE),       # known no-op: read-only view, write discarded
    ],
)
def test_classify(code: str, hazard: Hazard) -> None:
    assert classify_code(code) == hazard


@pytest.mark.parametrize(
    "code", ["0x02A30000", "0x02AC0000", "0x02A40001", "0x02AD0000", "0x022D0001"]
)
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

    @pytest.mark.parametrize("build", [commands.power_toggle, commands.wifi_toggle])
    def test_the_two_presses_that_can_end_the_connection_need_an_opt_in(
        self, build: Callable[[], Command]
    ) -> None:
        """Every safe action can be undone from the same connection; these cannot.

        Both toggle, and both can leave the robot off the network — powered down,
        or with its WiFi switched off — where nothing over MQTT reaches it.
        """
        code = build().code
        assert classify_code(code) is Hazard.DANGEROUS
        with pytest.raises(DangerousCommandError):
            assert_sendable(code)
        assert assert_sendable(code, allow_dangerous=True) is Hazard.DANGEROUS

    @pytest.mark.parametrize("value", [0x0000, 0x0601, 0x0201 | 0x0800])
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


def test_an_unknown_command_type_needs_opt_in() -> None:
    """The firmware is said to ignore any type but 1 and 2; that was never tried.

    Treating it as a no-op let an untested byte through with no opt-in.
    """
    with pytest.raises(DangerousCommandError):
        assert_sendable("0x03180001")
    assert assert_sendable("0x03180001", allow_dangerous=True) is Hazard.DANGEROUS


@pytest.mark.parametrize(
    "code",
    [
        "0x03A30000",
        "0x00AC0000",
        "0x11A30000",  # low digit 1: the old parser took this for a read and sent it
        "0x11AC0000",
        "0x122D0001",
        *(f"0x0301{value:04X}" for value in sorted(PANEL_BUTTON_NEVER)),
    ],
)
def test_an_unknown_type_never_unlocks_a_never_send_target(code: str) -> None:
    # If the firmware does not ignore the type after all, the override must not
    # be the thing that sent a reset.
    with pytest.raises(NeverSendError):
        assert_sendable(code, allow_dangerous=True)


#: (register, lowest verified value, highest verified value)
_SETTING_RANGES = [
    (0x16, 3, 30),       # clean-cycle wait, minutes
    (0x17, 0, 1),        # keypad lockout
    (0x18, 0, 2),        # night-light mode
    (0x19, 0, 100),      # night-light brightness, %
    (0x1A, 0, 1),        # discarded view of 0x1D
    (0x1B, 0, 1439),     # discarded view of today's sleep time
    (0x1C, 0, 1439),
    (0x1D, 0, 0x7F),     # seven-day mask
    *((register, 0, 1439) for register in range(0x1E, 0x2C)),
]


class TestSettingValueRanges:
    """A settings register is SAFE only at values that were seen to land.

    Every one of these registers used to take any 16-bit value with no opt-in, so
    `0x0216FFFF` went out as freely as the 20-minute wait it was tested at.
    """

    def test_the_table_is_exactly_the_documented_ranges(self) -> None:
        # Pinned whole, so a register added at any value, or one dropped from the
        # table, fails here instead of passing every boundary test below.
        assert {register: range(low, high + 1) for register, low, high in _SETTING_RANGES} == (
            SAFE_SETTING_VALUES
        )

    @pytest.mark.parametrize(("register", "low", "high"), _SETTING_RANGES)
    def test_the_verified_range_is_safe_up_to_both_ends(
        self, register: int, low: int, high: int
    ) -> None:
        for value in (low, high):
            assert assert_sendable(f"0x02{register:02X}{value:04X}") is Hazard.SAFE

    @pytest.mark.parametrize(("register", "low", "high"), _SETTING_RANGES)
    def test_a_value_past_either_end_needs_opt_in(
        self, register: int, low: int, high: int
    ) -> None:
        outside = [high + 1, 0xFFFF] + ([low - 1] if low > 0 else [])
        for value in outside:
            code = f"0x02{register:02X}{value:04X}"
            with pytest.raises(DangerousCommandError):
                assert_sendable(code)
            assert assert_sendable(code, allow_dangerous=True) is Hazard.DANGEROUS

    def test_the_lockout_flag_is_checked_on_all_sixteen_bits(self) -> None:
        # The register is a 0/1 flag, but the value field is 16 bits wide.
        assert classify_code("0x02170100") is Hazard.DANGEROUS

    @pytest.mark.parametrize("value", [0x0000, 0x0001])
    def test_debug_mode_has_no_verified_value(self, value: int) -> None:
        """`0x05` was in the safe bank without a single recorded write (#91)."""
        assert classify_code(f"0x0205{value:04X}") is Hazard.DANGEROUS

    @pytest.mark.parametrize("value", [0x0000, 0x0064, 0x6400, 0x6464, 0x2832, 0x0532])
    def test_panel_brightness_is_safe_when_both_levels_are_in_range(self, value: int) -> None:
        assert classify_code(f"0x020E{value:04X}") is Hazard.SAFE

    @pytest.mark.parametrize("value", [0x0065, 0x6500, 0x00FF, 0xFF00, 0xFFFF])
    def test_panel_brightness_checks_each_level_on_its_own(self, value: int) -> None:
        # A range on the packed value would pass 0x00FF: a dark-room level of 255.
        code = f"0x020E{value:04X}"
        with pytest.raises(DangerousCommandError):
            assert_sendable(code)
        assert assert_sendable(code, allow_dangerous=True) is Hazard.DANGEROUS

    @pytest.mark.parametrize(
        "code",
        [
            *(f"0x02{opcode:02X}{value:04X}"
              for opcode in sorted(NEVER_SEND_OPCODES | NEVER_SEND_REGISTERS)
              for value in (0x0000, 0x0007, 0xFFFF)),
            *(f"0x0201{value:04X}" for value in sorted(PANEL_BUTTON_NEVER)),
        ],
    )
    def test_never_send_targets_stay_refused_at_any_value(self, code: str) -> None:
        with pytest.raises(NeverSendError):
            assert_sendable(code, allow_dangerous=True)
