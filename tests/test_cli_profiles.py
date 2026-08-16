"""The CLI's memory: saved robots, and the flags they make unnecessary.

Everything here exists because the tool used to need --host, --serial and --ca
on every single invocation. The tests are grouped by the promise each part
makes: resolve the right robot, lay flags over what was saved, and fail with a
sentence rather than a stack trace.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiomqtt
import pytest

from whiskerless.cli import _check_host, _check_ssid, _read_pem, main
from whiskerless.exceptions import ProfileError, ProvisioningError, WhiskerlessError
from whiskerless.profiles import ProfileStore, RobotProfile, Serial

CA = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"


@pytest.fixture(scope="module")
def _cli_loop() -> Any:
    """See tests/test_cli.py — `main` must not close the session's current loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _own_loop(_cli_loop: Any) -> Any:
    with patch("whiskerless.cli.asyncio.run", _cli_loop.run_until_complete):
        yield


@pytest.fixture
def store() -> ProfileStore:
    """The store the CLI will see (conftest points WHISKERLESS_HOME at a tmp dir)."""
    return ProfileStore.from_env()


def seed(store: ProfileStore, serial: str = "LR4C123456", **kwargs: object) -> RobotProfile:
    defaults: dict[str, object] = {"host": "192.0.2.10", "ca_pem": CA}
    defaults.update(kwargs)
    profile = RobotProfile(serial=Serial(serial), **defaults)  # type: ignore[arg-type]
    store.save(profile)
    return profile


def _run_async(coro: Any) -> Any:
    """Drive one coroutine to completion on a throwaway loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run(*argv: str, answer: str | None = None) -> int:
    if answer is None:
        return main(list(argv))
    with patch("builtins.input", return_value=answer):
        return main(list(argv))


# --- bare invocation ----------------------------------------------------------
def test_a_bare_command_orients_instead_of_erroring(capsys: pytest.CaptureFixture[str]) -> None:
    """It used to exit 2 with argparse's "the following arguments are required"."""
    assert run() == 0
    assert "Nothing is set up on this machine yet" in capsys.readouterr().out


def test_a_bare_command_names_the_robots_it_knows(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store, name="Upstairs")
    assert run() == 0
    assert "Upstairs" in capsys.readouterr().out


def test_version_is_reportable(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "whiskerless" in capsys.readouterr().out


# --- listing, choosing, forgetting --------------------------------------------
def test_robots_says_so_when_there_are_none(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("robots") == 0
    assert "run `whiskerless provision`" in capsys.readouterr().out


def test_robots_lists_what_is_saved(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store, "LR4C123456", name="Upstairs")
    seed(store, "LR4C654321", name="Downstairs")
    assert run("robots") == 0
    out = capsys.readouterr().out
    assert "Upstairs" in out and "Downstairs" in out


def test_robots_marks_an_unconfirmed_serial(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store)
    assert run("robots") == 0
    assert "unconfirmed" in capsys.readouterr().out


def test_robots_does_not_nag_about_a_confirmed_serial(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    store.save(RobotProfile(serial=Serial("LR4C123456", verified=True), host="192.0.2.10"))
    assert run("robots") == 0
    assert "unconfirmed" not in capsys.readouterr().out


# --- adopt --------------------------------------------------------------------
def test_adopt_saves_a_robot_that_was_never_provisioned_here(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The store only fills on a successful provision, so a robot set up before it
    existed has no profile — and re-provisioning to get one would touch the robot."""
    ca = tmp_path / "ca.crt"
    ca.write_text(CA)

    assert run("adopt", "--serial", "LR4C654321", "--host", "192.0.2.20",
               "--ca", str(ca), "--name", "Upstairs") == 0

    saved = store.load("LR4C654321")
    assert saved.host == "192.0.2.20"
    assert saved.name == "Upstairs"
    assert saved.ca_pem == CA
    assert saved.serial.verified is False, "nobody confirmed this serial; a typo is invisible"
    assert "whiskerless state" in capsys.readouterr().out, "and it says how to check"


def test_adopt_becomes_the_default_when_it_is_the_only_robot(store: ProfileStore) -> None:
    assert run("adopt", "--serial", "LR4C654321", "--host", "192.0.2.20") == 0
    assert store.get_default() == "LR4C654321"


def test_adopt_does_not_steal_the_default_from_an_existing_robot(store: ProfileStore) -> None:
    seed(store, "LR4C123456")
    store.set_default("LR4C123456")
    assert run("adopt", "--serial", "LR4C654321", "--host", "192.0.2.20") == 0
    assert store.get_default() == "LR4C123456"


def test_adopt_refuses_a_serial_that_cannot_be_one(store: ProfileStore) -> None:
    """A typo becomes the MQTT client-id and both topics, so it fails silently
    forever. The shape check is the only guard available without the robot."""
    assert run("adopt", "--serial", "nope!", "--host", "192.0.2.20") == 1


def test_adopt_refuses_the_model_number_from_the_same_label(store: ProfileStore) -> None:
    """The label carries LR4C123456 and LR4-0301-00-US side by side, and the
    store's own shape rule accepts the second one. Adoption has to apply the
    provisioner's check, or it writes the one value guaranteed never to work."""
    assert run("adopt", "--serial", "LR4-0301-00-US", "--host", "192.0.2.20") == 1


def test_adopt_again_does_not_wipe_what_it_was_not_given(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Correcting the host must not cost the CA, the name, or the litter
    reference someone measured with the globe in front of them."""
    seed(store, "LR4C123456", name="Upstairs", litter_full_mm=140)

    assert run("adopt", "--serial", "LR4C123456", "--host", "192.0.2.99") == 0

    saved = store.load("LR4C123456")
    assert saved.host == "192.0.2.99", "the field given is updated"
    assert saved.name == "Upstairs"
    assert saved.ca_pem == CA
    assert saved.litter_full_mm == 140


def test_adopt_refuses_a_ca_that_is_not_a_pem(store: ProfileStore, tmp_path: Path) -> None:
    junk = tmp_path / "not-a-ca.txt"
    junk.write_text("this is not a certificate")
    assert run("adopt", "--serial", "LR4C654321", "--host", "192.0.2.20", "--ca", str(junk)) == 1


def _adopt_answering(answers: list[str], *extra: str) -> tuple[int, list[str]]:
    """Run an interactive `adopt`, scripting the prompts. Returns prompts seen."""
    prompts: list[str] = []

    def _input(prompt: str = "") -> str:
        prompts.append(prompt)
        return answers.pop(0)

    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", _input):
        return main(["adopt", *extra]), prompts


def test_adopt_with_no_arguments_asks(store: ProfileStore, tmp_path: Path) -> None:
    """Someone reaching for adopt is usually meeting the tool for the first time,
    and argparse's "the following arguments are required" teaches them nothing."""
    ca = tmp_path / "ca.crt"
    ca.write_text(CA)
    # serial, broker, CA, username (skip), name
    # serial, broker, CA, name — there is no broker-username question any more
    code, prompts = _adopt_answering(["LR4C654321", "192.0.2.20", str(ca), "Upstairs"])
    assert code == 0
    saved = store.load("LR4C654321")
    assert (saved.host, saved.name, saved.ca_pem) == ("192.0.2.20", "Upstairs", CA)
    assert any("serial" in prompt for prompt in prompts)


def test_adopt_re_asks_a_serial_that_cannot_be_one(store: ProfileStore) -> None:
    """The model number is printed on the label beside the serial, and adopting it
    writes the one value guaranteed never to work."""
    code, _ = _adopt_answering(["LR4-0301-00-US", "LR4C654321", "192.0.2.20", "", ""])
    assert code == 0
    assert store.load("LR4C654321").host == "192.0.2.20"


def test_adopt_offers_the_setup_already_in_use(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store, "LR4C123456", host="192.0.2.10", name="Downstairs")
    # serial, then enter for broker and CA, then skip username and name.
    code, prompts = _adopt_answering(["LR4C654321", "", "", ""])
    assert code == 0
    saved = store.load("LR4C654321")
    assert saved.host == "192.0.2.10"
    assert saved.ca_pem == CA
    assert "the setup already in use here" in capsys.readouterr().out
    ca_prompt = next(prompt for prompt in prompts if "CA" in prompt)
    assert "BEGIN CERTIFICATE" not in ca_prompt, "a PEM blob in a prompt is unreadable"


def test_adopt_can_skip_the_ca(store: ProfileStore) -> None:
    """A broker on a certificate the system already trusts needs none."""
    code, prompts = _adopt_answering(["LR4C654321", "192.0.2.20", "", ""])
    assert code == 0
    assert store.load("LR4C654321").ca_pem is None
    assert any("enter to skip" in prompt for prompt in prompts if "CA" in prompt)


def test_adopt_without_a_terminal_names_the_flags_it_needs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A script gets an error about the arguments, not the EOF of a prompt it
    could never have answered."""
    assert run("adopt") == 1
    assert "--serial and --host" in capsys.readouterr().err


def test_use_marks_the_default(store: ProfileStore, capsys: pytest.CaptureFixture[str]) -> None:
    seed(store, "LR4C123456", name="Upstairs")
    seed(store, "LR4C654321")
    assert run("use", "LR4C123456") == 0
    assert "Upstairs is now the default" in capsys.readouterr().out
    assert run("robots") == 0
    assert "* Upstairs" in capsys.readouterr().out


def test_use_rejects_a_robot_that_is_not_saved(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("use", "LR4C999999") == 1
    assert "no saved profile" in capsys.readouterr().err


def test_forget_declined_at_the_prompt_keeps_the_profile(store: ProfileStore) -> None:
    seed(store)
    assert run("forget", "LR4C123456", answer="no") == 1
    assert store.list_profiles() != ()


def test_forget_confirmed_removes_it(store: ProfileStore) -> None:
    seed(store)
    assert run("forget", "LR4C123456", answer="yes") == 0
    assert store.list_profiles() == ()


def test_forget_yes_skips_the_prompt(store: ProfileStore) -> None:
    seed(store)
    assert run("forget", "LR4C123456", "--yes") == 0
    assert store.list_profiles() == ()


def test_forget_says_the_robot_keeps_running(store: ProfileStore) -> None:
    """The word "forget" could easily read as "un-provision"."""
    seed(store)
    with patch("builtins.input", return_value="no") as ask:
        main(["forget", "LR4C123456"])
    assert "the robot keeps running" in ask.call_args.args[0]


def test_robots_shows_a_damaged_profile(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corrupt entry the listing hides is one the user can never fix."""
    seed(store, "LR4C654321", name="Downstairs")
    seed(store, "LR4C123456")
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{bad", encoding="utf-8")
    assert run("robots") == 0
    out = capsys.readouterr().out
    assert "Downstairs" in out
    assert "LR4C123456" in out and "unreadable" in out


def test_forget_still_removes_a_damaged_profile(store: ProfileStore) -> None:
    """A profile too corrupt to load is exactly the one forget must handle."""
    seed(store)
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{bad", encoding="utf-8")
    assert run("forget", "LR4C123456", "--yes") == 0
    assert not (store.robots_dir / "LR4C123456").exists()


def test_forget_of_an_unknown_robot_is_still_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run("forget", "LR4C999999", "--yes") == 1
    assert "no saved profile" in capsys.readouterr().err


def test_use_refuses_a_damaged_profile_and_sets_no_default(store: ProfileStore) -> None:
    """Pointing every future bare command at an unloadable profile helps nobody."""
    seed(store, "LR4C654321")
    seed(store, "LR4C123456")
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{bad", encoding="utf-8")
    assert run("use", "LR4C123456") == 1
    assert store.get_default() is None


# --- resolving which robot to act on ------------------------------------------
def test_a_saved_robot_needs_no_flags_at_all(store: ProfileStore) -> None:
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_state(captured) == 0
    assert captured["serial"] == "LR4C123456"
    assert captured["settings"].host == "192.0.2.10"
    assert captured["settings"].ca_cert_data == CA


def test_the_default_decides_when_several_are_saved(store: ProfileStore) -> None:
    seed(store, "LR4C123456")
    seed(store, "LR4C654321")
    store.set_default("LR4C654321")
    captured: dict[str, Any] = {}
    assert _run_state(captured) == 0
    assert captured["serial"] == "LR4C654321"


def test_an_explicit_serial_wins_over_the_default(store: ProfileStore) -> None:
    seed(store, "LR4C123456")
    seed(store, "LR4C654321")
    store.set_default("LR4C654321")
    captured: dict[str, Any] = {}
    assert _run_state(captured, "--serial", "LR4C123456") == 0
    assert captured["serial"] == "LR4C123456"


def test_ambiguity_names_the_candidates(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store, "LR4C123456")
    seed(store, "LR4C654321")
    assert run("state") == 1
    err = capsys.readouterr().err
    assert "LR4C654321" in err and "LR4C123456" in err


def test_nothing_saved_and_no_flags_points_at_provisioning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run("state") == 1
    assert "run `whiskerless provision` first" in capsys.readouterr().err


def test_a_fully_explicit_invocation_still_works_with_an_empty_store() -> None:
    """How this behaved before there was a store, and how scripts still call it."""
    captured: dict[str, Any] = {}
    assert _run_state(captured, "--serial", "LR4C000001", "--host", "192.0.2.99") == 0
    assert captured["settings"].host == "192.0.2.99"


def test_a_host_without_a_serial_says_what_is_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """"Run provision first" would mislead someone who already gave the broker."""
    assert run("state", "--host", "192.0.2.99") == 1
    assert "add --serial" in capsys.readouterr().err


# --- flags override, but only where given -------------------------------------
def test_a_flag_overrides_just_its_own_field(store: ProfileStore) -> None:
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_state(captured, "--host", "10.0.0.9") == 0
    assert captured["settings"].host == "10.0.0.9"
    assert captured["settings"].ca_cert_data == CA


def test_an_unspecified_port_does_not_clobber_the_saved_one(store: ProfileStore) -> None:
    """Every flag defaults to None precisely so argparse cannot overwrite the profile."""
    seed(store, port=1883)
    captured: dict[str, Any] = {}
    assert _run_state(captured) == 0
    assert captured["settings"].port == 1883


def test_insecure_turns_off_hostname_checking(store: ProfileStore) -> None:
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_state(captured, "--insecure") == 0
    assert captured["settings"].verify_hostname is False


def test_a_ca_flag_is_read_and_replaces_the_saved_one(
    store: ProfileStore, tmp_path: Path
) -> None:
    seed(store)
    other = tmp_path / "other.pem"
    other.write_text("-----BEGIN CERTIFICATE-----\nother\n-----END CERTIFICATE-----\n")
    captured: dict[str, Any] = {}
    assert _run_state(captured, "--ca", str(other)) == 0
    assert "other" in (captured["settings"].ca_cert_data or "")


def test_the_client_id_is_never_the_robots_serial(store: ProfileStore) -> None:
    """Claiming the robot's id kicks the robot off its own broker connection."""
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_state(captured) == 0
    assert captured["settings"].client_id is None


def test_monitor_renders_a_state_document_it_is_pushed(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """`monitor` sees both message kinds; only activity had ever been exercised."""
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_link(captured, "monitor", "--duration", "5") == 0
    assert "state:" in capsys.readouterr().out


def test_monitor_names_the_robot_it_resolved(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """With the serial coming from the store, the banner read "monitoring None"."""
    seed(store, name="Upstairs")
    captured: dict[str, Any] = {}
    assert _run_link(captured, "monitor", "--duration", "5") == 0
    assert "monitoring Upstairs" in capsys.readouterr().out


# --- paths and error messages -------------------------------------------------
def test_a_tilde_path_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "ca.pem").write_text(CA)
    assert _read_pem("~/ca.pem") == CA


def test_a_missing_file_says_which_one_and_what_to_check() -> None:
    with pytest.raises(WhiskerlessError, match="no such file"):
        _read_pem("/nonexistent/nowhere.pem")


def test_a_readable_file_that_is_not_a_pem_is_rejected_at_the_prompt(tmp_path: Path) -> None:
    """A wrong-but-readable file used to survive this question and throw away
    every answer typed after it — including a password typed blind."""
    not_pem = tmp_path / "notes.txt"
    not_pem.write_text("not a certificate")
    with pytest.raises(WhiskerlessError, match="not a PEM certificate"):
        _read_pem(str(not_pem))


def test_a_binary_file_is_reported_not_a_unicode_traceback(tmp_path: Path) -> None:
    """A DER certificate is the likely paste-o here, and it is not UTF-8."""
    der = tmp_path / "ca.der"
    der.write_bytes(bytes([0x30, 0x82, 0xFF, 0xFE]))
    with pytest.raises(WhiskerlessError, match="could not read"):
        _read_pem(str(der))


class _DroppingLink:
    """A link whose stream dies the way a broker drop does mid-session."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _DroppingLink:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def request_state(self) -> None:
        return None

    async def messages(self) -> Any:
        raise aiomqtt.MqttError("Disconnected during message iteration")
        yield  # pragma: no cover - makes this an async generator


def test_a_broker_drop_mid_session_is_one_line_not_a_traceback(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The link wraps CONNECT failures; a drop after that surfaced raw."""
    seed(store)
    with patch("whiskerless.cli.LitterRobot4Link", _DroppingLink):
        assert run("monitor", "--duration", "5") == 1
    assert "lost the broker connection" in capsys.readouterr().err


def test_a_broker_drop_still_traces_back_under_debug(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(store)
    monkeypatch.setenv("WHISKERLESS_DEBUG", "1")
    with patch("whiskerless.cli.LitterRobot4Link", _DroppingLink), pytest.raises(aiomqtt.MqttError):
        run("monitor", "--duration", "5")


def test_an_unreadable_file_is_reported_not_raised_raw(tmp_path: Path) -> None:
    directory = tmp_path / "a-directory.pem"
    directory.mkdir()
    with pytest.raises(WhiskerlessError, match="could not read"):
        _read_pem(str(directory))


def test_a_bad_ca_path_exits_cleanly_rather_than_tracing_back(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store)
    assert run("state", "--ca", "/nonexistent/nowhere.pem") == 1
    assert "whiskerless: no such file" in capsys.readouterr().err


def test_debug_re_raises_so_a_bug_report_has_a_traceback(store: ProfileStore) -> None:
    seed(store)
    with pytest.raises(WhiskerlessError):
        main(["state", "--debug", "--ca", "/nonexistent/nowhere.pem"])


def test_the_debug_environment_variable_does_the_same(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(store)
    monkeypatch.setenv("WHISKERLESS_DEBUG", "1")
    with pytest.raises(WhiskerlessError):
        main(["state", "--ca", "/nonexistent/nowhere.pem"])


def test_an_os_error_becomes_a_message(store: ProfileStore, capsys: pytest.CaptureFixture[str]) -> None:
    seed(store)
    with patch("whiskerless.cli._link", side_effect=OSError(13, "Permission denied")):
        assert run("state") == 1
    assert "Permission denied" in capsys.readouterr().err


def test_an_os_error_still_traces_back_under_debug(store: ProfileStore) -> None:
    seed(store)
    with (
        patch("whiskerless.cli._link", side_effect=OSError(13, "Permission denied")),
        pytest.raises(OSError, match="Permission denied"),
    ):
        main(["state", "--debug"])


def test_an_interrupt_is_reported_as_an_abort(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store)
    with patch("whiskerless.cli._link", side_effect=KeyboardInterrupt):
        assert run("state") == 130
    assert "aborted" in capsys.readouterr().err


# --- prompt-time validation ---------------------------------------------------
@pytest.mark.parametrize("bad", ["", "http://192.168.1.10/", "192.168.1.10 8883"])
def test_a_host_that_is_not_a_host_is_rejected(bad: str) -> None:
    with pytest.raises(WhiskerlessError):
        _check_host(bad)


def test_a_plain_address_passes() -> None:
    assert _check_host("192.168.1.10") == "192.168.1.10"


def test_an_empty_ssid_is_rejected() -> None:
    with pytest.raises(WhiskerlessError, match="SSID is required"):
        _check_ssid("")


def test_an_ssid_passes_through_untouched() -> None:
    assert _check_ssid("MyIoT") == "MyIoT"


def test_a_bad_answer_is_re_asked_rather_than_fatal(capsys: pytest.CaptureFixture[str]) -> None:
    """The point of validating at the prompt: a typo costs one line, not five."""
    from whiskerless.cli import _ask

    with patch("builtins.input", side_effect=["", "192.168.1.10"]):
        assert _ask("host: ", None, _check_host) == "192.168.1.10"
    assert "required" in capsys.readouterr().err


def test_a_bad_value_from_the_command_line_is_fatal() -> None:
    """Nobody is at a prompt to correct it, so re-asking would loop forever."""
    from whiskerless.cli import _ask

    with pytest.raises(WhiskerlessError):
        _ask("host: ", "", _check_host)


def test_input_that_ends_mid_prompt_is_an_error_not_a_hang() -> None:
    from whiskerless.cli import _ask

    with (
        patch("builtins.input", side_effect=EOFError),
        pytest.raises(WhiskerlessError, match="input ended"),
    ):
        _ask("host: ", None, _check_host)


# --- serial validation --------------------------------------------------------
def test_the_model_number_is_not_accepted_as_a_serial() -> None:
    """The REAL designator, not a strawman: LR4-0301-00-US is long enough and
    carries enough digits to pass every shape check — the hyphen is the tell."""
    from whiskerless.ble.provision import ProvisioningConfig

    with pytest.raises(ProvisioningError, match="looks like the model number"):
        ProvisioningConfig.check_serial("LR4-0301-00-US")
    with pytest.raises(ProvisioningError, match="looks like the model number"):
        ProvisioningConfig.check_serial("LR4C")


def test_a_real_serial_is_normalized() -> None:
    from whiskerless.ble.provision import ProvisioningConfig

    assert ProvisioningConfig.check_serial(" lr4c123456 ") == "LR4C123456"


def test_another_model_is_refused_outright() -> None:
    from whiskerless.ble.provision import ProvisioningConfig

    with pytest.raises(ProvisioningError, match="only supports the LR4"):
        ProvisioningConfig.check_serial("LR3C123456")


# --- helper -------------------------------------------------------------------
def _run_link(captured: dict[str, Any], *argv: str) -> int:
    """Run any link-backed command against a link that pushes one state document."""
    return _run_state(captured, _argv=list(argv))


def _run_state(captured: dict[str, Any], *extra: str, _argv: list[str] | None = None) -> int:
    """Run `state`, capturing the settings and serial the CLI resolved."""

    class Recorder:
        def __init__(self, settings: Any, serial: str, **_: object) -> None:
            captured["settings"] = settings
            captured["serial"] = serial

        async def __aenter__(self) -> Recorder:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def request_state(self) -> None:
            return None

        async def messages(self) -> Any:  # pragma: no cover - replaced below
            return None

    async def _one_state(self: Any) -> Any:
        from whiskerless.devices.litter_robot_4.models import LitterRobot4State
        from whiskerless.devices.litter_robot_4.protocol import StateMessage

        yield StateMessage(state=LitterRobot4State(raw={}), raw={})

    Recorder.messages = _one_state  # type: ignore[assignment]
    with patch("whiskerless.cli.LitterRobot4Link", Recorder):
        return main(_argv if _argv is not None else ["state", *extra])


def test_reprovisioning_keeps_the_metadata_it_never_asked_for(
    store: ProfileStore, tmp_path: Path
) -> None:
    """provision collects the serial, broker, CA and WiFi — not the name, the
    broker credentials or the port. Writing defaults over those on a
    reprovision silently erased what the user had set up."""
    seed(store, name="Upstairs", port=1884)
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.99",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    saved = store.load("LR4C123456")
    assert saved.host == "192.0.2.99", "what provisioning collected does move"
    assert saved.display_name == "Upstairs"
    assert saved.port == 1884


def test_provisioning_saves_a_profile_that_later_commands_find(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.10",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret",
        "--name", "Upstairs", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    saved = store.resolve("LR4C123456")
    assert saved.host == "192.0.2.10"
    assert saved.ca_pem == CA
    assert saved.display_name == "Upstairs"
    assert "saved as Upstairs" in capsys.readouterr().out


def test_a_failed_provisioning_saves_nothing(store: ProfileStore, tmp_path: Path) -> None:
    """A profile claiming a robot is reachable where it is not is worse than none."""
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.10",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=False)),
    ):
        assert main(argv) == 1
    with pytest.raises(ProfileError):
        store.load("LR4C123456")


def test_a_dry_run_saves_nothing_and_says_so(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.10",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret",
        "--dry-run", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=False)),
    ):
        assert main(argv) == 0
    assert "DRY RUN" in capsys.readouterr().out
    with pytest.raises(ProfileError):
        store.load("LR4C123456")


def test_the_first_robot_provisioned_becomes_the_default(
    store: ProfileStore, tmp_path: Path
) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.10",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    assert store.get_default() == "LR4C123456"


def test_provisioning_a_second_robot_leaves_the_default_alone(
    store: ProfileStore, tmp_path: Path
) -> None:
    seed(store, "LR4C654321")
    store.set_default("LR4C654321")
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.10",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    assert store.get_default() == "LR4C654321"


def test_a_store_that_cannot_be_written_does_not_fail_the_provisioning(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The robot is already changed; a convenience file must not undo that verdict."""
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.10",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
        patch.object(ProfileStore, "save", side_effect=OSError(13, "Permission denied")),
    ):
        assert main(argv) == 0
    assert "could not save the profile" in capsys.readouterr().err


# --- a second robot inherits the first one's setup ----------------------------
def _provision_answering(answers: list[str], *extra: str) -> tuple[int, list[str]]:
    """Run an interactive `provision`, scripting the prompts. Returns prompts seen."""
    prompts: list[str] = []

    def _input(prompt: str = "") -> str:
        prompts.append(prompt)
        return answers.pop(0)

    with (
        patch("builtins.input", _input),
        patch("whiskerless.cli.getpass.getpass", return_value="wifi-secret"),
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        return main(["provision", "--yes", *extra]), prompts


def test_a_second_robot_is_offered_the_first_ones_broker(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store, "LR4C654321", host="192.0.2.10", name="Downstairs", wifi_ssid="MyIoT")
    # serial, then enter three times to accept broker / CA / SSID.
    code, prompts = _provision_answering(["LR4C123456", "", "", ""])
    assert code == 0
    saved = store.load("LR4C123456")
    assert saved.host == "192.0.2.10"
    assert saved.ca_pem == CA
    assert saved.wifi_ssid == "MyIoT"
    assert "the setup already in use here" in capsys.readouterr().out
    assert any("192.0.2.10" in prompt for prompt in prompts)


def test_the_offered_ca_is_described_not_dumped(store: ProfileStore) -> None:
    """The stored CA is contents, and a PEM blob in a prompt is unreadable."""
    seed(store, "LR4C654321", name="Downstairs")
    _, prompts = _provision_answering(["LR4C123456", "", "", "MyIoT"])
    ca_prompt = next(prompt for prompt in prompts if "CA" in prompt)
    assert "BEGIN CERTIFICATE" not in ca_prompt
    assert "the CA already in use here" in ca_prompt


def test_a_shared_ca_is_never_attributed_to_one_robot(store: ProfileStore) -> None:
    """Naming a robot implies the CA is per-robot; with several sharing it, it is not."""
    for serial in ("LR4C111111", "LR4C222222", "LR4C333333"):
        seed(store, serial, name=f"Robot {serial[-1]}")
    _, prompts = _provision_answering(["LR4C123456", "", "", "MyIoT"])
    ca_prompt = next(prompt for prompt in prompts if "CA" in prompt)
    assert "the CA already in use here" in ca_prompt
    assert not any(name in ca_prompt for name in ("Robot 1", "Robot 2", "Robot 3"))


def test_robots_that_disagree_fall_back_to_naming_the_source(store: ProfileStore) -> None:
    """Only when the CAs genuinely differ is naming one of them informative."""
    seed(store, "LR4C111111", name="Garage", ca_pem=CA)
    seed(store, "LR4C222222", name="Attic", ca_pem="-----BEGIN CERTIFICATE-----\nB\n-----END CERTIFICATE-----\n")
    store.set_default("LR4C222222")
    _, prompts = _provision_answering(["LR4C123456", "", "", "MyIoT"])
    ca_prompt = next(prompt for prompt in prompts if "CA" in prompt)
    assert "the CA saved for Attic" in ca_prompt


def test_a_robot_with_no_ca_does_not_veto_the_shared_offer(store: ProfileStore) -> None:
    seed(store, "LR4C111111", ca_pem=CA)
    store.save(RobotProfile(serial=Serial("LR4C222222"), host="192.0.2.10"))
    _, prompts = _provision_answering(["LR4C123456", "", "", "MyIoT"])
    ca_prompt = next(prompt for prompt in prompts if "CA" in prompt)
    assert "the CA already in use here" in ca_prompt


def test_the_offer_can_be_overridden_by_typing(store: ProfileStore, tmp_path: Path) -> None:
    seed(store, "LR4C654321", host="192.0.2.10", wifi_ssid="MyIoT")
    other = tmp_path / "other.pem"
    other.write_text("-----BEGIN CERTIFICATE-----\nother\n-----END CERTIFICATE-----\n")
    code, _ = _provision_answering(
        ["LR4C123456", "10.0.0.9", str(other), "OtherNet"]
    )
    assert code == 0
    saved = store.load("LR4C123456")
    assert saved.host == "10.0.0.9"
    assert "other" in (saved.ca_pem or "")
    assert saved.wifi_ssid == "OtherNet"


def test_the_first_robot_is_offered_nothing(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    code, _ = _provision_answering(["LR4C123456", "192.0.2.10", str(ca), "MyIoT"])
    assert code == 0
    assert "reusing the setup" not in capsys.readouterr().out


def test_the_wifi_passphrase_is_never_stored(store: ProfileStore) -> None:
    """A home WiFi secret is a bigger thing to leave on disk than a broker login."""
    seed(store, "LR4C654321", wifi_ssid="MyIoT")
    assert _provision_answering(["LR4C123456", "", "", ""])[0] == 0
    saved = (store.robots_dir / "LR4C123456" / "profile.json").read_text()
    assert "wifi-secret" not in saved


def test_an_ssid_is_still_asked_for_when_the_prior_robot_has_none(
    store: ProfileStore,
) -> None:
    seed(store, "LR4C654321")  # saved before wifi_ssid was recorded
    code, prompts = _provision_answering(["LR4C123456", "", "", "MyIoT"])
    assert code == 0
    assert store.load("LR4C123456").wifi_ssid == "MyIoT"
    assert any(prompt.startswith("WiFi SSID: ") for prompt in prompts)


def test_the_default_robot_is_the_one_whose_setup_is_offered(store: ProfileStore) -> None:
    seed(store, "LR4C111111", host="10.0.0.1")
    seed(store, "LR4C999999", host="10.0.0.2")
    store.set_default("LR4C999999")
    assert _provision_answering(["LR4C123456", "", "", "MyIoT"])[0] == 0
    assert store.load("LR4C123456").host == "10.0.0.2"


async def _fake_scan(**_: object) -> list[Any]:
    from whiskerless.ble.transport import DiscoveredRobot

    return [DiscoveredRobot(address="AA:BB:CC:DD:EE:FF", name="LitterRobot", rssi=-40)]


async def _fake_mac(*_: object, **__: object) -> str:
    return "aa:bb:cc:dd:ee:ff"


def _fake_provision(*, success: bool) -> Any:
    async def _provision(*_: object, **kwargs: object) -> Any:
        from whiskerless.ble.provision import ProvisioningResult

        return ProvisioningResult(
            success=success, message="done" if success else "failed"
        )

    return _provision


def _provision_argv(ca: Path, *extra: str) -> list[str]:
    return [
        "provision", "--serial", "LR4C123456", "--host-ip", "192.0.2.10",
        "--ca", str(ca), "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes", *extra,
    ]


def _provisioned(argv: list[str], answer: str | None = None) -> int:
    patches = [
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ]
    if answer is not None:
        patches += [patch("sys.stdin.isatty", return_value=True),
                    patch("builtins.input", return_value=answer)]
    with patches[0], patches[1], patches[2]:
        if answer is None:
            return main(argv)
        with patches[3], patches[4]:
            return main(argv)


def test_an_optional_question_still_fails_loudly_on_a_closed_terminal() -> None:
    """Skipping applies to a run that was never interactive. A terminal that
    disappears mid-prompt is a different thing, and guessing an answer there
    would write a profile nobody agreed to."""
    from whiskerless.cli import _ask_optional

    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", side_effect=EOFError),
        pytest.raises(WhiskerlessError, match="input ended"),
    ):
        _ask_optional("broker username", None, None)


# --- choosing a network from what the robot can see ---------------------------
def _networks() -> list[Any]:
    from whiskerless.ble.messages import WifiNetwork

    return [
        WifiNetwork(ssid="Near", channel=1, rssi=-40, secured=True),
        WifiNetwork(ssid="Far", channel=11, rssi=-80, secured=False),
    ]


def test_a_robot_that_sees_nothing_falls_back_to_typing() -> None:
    """Hidden SSIDs are real and the robot joins them fine; it just cannot list
    them. Falling back beats refusing."""
    from whiskerless.cli import _choose_network

    answers = iter(["Hidden", ""])
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _prompt="": next(answers)),
        patch("whiskerless.cli.getpass.getpass", return_value="pw"),
    ):
        assert _run_async(_choose_network([])) == ("Hidden", "pw")


def test_a_hidden_network_can_be_typed_instead_of_picked() -> None:
    from whiskerless.cli import _choose_network

    answers = iter(["-", "Hidden", ""])
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _prompt="": next(answers)),
        patch("whiskerless.cli.getpass.getpass", return_value="pw"),
    ):
        assert _run_async(_choose_network(_networks())) == ("Hidden", "pw")


def test_a_nonsense_selection_just_asks_again() -> None:
    from whiskerless.cli import _choose_network

    answers = iter(["nope", "99", "1", ""])
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _prompt="": next(answers)),
        patch("whiskerless.cli.getpass.getpass", return_value="pw"),
    ):
        assert _run_async(_choose_network(_networks()))[0] == "Far"


def test_input_ending_at_the_network_list_is_an_error() -> None:
    """A pipe must fail with a sentence, not hang or pick something."""
    from whiskerless.cli import _choose_network

    with patch("builtins.input", side_effect=EOFError), pytest.raises(WhiskerlessError):
        _run_async(_choose_network(_networks()))


def test_the_list_is_shown_strongest_first(capsys: pytest.CaptureFixture[str]) -> None:
    from whiskerless.cli import _choose_network

    answers = iter(["0", ""])
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _prompt="": next(answers)),
        patch("whiskerless.cli.getpass.getpass", return_value="pw"),
    ):
        _run_async(_choose_network(_networks()))
    out = capsys.readouterr().out
    assert out.index("Near") < out.index("Far")


def test_a_named_network_still_gets_its_passphrase_asked_for(store: ProfileStore) -> None:
    """--wifi-ssid skips the chooser, so the passphrase prompt has to happen up
    front or the robot is provisioned with an empty one."""
    seed(store, "LR4C654321", wifi_ssid="MyIoT")
    asked: list[str] = []

    def _record(_prompt: str) -> str:
        asked.append("typed-pw")
        return "typed-pw"

    answers = iter([""] * 3)  # broker, CA, then the network list is skipped
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _prompt="": next(answers)),
        patch("whiskerless.cli.getpass.getpass", _record),
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(["provision", "--serial", "LR4C123456", "--wifi-ssid", "MyIoT", "--yes"]) == 0
    assert asked == ["typed-pw"], "the passphrase is asked for, never stored"


def test_a_supplied_passphrase_survives_the_network_chooser() -> None:
    """--wifi-pass with no SSID still needs the list, but must not be overwritten."""
    from whiskerless.ble.messages import WifiNetwork
    from whiskerless.cli import _choose_network

    networks = [WifiNetwork(ssid="Near", channel=1, rssi=-40, secured=True)]

    def _explode(_prompt: str) -> str:
        raise AssertionError("prompted for a passphrase that was given on the command line")

    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _prompt="": "0"),
        patch("whiskerless.cli.getpass.getpass", _explode),
    ):
        assert _run_async(_choose_network(networks, "from-a-flag")) == ("Near", "from-a-flag")


def test_an_open_network_is_never_asked_for_a_password() -> None:
    """Asking for a password a network does not have invites someone to invent one."""
    from whiskerless.ble.messages import WifiNetwork
    from whiskerless.cli import _choose_network

    networks = [WifiNetwork(ssid="Cafe", channel=1, rssi=-50, secured=False)]

    def _explode(_prompt: str) -> str:
        raise AssertionError("asked for a passphrase on an open network")

    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _prompt="": "0"),
        patch("whiskerless.cli.getpass.getpass", _explode),
    ):
        assert _run_async(_choose_network(networks)) == ("Cafe", "")
