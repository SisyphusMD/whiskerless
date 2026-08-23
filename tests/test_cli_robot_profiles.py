"""The CLI's memory: saved robots, and the flags they make unnecessary.

Everything here exists because the tool used to need --host, --serial and --ca
on every single invocation. The tests are grouped by the promise each part
makes: resolve the right robot, lay flags over what was saved, and fail with a
sentence rather than a stack trace.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import replace
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import aiomqtt
import pytest

from whiskerless.cli import _check_host, _check_ssid, _pick_saved_robot, _profile, _read_pem, main
from whiskerless.cli import _store as cli_store
from whiskerless.exceptions import ProvisioningError, RobotProfileError, WhiskerlessError
from whiskerless.robot_profiles import AuthMode, Broker, RobotProfile, RobotProfileStore, Serial

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
def store() -> RobotProfileStore:
    """The store the CLI will see (conftest points WHISKERLESS_HOME at a tmp dir)."""
    return RobotProfileStore.from_env()


def seed(store: RobotProfileStore, serial: str = "LR4C123456", **kwargs: object) -> RobotProfile:
    """A saved robot, plus the one broker and CA every robot in a store shares."""
    if not store.has_broker():
        store.save_broker(Broker(host="192.0.2.10"))
    if not store.has_ca():
        from whiskerless import pki

        # A real authority, key included: every provision issues the robot a
        # certificate now, so a store that cannot sign is not one provision runs on.
        store.save_ca(pki.generate_ca())

    defaults: dict[str, object] = {}
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


@cache
def _shared_ca_file() -> str:
    """A CA file on disk for helpers that have no tmp_path of their own."""
    path = Path(tempfile.mkdtemp()) / "ca.pem"
    path.write_text(CA)
    return str(path)


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
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
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
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store, "LR4C123456", name="Upstairs")
    seed(store, "LR4C654321", name="Downstairs")
    assert run("robots") == 0
    out = capsys.readouterr().out
    assert "Upstairs" in out and "Downstairs" in out


def test_robots_marks_an_unconfirmed_serial(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store)
    assert run("robots") == 0
    assert "unconfirmed" in capsys.readouterr().out


def test_robots_does_not_nag_about_a_confirmed_serial(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    store.save(RobotProfile(serial=Serial("LR4C123456", verified=True)))
    assert run("robots") == 0
    assert "unconfirmed" not in capsys.readouterr().out


def test_use_marks_the_default(store: RobotProfileStore, capsys: pytest.CaptureFixture[str]) -> None:
    seed(store, "LR4C123456", name="Upstairs")
    seed(store, "LR4C654321")
    assert run("use", "LR4C123456") == 0
    assert "Upstairs is now the default" in capsys.readouterr().out
    assert run("robots") == 0
    assert "* Upstairs" in capsys.readouterr().out


def test_use_rejects_a_robot_that_is_not_saved(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("use", "LR4C999999") == 1
    assert "no saved profile" in capsys.readouterr().err


def test_forget_declined_at_the_prompt_keeps_the_profile(store: RobotProfileStore) -> None:
    seed(store)
    assert run("forget", "LR4C123456", answer="no") == 1
    assert store.list_robot_profiles() != ()


def test_forget_confirmed_removes_it(store: RobotProfileStore) -> None:
    seed(store)
    assert run("forget", "LR4C123456", answer="yes") == 0
    assert store.list_robot_profiles() == ()


def test_forget_yes_skips_the_prompt(store: RobotProfileStore) -> None:
    seed(store)
    assert run("forget", "LR4C123456", "--yes") == 0
    assert store.list_robot_profiles() == ()


def test_forget_says_the_robot_keeps_running(store: RobotProfileStore) -> None:
    """The word "forget" could easily read as "un-provision"."""
    seed(store)
    with patch("builtins.input", return_value="no") as ask:
        main(["forget", "LR4C123456"])
    assert "the robot keeps running" in ask.call_args.args[0]


def test_robots_shows_a_damaged_profile(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corrupt entry the listing hides is one the user can never fix."""
    seed(store, "LR4C654321", name="Downstairs")
    seed(store, "LR4C123456")
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{bad", encoding="utf-8")
    assert run("robots") == 0
    out = capsys.readouterr().out
    assert "Downstairs" in out
    assert "LR4C123456" in out and "unreadable" in out


def test_forget_still_removes_a_damaged_profile(store: RobotProfileStore) -> None:
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


def test_use_refuses_a_damaged_profile_and_sets_no_default(store: RobotProfileStore) -> None:
    """Pointing every future bare command at an unloadable profile helps nobody."""
    seed(store, "LR4C654321")
    seed(store, "LR4C123456")
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{bad", encoding="utf-8")
    assert run("use", "LR4C123456") == 1
    assert store.get_default() is None


# --- resolving which robot to act on ------------------------------------------
def test_a_saved_robot_needs_no_flags_at_all(store: RobotProfileStore) -> None:
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_state(captured) == 0
    assert captured["serial"] == "LR4C123456"
    # Whatever the store holds, not a fixed literal: `seed` generates a real
    # authority now, because a store that cannot sign is not one this works on.
    assert captured["settings"].ca_cert_data == store.ca_path.read_text(encoding="utf-8")


def test_the_default_decides_when_several_are_saved(store: RobotProfileStore) -> None:
    seed(store, "LR4C123456")
    seed(store, "LR4C654321")
    store.set_default("LR4C654321")
    captured: dict[str, Any] = {}
    assert _run_state(captured) == 0
    assert captured["serial"] == "LR4C654321"


def test_an_explicit_serial_wins_over_the_default(store: RobotProfileStore) -> None:
    seed(store, "LR4C123456")
    seed(store, "LR4C654321")
    store.set_default("LR4C654321")
    captured: dict[str, Any] = {}
    assert _run_state(captured, "--serial", "LR4C123456") == 0
    assert captured["serial"] == "LR4C123456"


def test_ambiguity_names_the_candidates(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
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


# --- flags override, but only where given -------------------------------------
def test_the_client_id_is_never_the_robots_serial(store: RobotProfileStore) -> None:
    """Claiming the robot's id kicks the robot off its own broker connection."""
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_state(captured) == 0
    assert captured["settings"].client_id is None


def test_monitor_renders_a_state_document_it_is_pushed(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """`monitor` sees both message kinds; only activity had ever been exercised."""
    seed(store)
    captured: dict[str, Any] = {}
    assert _run_link(captured, "monitor", "--duration", "5") == 0
    assert "state:" in capsys.readouterr().out


def test_monitor_names_the_robot_it_resolved(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
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
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The link wraps CONNECT failures; a drop after that surfaced raw."""
    seed(store)
    with patch("whiskerless.cli.LitterRobot4Link", _DroppingLink):
        assert run("monitor", "--duration", "5") == 1
    assert "lost the broker connection" in capsys.readouterr().err


def test_a_broker_drop_still_traces_back_under_debug(
    store: RobotProfileStore, monkeypatch: pytest.MonkeyPatch
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


def test_debug_re_raises_so_a_bug_report_has_a_traceback(store: RobotProfileStore) -> None:
    with pytest.raises(WhiskerlessError):
        main(["state", "--debug"])  # nothing set up: a RobotProfileError


def test_the_debug_environment_variable_does_the_same(
    store: RobotProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WHISKERLESS_DEBUG", "1")
    with pytest.raises(WhiskerlessError):
        main(["state"])


def test_an_os_error_becomes_a_message(store: RobotProfileStore, capsys: pytest.CaptureFixture[str]) -> None:
    seed(store)
    with patch("whiskerless.cli._link", side_effect=OSError(13, "Permission denied")):
        assert run("state") == 1
    assert "Permission denied" in capsys.readouterr().err


def test_an_os_error_still_traces_back_under_debug(store: RobotProfileStore) -> None:
    seed(store)
    with (
        patch("whiskerless.cli._link", side_effect=OSError(13, "Permission denied")),
        pytest.raises(OSError, match="Permission denied"),
    ):
        main(["state", "--debug"])


def test_an_interrupt_is_reported_as_an_abort(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
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
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """provision collects the serial, broker, CA and WiFi — not the name, the
    broker credentials or the port. Writing defaults over those on a
    reprovision silently erased what the user had set up."""
    _prepared(store)
    seed(store, name="Upstairs", litter_full_mm=140)
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    saved = store.load("LR4C123456")
    assert saved.display_name == "Upstairs"


def test_provisioning_saves_a_profile_that_later_commands_find(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepared(store)
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret",
        "--name", "Upstairs", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    saved = store.resolve("LR4C123456")
    assert saved.display_name == "Upstairs"
    assert "saved as Upstairs" in capsys.readouterr().out


def test_a_failed_provisioning_saves_nothing(store: RobotProfileStore, tmp_path: Path) -> None:
    """A profile claiming a robot is reachable where it is not is worse than none."""
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=False)),
    ):
        assert main(argv) == 1
    with pytest.raises(RobotProfileError):
        store.load("LR4C123456")


def test_a_dry_run_saves_nothing_and_says_so(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepared(store)
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456", "--wifi-ssid", "home", "--wifi-pass", "secret",
        "--dry-run", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=False)),
    ):
        assert main(argv) == 0
    assert "DRY RUN" in capsys.readouterr().out
    with pytest.raises(RobotProfileError):
        store.load("LR4C123456")


def test_the_first_robot_provisioned_becomes_the_default(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    _prepared(store)
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    assert store.get_default() == "LR4C123456"


def test_provisioning_a_second_robot_leaves_the_default_alone(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    seed(store, "LR4C654321")
    store.set_default("LR4C654321")
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(argv) == 0
    assert store.get_default() == "LR4C654321"


def test_a_store_that_cannot_be_written_does_not_fail_the_provisioning(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The robot is already changed; a convenience file must not undo that verdict."""
    _prepared(store)
    ca = tmp_path / "ca.pem"
    ca.write_text(CA)
    argv = [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes",
    ]
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
        patch.object(RobotProfileStore, "save", side_effect=OSError(13, "Permission denied")),
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


def test_the_wifi_passphrase_is_never_stored(store: RobotProfileStore) -> None:
    """A home WiFi secret is a bigger thing to leave on disk than a broker login."""
    seed(store, "LR4C654321", wifi_ssid="MyIoT")
    assert _provision_answering(["LR4C123456", "", "", ""])[0] == 0
    saved = (store.robots_dir / "LR4C123456" / "profile.json").read_text()
    assert "wifi-secret" not in saved


def test_an_ssid_is_still_asked_for_when_the_prior_robot_has_none(
    store: RobotProfileStore,
) -> None:
    seed(store, "LR4C654321")  # saved before wifi_ssid was recorded
    code, prompts = _provision_answering(["LR4C123456", "", "", "MyIoT"])
    assert code == 0
    assert store.load("LR4C123456").wifi_ssid == "MyIoT"
    assert any(prompt.startswith("WiFi SSID: ") for prompt in prompts)


async def _fake_scan(**_: object) -> list[Any]:
    from whiskerless.ble.transport import DiscoveredRobot

    return [DiscoveredRobot(address="AA:BB:CC:DD:EE:FF", name="LitterRobot", rssi=-40)]


async def _fake_mac(*_: object, **__: object) -> str:
    return "aa:bb:cc:dd:ee:ff"


def _fake_provision(*, success: bool) -> Any:
    """Stands in for the BLE work, but still drives the callbacks the CLI passes.

    The confirmation screen and the network chooser both live inside
    `provision_robot` now — the network cannot be known until the BLE link is
    open — so a fake that ignored them would silently skip the very output these
    tests assert on.
    """

    async def _provision(*_a: object, **kwargs: object) -> Any:
        from whiskerless.ble.provision import ProvisioningResult

        config = _a[1] if len(_a) > 1 else kwargs.get("config")
        chooser = kwargs.get("choose_network")
        if chooser is not None and config is not None and not config.wifi_ssid:
            config.wifi_ssid, config.wifi_pass = await chooser([])  # type: ignore[operator]
        confirm = kwargs.get("confirm")
        if confirm is not None and config is not None and not confirm(config, "30:c9:22:27:1d:34"):  # type: ignore[operator]
            return ProvisioningResult(
                success=False, message="aborted before anything was written"
            )
        return ProvisioningResult(
            success=success, message="done" if success else "failed"
        )

    return _provision


def _provision_argv(ca: Path, *extra: str) -> list[str]:
    """A provision on a machine that `setup` has already prepared."""
    store = RobotProfileStore.from_env()
    if not store.has_broker():
        store.save_broker(Broker(host="192.0.2.10"))
    if not store.has_ca_cert():
        store.save_ca_cert_only(ca.read_text())
    return [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes", *extra,
    ]


def _prepared(store: RobotProfileStore | None = None, *, with_key: bool = True) -> None:
    """What `whiskerless setup` leaves behind, without running it.

    Always with a key: since 0.2.0 setup cannot finish without one, so a store
    without it is not a state this helper can produce.
    """
    from whiskerless import pki

    store = store or RobotProfileStore.from_env()
    if not store.has_broker():
        store.save_broker(Broker(host="192.0.2.10"))
    if not store.has_ca():
        if with_key:
            store.save_ca(pki.generate_ca())
        else:
            store.save_ca_cert_only(CA)


def _provisioned(argv: list[str], answer: str | None = None) -> int:
    _prepared()
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


def test_a_named_network_still_gets_its_passphrase_asked_for(store: RobotProfileStore) -> None:
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


# --- what the robot gets for an identity --------------------------------------
def _provision_output(store: RobotProfileStore, *extra: str) -> str:
    _prepared(store)
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        main(["provision", "--serial", "LR4C123456",
              "--wifi-ssid", "home", "--wifi-pass", "pw", "--yes", *extra])
    return ""


def test_a_ca_we_can_sign_with_means_the_robot_gets_our_identity(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    _provision_output(store)
    out = capsys.readouterr().out
    assert "NO CA KEY" not in out
    assert "issued by your CA, CN=LR4C123456" in out


def test_every_robot_gets_an_identity_with_no_way_to_opt_out(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--no-client-cert` is gone.

    The store holds a signing key by definition now, so leaving a robot on its
    factory identity bought nothing: a robot WITH a certificate still connects to
    a listener that does not ask for one, while a robot without one cannot connect
    to a listener that does. The flag only created a way to end up unable to
    tighten the broker later, discovered at the robot."""
    # argparse exits rather than returning, so the flag is gone at the parser.
    with pytest.raises(SystemExit) as exited:
        main(["provision", "--no-client-cert", "--serial", "LR4C123456"])
    assert exited.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err

    _provision_output(store)
    assert "issued by your CA, CN=LR4C123456" in capsys.readouterr().out


# --- setting up a certificate authority on a fresh machine --------------------
def _ca_files(tmp_path: Path, *, with_key: bool = True) -> tuple[str, str | None]:
    from whiskerless import pki

    ca = pki.generate_ca("someone else's CA")
    cert = tmp_path / "their-ca.crt"
    cert.write_text(ca.cert_pem)
    if not with_key:
        return str(cert), None
    key = tmp_path / "their-ca.key"
    key.write_text(ca.key_pem)
    return str(cert), str(key)


def _first_run(store: RobotProfileStore, answers: list[str], *extra: str) -> None:
    """Interactive `setup`, then a provision — the order a first-time user takes."""
    it = iter(answers)
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": next(it)),
        patch("whiskerless.cli.getpass.getpass", return_value="pw"),
    ):
        main(["setup", "--host", "192.0.2.10", *extra])
    if not RobotProfileStore.from_env().has_ca_cert():
        return  # setup declined or failed; nothing to provision onto
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        main(["provision", "--serial", "LR4C123456",
              "--wifi-ssid", "home", "--wifi-pass", "pw", "--yes"])


def test_a_fresh_machine_is_offered_a_certificate_authority(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Enter generates everything: a first-time user should not have to learn
    openssl before their litter box works."""
    _first_run(store, [""])
    out = capsys.readouterr().out
    assert "NO CERTIFICATE AUTHORITY" in out
    assert store.has_ca(), "the CA is on disk afterwards"
    assert store.has_client(), "so is this machine's identity"
    assert (store.broker_dir / "server.crt").is_file()
    assert "Back up" in out and "cafile" in out


def test_the_certificate_authority_is_generated_once(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regenerating would strand every robot provisioned to trust the old one."""
    _first_run(store, [""])
    first = store.ca_path.read_text()
    capsys.readouterr()
    _first_run(store, [])
    assert store.ca_path.read_text() == first
    assert "NO CERTIFICATE AUTHORITY" not in capsys.readouterr().out


def test_a_supplied_ca_and_key_are_copied_into_the_store(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Copied, not remembered by path: a path breaks when the USB stick comes out."""
    cert, key = _ca_files(tmp_path)
    _first_run(store, ["2", cert, key])
    assert store.has_ca()
    assert store.ca_path.read_text() == Path(cert).read_text()


def test_importing_a_ca_requires_its_key(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """A certificate with no key stopped being a resting state in 0.2.0.

    It used to be one: the robot was told who to trust and kept its factory
    certificate. Now that whiskerless issues every robot an identity, a store
    that cannot sign is an unfinished setup — and one that looks exactly like a
    finished one until somebody is standing at a robot.
    """
    cert, _ = _ca_files(tmp_path, with_key=False)
    # Answers run out at the key prompt, the way a closed stdin ends one: EOF,
    # not StopIteration, which inside a coroutine surfaces as a RuntimeError
    # rather than the error the CLI actually raises.
    answers = ["2", cert]

    def _input(_prompt: str = "") -> str:
        if answers:
            return answers.pop(0)
        raise EOFError

    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", _input),
    ):
        # The import asks for a key it will not be given, so the run cannot finish.
        assert main(["setup", "--host", "192.0.2.10"]) != 0
    assert not store.has_ca(), "nothing that cannot sign should have been filed"


def test_a_bare_ca_flag_says_the_key_is_needed_too(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--ca alone used to establish a trust-only store. It now names the flag
    that finishes the job, rather than half-configuring the machine."""
    cert, _ = _ca_files(tmp_path, with_key=False)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert]) != 0
    assert "--ca-key" in capsys.readouterr().err
    assert not store.has_ca_cert(), "a refused setup must not leave a CA behind"


def test_a_server_certificate_is_missing_a_ca_and_says_so(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The "I gave you my server cert" mistake, caught at the prompt rather than
    as an unexplained TLS failure weeks later."""
    from whiskerless import pki

    ca = pki.generate_ca()
    leaf = pki.issue_server(ca, "192.0.2.10")
    cert, key = tmp_path / "leaf.crt", tmp_path / "leaf.key"
    cert.write_text(leaf.cert_pem)
    key.write_text(leaf.key_pem)
    _first_run(store, ["2", str(cert), str(key)])
    assert "not a certificate authority" in capsys.readouterr().err


def test_a_path_that_is_not_there_is_caught_at_the_prompt(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, key = _ca_files(tmp_path)
    _first_run(store, ["2", str(tmp_path / "nope.crt"), cert, key])
    assert "no such file" in capsys.readouterr().err


def test_an_unattended_run_with_no_ca_at_all_explains_the_flags(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A cron job gets a sentence about --ca, not an EOF on a prompt."""
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 1
    err = capsys.readouterr().err
    assert "--ca" in err and "run this in a terminal" in err


def test_the_issued_certificate_serial_is_recorded(store: RobotProfileStore) -> None:
    """The only trace kept of a robot's certificate, and it is not secret."""
    _first_run(store, [""])
    assert store.load("LR4C123456").cert_serial


def _setup_run(*extra: str) -> int:
    """`whiskerless setup` — this machine, its broker and its certificates."""
    return main(["setup", "--host", "192.0.2.10", *extra])


def _flag_run(store: RobotProfileStore, *setup_flags: str, provision: tuple[str, ...] = ()) -> int:
    """`setup` with these flags, then a provision onto the machine it prepared.

    Two commands on purpose: between generating certificates and a robot being
    able to use them, three files have to reach the broker and it has to restart,
    and a robot in pairing mode cannot be kept waiting for that.
    """
    code = main(["setup", "--host", "192.0.2.10", *setup_flags])
    if code != 0:
        return code
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        return main(["provision", "--serial", "LR4C123456",
                     "--wifi-ssid", "home", "--wifi-pass", "pw", "--yes", *provision])


def test_a_ca_supplied_by_flag_is_copied_and_can_issue(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0
    assert store.has_ca()
    assert store.load("LR4C123456").cert_serial, "a robot certificate was issued"


def test_a_lone_ca_is_refused_even_when_the_store_already_has_one(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ignoring the file and reporting success is how somebody believes they
    switched authorities while every robot still trusts the old one."""
    cert, key = _ca_files(tmp_path)
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    second = tmp_path / "second"
    second.mkdir()
    other, _ = _ca_files(second)
    assert _setup_run("--ca", other) == 1
    assert "--ca needs --ca-key" in capsys.readouterr().err


def test_a_ca_key_without_its_certificate_says_why_both_are_needed(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca-key", key) == 1
    assert "--ca-key needs --ca" in capsys.readouterr().err


def test_a_client_certificate_can_be_supplied_by_flag(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """For somebody who mints this machine's identity themselves — from the same
    CA, but somewhere else — rather than letting the store issue it."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    ca = pki.read_pair(Path(cert), Path(key))
    mine = pki.issue_client(ca, "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)
    assert _flag_run(store, "--ca", cert, "--ca-key", key, "--client-cert", str(cpath),
                     "--client-key", str(kpath)) == 0
    assert store.has_client()
    assert store.load_client().cert_pem == mine.cert_pem


def test_half_a_client_identity_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, _key = _ca_files(tmp_path, with_key=False)
    assert _flag_run(store, "--ca", cert, "--client-cert", cert) == 1
    assert "go together" in capsys.readouterr().err


def test_an_expired_ca_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "stale CA")])
    past = dt.datetime.now(dt.UTC) - dt.timedelta(days=10)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(past - dt.timedelta(days=1)).not_valid_after(past)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cpath, kpath = tmp_path / "old.crt", tmp_path / "old.key"
    cpath.write_text(cert.public_bytes(serialization.Encoding.PEM).decode())
    kpath.write_text(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()).decode())
    assert _flag_run(store, "--ca", str(cpath), "--ca-key", str(kpath)) == 1
    assert "already expired" in capsys.readouterr().err


def test_a_ca_without_key_usage_warns_about_the_failure_it_will_cause(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It works for the robot and then breaks our own CLI on Python 3.13 — the
    worst possible split, and worth naming before it happens."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "loose CA")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=200))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cpath, kpath = tmp_path / "loose.crt", tmp_path / "loose.key"
    cpath.write_text(cert.public_bytes(serialization.Encoding.PEM).decode())
    kpath.write_text(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()).decode())
    assert _flag_run(store, "--ca", str(cpath), "--ca-key", str(kpath)) == 0
    err = capsys.readouterr().err
    assert "no keyUsage extension" in err
    assert "whiskerless handles that" in err, "not presented as a failure it is not"
    assert "expires within a year" in err, "and its short life is worth saying too"


def test_input_ending_at_the_authority_question_names_the_flags(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pipe that reaches the question gets a sentence, not a traceback."""
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", side_effect=EOFError),
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 1
    assert "--ca" in capsys.readouterr().err


def test_a_certificate_with_no_constraints_at_all_is_not_a_ca(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Older self-signed certificates often carry no basicConstraints extension;
    absent is not the same as CA:TRUE."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "bare")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=800))
        .sign(key, hashes.SHA256())
    )
    cpath, kpath = tmp_path / "bare.crt", tmp_path / "bare.key"
    cpath.write_text(cert.public_bytes(serialization.Encoding.PEM).decode())
    kpath.write_text(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()).decode())
    assert _flag_run(store, "--ca", str(cpath), "--ca-key", str(kpath)) == 1
    assert "not a certificate authority" in capsys.readouterr().err




def test_a_different_ca_is_refused_rather_than_swapped_in(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Replacing it leaves every provisioned robot trusting a certificate the
    broker no longer presents, and each rescue is a walk to the robot."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca("the one they trust"))
    seed(store, "LR4C111111", name="Upstairs")
    other, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca", other, "--ca-key", key) == 1
    err = capsys.readouterr().err
    assert "already has a different certificate authority" in err
    assert "Upstairs" in err, "and it names who would be stranded"


def test_the_same_ca_supplied_again_is_not_treated_as_a_swap(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Re-running with the same files is idempotent, not an error."""
    cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0


def test_an_imported_ca_also_gives_this_machine_an_identity(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Otherwise the robot gets a certificate and the CLI does not, and a broker
    running `require_certificate true` refuses every command afterwards."""
    cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0
    assert store.has_client(), "the CLI can identify itself too"


@pytest.mark.parametrize("flag", [["--port", "1884"], ["--insecure"]])
def test_setup_refuses_to_point_the_cli_where_the_robot_cannot_follow(
    store: RobotProfileStore, flag: list[str]
) -> None:
    """Both are gone, and being gone is the feature.

    The robot's port is a compile-time constant with no provisioning field, and
    the robot verifies the broker's name — so either flag could only ever aim the
    CLI at something the robot is not using. Accepting them again silently would
    reintroduce a split nobody would notice until a command went to the wrong
    listener."""
    with pytest.raises(SystemExit) as exc:
        main(["setup", "--host", "192.0.2.10", *flag])
    assert exc.value.code != 0


def test_declining_a_dry_run_is_still_a_decline(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A script reading the exit code must not be told a run it declined
    succeeded, dry or not."""
    _prepared(store)
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _p="": "no"),
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        code = main(["provision", "--serial", "LR4C123456",
                     "--wifi-ssid", "home", "--wifi-pass", "pw", "--dry-run"])
    assert code == 1
    assert "aborted" in capsys.readouterr().err


def test_rerunning_setup_keeps_the_saved_host_without_being_asked(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """A scripted run cannot answer a question, so a re-run with nothing new must
    fall back to what is saved rather than prompting for a host it already has."""
    cert, key = _ca_files(tmp_path)
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    with patch("whiskerless.cli.sys.stdin.isatty", lambda: False):
        assert main(["setup"]) == 0
    assert store.load_broker().host == "192.0.2.10"


def test_setup_asks_for_the_broker_when_there_is_nothing_saved(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """The first-ever run has no host to fall back on, so it asks."""
    cert, key = _ca_files(tmp_path)
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _p="": "192.0.2.77"),
    ):
        assert main(["setup", "--ca", cert, "--ca-key", key]) == 0
    assert store.load_broker().host == "192.0.2.77"


def test_setup_that_generates_points_at_the_files_it_made(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _p="": ""),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    out = capsys.readouterr().out
    assert "cafile" in out, "the three files are listed"
    assert "install the files above" in out


def test_moving_the_broker_reissues_its_certificate(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The certificate is bound to the address, so `broker.json` moving on while
    it stayed put handed the robot a SAN naming somewhere it does not connect —
    a handshake that fails every time and looks exactly like a broken robot.
    Worse, `setup` then printed those same three files and said to install them."""
    from whiskerless import pki

    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _p="": ""),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    first = (store.broker_dir / "server.crt").read_text()
    assert pki.certificate_common_name(first) == "192.0.2.10"

    assert main(["setup", "--host", "192.0.2.99"]) == 0
    reissued = (store.broker_dir / "server.crt").read_text()
    assert pki.certificate_common_name(reissued) == "192.0.2.99"
    assert "reissued the broker certificate" in capsys.readouterr().out


def test_the_same_broker_keeps_the_certificate_it_already_has(store: RobotProfileStore) -> None:
    """Re-running setup must not churn a certificate somebody has already
    installed on their broker."""
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _p="": ""),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    before = (store.broker_dir / "server.crt").read_text()
    assert main(["setup", "--host", "192.0.2.10"]) == 0
    assert (store.broker_dir / "server.crt").read_text() == before


def test_a_moved_broker_gets_a_reissued_certificate(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A certificate naming the old address fails every handshake while looking
    right on disk. The store can always sign now, so it is simply replaced —
    where 0.1.3 could only warn, because the key might not have been here."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0
    capsys.readouterr()
    assert main(["setup", "--host", "192.0.2.99"]) == 0
    assert "reissued the broker certificate" in capsys.readouterr().out
    served = (store.broker_dir / "server.crt").read_text()
    assert pki.certificate_common_name(served) == "192.0.2.99"


def test_a_broker_certificate_that_cannot_be_read_is_reported_not_replaced(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unparseable means unprovable, and the rule is that only a certificate
    chaining to OUR CA is ever overwritten. Deleting a private key on the
    strength of "this did not parse" is not a trade worth making — so it is
    reported and left, and setup stops recommending it."""
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("builtins.input", lambda _p="": ""),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    capsys.readouterr()  # discard the first run: it legitimately says "install the files above"
    (store.broker_dir / "server.crt").write_text("not a certificate")
    assert main(["setup", "--host", "192.0.2.10"]) == 0
    out = capsys.readouterr()
    assert "is not signed by the CA" in out.err
    assert "install the files above" not in out.out


def test_setup_that_imports_a_ca_does_not_point_at_files_it_did_not_make(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Importing a CA WITH its key produces the broker's certificate too, so the
    files it points at are ones it actually made (backlog #72)."""
    cert, key = _ca_files(tmp_path)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0
    out = capsys.readouterr().out
    assert "install the files above" in out
    assert "server.crt" in out


def test_bringing_your_own_ca_and_key_also_gets_a_broker_certificate(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backlog #72. Handing over the signing key gives whiskerless everything it
    needs to issue the broker's certificate; it used to file the pair, mint this
    machine's identity, and then tell you to make sure your broker presents a
    certificate signed by that CA — with the thing that could sign it sitting
    right there."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path, with_key=True)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0
    issued = store.broker_dir / "server.crt"
    assert issued.is_file(), "the broker certificate should have been issued"
    assert pki.certificate_common_name(issued.read_text()) == "192.0.2.10"
    out = capsys.readouterr().out
    assert "cafile" in out, "and setup should now point at all three files"


def test_a_server_certificate_you_placed_yourself_is_never_overwritten(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Only the ABSENT case is filled in. Somebody with their own issuance
    process may have put the real one there already — and as long as it names
    this broker, it is theirs to keep. (An UNREADABLE one is reissued instead;
    that is a different test, and deliberate.)"""
    from whiskerless import pki

    # ONE call: _ca_files mints a fresh CA each time, so calling it twice would
    # sign the fixture with a CA that is never imported — which the code now
    # correctly refuses to leave in place.
    cert, key = _ca_files(tmp_path, with_key=True)
    assert key is not None
    theirs = pki.issue_server(pki.read_pair(Path(cert), Path(key)), "192.0.2.10")
    store.save_broker_certs(theirs)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0
    assert (store.broker_dir / "server.crt").read_text() == theirs.cert_pem


def test_a_broker_certificate_from_a_foreign_ca_is_never_overwritten(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The worst shape of wrong — right host, right filename, fails every
    handshake because the robots hold a different CA. It is REPORTED, not
    replaced: proving a chain is harder than it looks (an intermediate, or an
    RSASSA-PSS signature, reads as "not ours"), and a false negative that
    overwrites would destroy somebody's certificate and its private key."""
    from whiskerless import pki

    stranger = pki.issue_server(pki.generate_ca("not yours"), "192.0.2.10")
    store.save_broker_certs(stranger)
    cert, key = _ca_files(tmp_path, with_key=True)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0
    assert (store.broker_dir / "server.crt").read_text() == stranger.cert_pem
    out = capsys.readouterr()
    assert "will not overwrite a certificate it did not issue" in out.err
    assert "install the files above" not in out.out


def test_a_wrong_ca_broker_certificate_is_called_out_when_it_cannot_be_reissued(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    store.save_broker_certs(pki.issue_server(pki.generate_ca("not yours"), "192.0.2.10"))
    cert, key = _ca_files(tmp_path)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0
    # Still not overwritten: only a certificate chaining to OUR CA is replaced,
    # because a false negative here would destroy somebody's private key.
    assert "cannot verify a broker" in capsys.readouterr().err


def test_an_unreadable_broker_certificate_file_does_not_crash_setup(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """The chain check reads the file a second time; a read that fails there must
    not take down a command that was only deciding whether to reissue."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path, with_key=True)
    assert key is not None
    store.save_broker_certs(pki.issue_server(pki.read_pair(Path(cert), Path(key)), "192.0.2.10"))
    real = Path.read_text
    calls: list[int] = []

    def flaky(self: Path, *a: object, **kw: object) -> str:
        # Fail only the chain-check read of server.crt, not the CN read before it.
        if self.name == "server.crt":
            calls.append(1)
            if len(calls) > 1:
                raise OSError(5, "Input/output error")
        return real(self, *a, **kw)  # type: ignore[arg-type]

    with patch.object(Path, "read_text", flaky):
        assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0


def test_a_broker_certificate_that_vanishes_mid_check_is_not_treated_as_usable(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """`is_file()` then `read_text()` is a check-then-use; if the read fails the
    answer must be "not usable", never "fine"."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path, with_key=True)
    assert key is not None
    store.save_broker_certs(pki.issue_server(pki.read_pair(Path(cert), Path(key)), "192.0.2.10"))
    real = Path.read_text

    def vanish(self: Path, *a: object, **kw: object) -> str:
        if self.name == "server.crt":
            raise OSError(2, "No such file or directory")
        return real(self, *a, **kw)  # type: ignore[arg-type]

    with patch.object(Path, "read_text", vanish):
        assert main(["setup", "--host", "192.0.2.10", "--ca", cert, "--ca-key", key]) == 0


def test_a_migrated_store_is_told_what_changed_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run that hoists a pre-0.2.0 store is the only moment anything knows
    somebody is upgrading rather than starting fresh.

    Two things changed that they did not ask for and cannot see: broker
    credentials stopped existing, and a certificate per robot became available —
    which they would never discover, because a trust anchor with no key looks
    exactly like a deliberate choice to everything downstream.
    """
    import json

    from whiskerless.robot_profiles import LEGACY_SUBDIR

    robot = tmp_path / LEGACY_SUBDIR / "robots" / "LR4C123456"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(json.dumps({"serial": "LR4C123456", "host": "192.0.2.10"}))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WHISKERLESS_HOME", raising=False)

    assert main(["robots"]) == 0
    first = capsys.readouterr().err
    assert "Moved your settings" in first
    assert "usernames and passwords are gone" in first
    assert "certificate" in first, "the recommended path has to be named"

    # Only the migrating run says it. Every later command is silent.
    assert main(["robots"]) == 0
    assert "Moved your settings" not in capsys.readouterr().err


def test_a_store_placed_by_hand_is_told_what_changed_without_claiming_a_move(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`WHISKERLESS_HOME` skips the rename and is hoisted where it stands.

    Keying the notice on the move meant the one class of user who placed their
    store deliberately heard nothing about credentials disappearing — and there
    is no move to announce, so announcing one sends them looking for a directory
    that was never created.
    """
    import json

    home = tmp_path / "elsewhere"
    robot = home / "robots" / "LR4C123456"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(
        json.dumps({"serial": "LR4C123456", "host": "192.0.2.10", "username": "dead"})
    )
    monkeypatch.setenv("WHISKERLESS_HOME", str(home))

    assert main(["robots"]) == 0
    said = capsys.readouterr().err
    assert "usernames and passwords are gone" in said
    assert "Moved your settings" not in said, "nothing moved, so nothing to go looking for"
    assert "0.2.0 layout" in said



def test_a_store_with_a_certificate_but_no_key_is_refused_without_a_terminal(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What an upgraded 0.1.3 store looks like: the CA certificate hoists across
    from the robot profiles, and the key was never in there to hoist.

    Carrying on regardless is the worst option — it looks identical to a working
    setup while silently declining to issue the certificates the version exists
    for. A script gets told which flags finish the job."""
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca("theirs").cert_pem)
    assert main(["setup", "--host", "192.0.2.10"]) != 0
    err = capsys.readouterr().err
    assert "certificate with no key" in err
    assert "--ca-key" in err


def test_the_missing_key_can_be_supplied_and_nothing_is_re_provisioned(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cheap answer: the robots already trust this authority, so filing its
    key leaves every one of them working."""
    from whiskerless import pki

    ca = pki.generate_ca("theirs")
    store.save_ca_cert_only(ca.cert_pem)
    key_path = tmp_path / "ca.key"
    key_path.write_text(ca.key_pem)

    answers = ["1", str(key_path)]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    assert store.has_ca(), "the key should now be filed with its certificate"
    assert store.load_ca().cert_pem == ca.cert_pem, "the anchor must not have changed"
    assert store.has_client(), "and this machine needs an identity of its own"


def test_a_key_for_a_different_authority_is_refused(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """A key that signs for something else would leave every robot out there
    trusting an authority this store cannot sign for."""
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca("theirs").cert_pem)
    other = pki.generate_ca("somebody else")
    key_path = tmp_path / "other.key"
    key_path.write_text(other.key_pem)

    answers = ["1", str(key_path)]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) != 0
    assert not store.has_ca()


def test_replacing_the_authority_needs_the_cost_typed_out(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generating a new authority strands every robot until it is re-provisioned,
    so it is not something a stray keypress does."""
    from whiskerless import pki

    original = pki.generate_ca("theirs").cert_pem
    store.save_ca_cert_only(original)
    store.save_broker(Broker(host="192.0.2.10"))

    answers = ["2", "no"]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) != 0
    assert store.ca_path.read_text() == original, "a declined replacement changes nothing"

    answers = ["2", "yes"]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    assert store.has_ca()
    assert store.ca_path.read_text() != original, "confirming replaces the anchor"
    assert "re-provision" in capsys.readouterr().out.lower()


def test_a_second_broker_is_reported_rather_than_dropped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before layout 1 the broker address lived on each robot, so two of them
    could name two brokers. One store holds one, and the migration picks — which
    leaves the other robot pointed somewhere that is not its broker.

    Almost certainly nobody's setup, but a silent wrong answer is worse than a
    stated one, and this is the only moment the discarded address exists to
    report."""
    import json as json_module

    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    for serial, host in (("LR4C111111", "192.0.2.10"), ("LR4C222222", "198.51.100.20")):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json_module.dumps({"serial": serial, "host": host})
        )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WHISKERLESS_HOME", raising=False)

    assert main(["robots"]) == 0
    err = capsys.readouterr().err
    assert "More than one broker" in err
    assert "192.0.2.10" in err and "198.51.100.20" in err
    assert "WHISKERLESS_HOME" in err, "and how to keep both"


def test_one_broker_across_robots_says_nothing_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary case must not grow a warning about a choice nobody faced."""
    import json as json_module

    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    for serial in ("LR4C111111", "LR4C222222"):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json_module.dumps({"serial": serial, "host": "192.0.2.10"})
        )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WHISKERLESS_HOME", raising=False)

    assert main(["robots"]) == 0
    assert "More than one broker" not in capsys.readouterr().err


def test_a_robot_profile_too_damaged_to_read_does_not_stop_the_hoist(tmp_path: Path) -> None:
    """This runs from from_env(), so anything raising takes every command down."""
    import json as json_module

    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    (legacy / "LR4C111111").mkdir(parents=True)
    (legacy / "LR4C111111" / "profile.json").write_text(
        json_module.dumps({"serial": "LR4C111111", "host": "192.0.2.10"})
    )
    (legacy / "LR4C222222").mkdir(parents=True)
    (legacy / "LR4C222222" / "profile.json").write_text("{not json at all")

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.load_broker().host == "192.0.2.10", "the readable robot still hoists"


def test_the_key_question_with_nobody_to_ask_names_the_flags(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A terminal that closes mid-question must not become a traceback. It is the
    same answer the non-interactive path gives, because the situation is the
    same: nobody can say which authority this store should end up with."""
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca("theirs").cert_pem)

    def _eof(_prompt: str = "") -> str:
        raise EOFError

    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", _eof),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) != 0
    assert "--ca-key" in capsys.readouterr().err


def test_replacing_the_authority_works_without_a_broker_on_file(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Migration keeps a CA even when it can hoist no broker address, so this
    store is reachable — and replacing the authority is irreversible, so it must
    not get half-done and then fail looking for a broker that was never there."""
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca("theirs").cert_pem)
    assert not store.has_broker()

    answers = ["2", "yes"]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.77"]) == 0
    assert store.has_ca()
    served = (store.broker_dir / "server.crt").read_text()
    assert pki.certificate_common_name(served) == "192.0.2.77", "the host asked for"


def test_replacing_the_authority_replaces_this_machines_identity_too(
    store: RobotProfileStore
) -> None:
    """The stored client certificate was signed by the authority being retired.

    Keeping it means setup reports success and the CLI is then refused the moment
    the listener asks for a certificate — with nothing to connect the two."""
    from whiskerless import pki

    old_ca = pki.generate_ca("theirs")
    store.save_ca_cert_only(old_ca.cert_pem)
    store.save_broker(Broker(host="192.0.2.10"))
    store.save_client(pki.issue_client(old_ca, "whiskerless-old"))
    before = store.load_client().cert_pem

    answers = ["2", "yes"]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0

    assert store.load_client().cert_pem != before, "the stale identity survived"
    # And the new one chains to the authority that now exists.
    assert pki.is_signed_by(store.load_client().cert_pem, store.ca_path.read_text())


def test_robots_marks_the_ones_with_no_certificate_of_ours(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A robot we never issued a certificate to is refused by the listener this
    project recommends, and works on the one it replaces — so the two states have
    to be distinguishable somewhere. Here, not on every command: the CA question
    was made once-only for the same reason."""
    seed(store, "LR4C111111", cert_serial="abc123")
    seed(store, "LR4C222222")
    assert main(["robots"]) == 0
    out = capsys.readouterr().out
    assert "LR4C222222" in out and "no identity from this store" in out
    assert "1 robot holds no certificate this store issued" in out
    # The one that has a certificate is not accused of lacking one.
    lines = [line for line in out.splitlines() if "LR4C111111" in line]
    assert lines and "no identity" not in lines[0]


def test_robots_says_nothing_when_every_robot_has_a_certificate(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ordinary case must not grow a warning about a problem nobody has."""
    seed(store, "LR4C111111", cert_serial="abc123")
    seed(store, "LR4C222222", cert_serial="def456")
    assert main(["robots"]) == 0
    assert "no identity from this store" not in capsys.readouterr().out


def test_replacing_the_authority_does_not_overwrite_a_foreign_broker_certificate(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Overwriting a certificate this store did not issue destroys its private key
    too, which is why `_refresh_server_cert` never does it. Rotating the authority
    must go through the same guard rather than writing directly."""
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca("theirs").cert_pem)
    store.save_broker(Broker(host="192.0.2.10"))
    foreign = pki.issue_server(pki.generate_ca("somebody else"), "192.0.2.10")
    store.save_broker_certs(foreign)

    answers = ["2", "yes"]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0

    kept = (store.broker_dir / "server.crt").read_text()
    assert kept == foreign.cert_pem, "somebody else's certificate was overwritten"
    assert "will not overwrite a certificate it did not issue" in capsys.readouterr().err


def test_replacing_the_authority_marks_every_robot_for_re_provisioning(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each robot's recorded certificate was signed by the retired authority.

    Left in place they read as current, so `robots` would show nothing to
    re-provision at exactly the moment every one of them needs it."""

    seed(store, "LR4C111111", cert_serial="abc123")
    seed(store, "LR4C222222", cert_serial="def456")
    # Downgrade to what a migrated store looks like: `seed` builds a signable one,
    # so the key has to go for the trust-only path to be reached at all.
    (store.root / "ca" / "ca.key").unlink()
    assert store.has_ca_cert() and not store.has_ca()

    answers = ["2", "yes"]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    capsys.readouterr()

    assert all(p.cert_serial is None for p in store.list_robot_profiles())
    assert main(["robots"]) == 0
    out = capsys.readouterr().out
    # NOT "factory identity": these robots hold certificates this store issued,
    # signed by the authority just retired. The physical robot did not change.
    assert out.count("no identity from this store") == 2
    assert "2 robots hold no certificate this store issued" in out


def test_replacing_the_authority_leaves_an_unreadable_broker_certificate_alone(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whether the old certificate is ours has to be read off disk, and that read
    can fail. Unprovable is treated as somebody else's, because overwriting takes
    the private key with it and there is no way to put one back."""
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca("theirs").cert_pem)
    store.save_broker(Broker(host="192.0.2.10"))
    store.save_broker_certs(pki.issue_server(pki.generate_ca("mine"), "192.0.2.10"))
    served = (store.broker_dir / "server.crt").read_text()

    real_read = Path.read_text

    def _read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "server.crt":
            raise OSError("unreadable")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _read)
    answers = ["2", "yes"]
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": answers.pop(0)),
    ):
        assert main(["setup", "--host", "192.0.2.10"]) == 0
    monkeypatch.undo()

    assert (store.broker_dir / "server.crt").read_text() == served
    assert "was not issued by this machine" in capsys.readouterr().err


# --- the three ways a store can authenticate --------------------------------


def _provision_run(*extra: str) -> int:
    """A provision onto whatever `setup` has already prepared."""
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        return main(["provision", "--serial", "LR4C123456",
                     "--wifi-ssid", "home", "--wifi-pass", "pw", "--yes", *extra])


def _expired_client(ca: Any, common_name: str) -> Any:
    """A client certificate that was valid once, for the check that it is not now."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from whiskerless.pki import KeyPair

    issuer = x509.load_pem_x509_certificate(ca.cert_pem.encode())
    signing = serialization.load_pem_private_key(ca.key_pem.encode(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=400)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(issuer.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(past)
        .not_valid_after(past + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(signing, hashes.SHA256())  # type: ignore[arg-type]
    )
    return KeyPair(
        cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        key_pem=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


def _future_client(ca: Any, common_name: str) -> Any:
    """A certificate whose validity has not started yet."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from whiskerless.pki import KeyPair

    issuer = x509.load_pem_x509_certificate(ca.cert_pem.encode())
    signing = serialization.load_pem_private_key(ca.key_pem.encode(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=7)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(issuer.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(later)
        .not_valid_after(later + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(signing, hashes.SHA256())  # type: ignore[arg-type]
    )
    return KeyPair(
        cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        key_pem=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


def _bare_client(ca: Any, common_name: str, *, eku: Any = None) -> Any:
    """A client certificate with no extensions at all — no BasicConstraints, no
    ExtendedKeyUsage. Plenty of hand-rolled CAs issue exactly this. `eku` adds one
    back, for the checks that only apply when the extension is there to disagree
    with."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from whiskerless.pki import KeyPair

    issuer = x509.load_pem_x509_certificate(ca.cert_pem.encode())
    signing = serialization.load_pem_private_key(ca.key_pem.encode(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.UTC)
    # An empty string is not a name cryptography will build; a subject with no
    # attributes is what a certificate carrying no common name actually looks like.
    subject = (
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        if common_name
        else x509.Name([])
    )
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=30))
    )
    if eku is not None:
        builder = builder.add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
    cert = builder.sign(signing, hashes.SHA256())  # type: ignore[arg-type]
    return KeyPair(
        cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        key_pem=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


def _their_robot_cert(tmp_path: Path, ca_cert: str, ca_key: str, serial: str) -> tuple[str, str]:
    """A robot certificate somebody else issued, from the same authority."""
    from whiskerless import pki

    ca = pki.read_pair(Path(ca_cert), Path(ca_key))
    theirs = pki.issue_client(ca, serial)
    cert, key = tmp_path / f"{serial}.crt", tmp_path / f"{serial}.key"
    cert.write_text(theirs.cert_pem)
    key.write_text(theirs.key_pem)
    return str(cert), str(key)


def test_the_default_mode_is_recorded_so_it_can_be_relied_on(store: RobotProfileStore) -> None:
    cert, key = _ca_files(Path(tempfile.mkdtemp()))
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    assert store.load_broker().auth is AuthMode.MUTUAL


def test_supplied_mode_takes_a_ca_certificate_with_no_key(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """The cert-manager arrangement: the signing key never reaches this machine.
    Stricter than the default, not weaker — so it must not need one."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    ca = pki.read_pair(Path(cert), Path(key))
    mine = pki.issue_client(ca, "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)

    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", str(cpath), "--client-key", str(kpath)) == 0
    assert store.load_broker().auth is AuthMode.SUPPLIED
    assert store.has_ca_cert() and not store.has_ca(), "a signing key was filed anyway"

    robot_cert, robot_key = _their_robot_cert(tmp_path, cert, key, "LR4C123456")
    assert _provision_run("--robot-cert", robot_cert, "--robot-key", robot_key) == 0
    assert store.load_robot_identity("LR4C123456").cert_pem == Path(robot_cert).read_text()
    assert store.load("LR4C123456").cert_serial, "the issued certificate was not recorded"

    # And the second provision needs nothing handed over again.
    assert _provision_run() == 0


def test_supplied_mode_refuses_a_key_that_contradicts_it(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Filing it would leave a store that says identities come from elsewhere
    while holding everything needed to issue them here."""
    cert, key = _ca_files(tmp_path)
    assert _setup_run("--auth", "supplied", "--ca", cert, "--ca-key", key) == 1
    assert "--ca-key contradicts" in capsys.readouterr().err


def test_supplied_mode_needs_this_machines_own_certificate(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing here can mint it, and a store without one is refused by a listener
    asking for one — after reporting that setup succeeded."""
    cert, _ = _ca_files(tmp_path)
    assert _setup_run("--auth", "supplied", "--ca", cert) == 1
    assert "needs this machine's own certificate" in capsys.readouterr().err


def test_supplied_mode_with_no_certificate_for_this_robot_says_so(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    mine = pki.issue_client(pki.read_pair(Path(cert), Path(key)), "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)
    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", str(cpath), "--client-key", str(kpath)) == 0
    assert _provision_run() == 1
    assert "has no certificate on file for LR4C123456" in capsys.readouterr().err


def test_a_robot_certificate_from_the_wrong_authority_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Written to the robot it produces a robot the broker refuses, and the
    failure surfaces as a TLS handshake that names nothing."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    mine = pki.issue_client(pki.read_pair(Path(cert), Path(key)), "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)
    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", str(cpath), "--client-key", str(kpath)) == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other_cert, other_key = _ca_files(elsewhere)
    assert other_key is not None
    stray_cert, stray_key = _their_robot_cert(elsewhere, other_cert, other_key, "LR4C123456")
    assert _provision_run("--robot-cert", stray_cert, "--robot-key", stray_key) == 1
    assert "was not signed by the CA" in capsys.readouterr().err


def test_anonymous_mode_leaves_the_robot_the_certificate_it_shipped_with(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What 0.1.3 did, and the one mode that has to be asked for."""
    cert, _ = _ca_files(tmp_path)
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert store.load_broker().auth is AuthMode.ANONYMOUS
    assert _provision_run() == 0
    assert not store.has_robot_identity("LR4C123456")
    assert store.load("LR4C123456").cert_serial is None
    assert "keeps the certificate it shipped with" in capsys.readouterr().out


def test_anonymous_mode_does_not_mark_every_robot_as_needing_attention(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A robot without one of our certificates is the ARRANGEMENT here. Flagging
    the whole fleet trains somebody to ignore the one marker that means
    something."""
    cert, _ = _ca_files(tmp_path)
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert _provision_run() == 0
    capsys.readouterr()
    assert main(["robots"]) == 0
    listed = capsys.readouterr().out
    assert "no identity from this store" not in listed
    assert "re-provisioning is the fix" not in listed


def test_the_mode_is_kept_across_a_later_setup_run(store: RobotProfileStore, tmp_path: Path) -> None:
    """`setup --host <new address>` is routine. A default that overrode the file
    would move a cert-manager store back onto certificates we sign — the second
    time, not the first, which is the kind of change nobody goes looking for."""
    cert, _ = _ca_files(tmp_path)
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert main(["setup", "--host", "192.0.2.11"]) == 0
    assert store.load_broker().auth is AuthMode.ANONYMOUS
    assert store.load_broker().host == "192.0.2.11"


def test_changing_the_mode_says_so(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, key = _ca_files(tmp_path)
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    capsys.readouterr()
    assert _setup_run("--auth", "anonymous") == 0
    assert "mutual" in capsys.readouterr().out


def test_a_robot_keeps_one_identity_across_re_provisions(store: RobotProfileStore) -> None:
    """A new WiFi password is enough to re-provision, and the broker's ACLs and
    logs are keyed to the certificate."""
    seed(store)
    assert _provision_run() == 0
    first = store.load_robot_identity("LR4C123456").cert_pem
    assert _provision_run() == 0
    assert store.load_robot_identity("LR4C123456").cert_pem == first


def test_reissue_replaces_the_stored_identity(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store)
    assert _provision_run() == 0
    first = store.load_robot_identity("LR4C123456").cert_pem
    capsys.readouterr()
    assert _provision_run("--reissue") == 0
    assert store.load_robot_identity("LR4C123456").cert_pem != first
    assert "replacing the certificate" in capsys.readouterr().out


def test_provisioning_says_to_back_up_again(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every provision adds material a backup taken before it does not have — and
    in `supplied` mode a private key nothing here can produce again."""
    seed(store)
    assert _provision_run() == 0
    said = capsys.readouterr().out
    assert "Back up again" in said
    assert "whiskerless backup" in said


def test_a_supplied_certificate_cannot_be_forced_into_an_anonymous_store(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, key = _ca_files(tmp_path)
    assert key is not None
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    robot_cert, robot_key = _their_robot_cert(tmp_path, cert, key, "LR4C123456")
    assert _provision_run("--robot-cert", robot_cert, "--robot-key", robot_key) == 1
    assert "contradicts this store's 'anonymous' mode" in capsys.readouterr().err


def test_half_a_supplied_pair_says_both_are_needed(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store)
    assert _provision_run("--robot-cert", str(tmp_path / "nothing.crt")) == 1
    assert "--robot-cert and --robot-key go together" in capsys.readouterr().err


def test_a_non_signing_mode_with_no_ca_and_no_terminal_says_which_flag(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _setup_run("--auth", "anonymous") == 1
    assert "pass --ca <file>" in capsys.readouterr().err


def test_a_non_signing_mode_asks_for_the_ca_when_there_is_somebody_to_ask(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    mine = pki.issue_client(pki.read_pair(Path(cert), Path(key)), "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)

    answers = iter([cert])
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": next(answers)),
    ):
        assert _setup_run("--auth", "supplied",
                          "--client-cert", str(cpath), "--client-key", str(kpath)) == 0
    assert store.has_ca_cert() and not store.has_ca()
    assert "NO CERTIFICATE AUTHORITY" in capsys.readouterr().out


def test_a_non_signing_mode_with_nobody_to_ask_at_the_prompt(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A terminal that ends mid-question, which argparse cannot pre-empt."""
    def _eof(_prompt: str = "") -> str:
        raise EOFError

    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", _eof),
    ):
        assert _setup_run("--auth", "anonymous") == 1
    assert "input ended" in capsys.readouterr().err


def test_a_foreign_broker_certificate_naming_the_wrong_host_is_reported(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing here can replace it — no key — so saying what is wrong with it is
    the whole of what this can do."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    ca = pki.read_pair(Path(cert), Path(key))
    store.save_broker_certs(pki.issue_server(ca, "192.0.2.99"))
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    said = capsys.readouterr()
    assert "does not name 192.0.2.10" in said.err
    assert (store.broker_dir / "server.crt").read_text(), "it was replaced anyway"
    assert "install your broker's certificate" in said.out


def test_the_upgrade_prompt_names_the_way_out_that_costs_no_robot(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Somebody whose key is in cert-manager should not have to pick "generate a
    new authority" — and re-provision the fleet — to escape a prompt written for
    somebody who lost theirs."""
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca().cert_pem)
    store.save_broker(Broker(host="192.0.2.10"))
    answers = iter(["2", "yes"])
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": next(answers)),
    ):
        assert _setup_run() == 0
    assert "--auth supplied" in capsys.readouterr().out


def test_the_scripted_upgrade_error_names_it_too(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca().cert_pem)
    store.save_broker(Broker(host="192.0.2.10"))
    assert _setup_run() == 1
    assert "--auth supplied" in capsys.readouterr().err


def test_the_ca_cannot_be_handed_over_as_a_robots_certificate(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A CA certificate IS signed by the stored authority when it is the stored
    authority, so a signature check alone accepts it — and provisioning writes the
    key beside it to the robot."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    mine = pki.issue_client(pki.read_pair(Path(cert), Path(key)), "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)
    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", str(cpath), "--client-key", str(kpath)) == 0

    assert _provision_run("--robot-cert", cert, "--robot-key", key) == 1
    assert "hand your signing key to a litter box" in capsys.readouterr().err
    assert not store.has_robot_identity("LR4C123456"), "it was filed anyway"


def test_an_expired_supplied_certificate_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    ca = pki.read_pair(Path(cert), Path(key))
    mine = pki.issue_client(ca, "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)
    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", str(cpath), "--client-key", str(kpath)) == 0

    stale = _expired_client(ca, "LR4C123456")
    scert, skey = tmp_path / "old.crt", tmp_path / "old.key"
    scert.write_text(stale.cert_pem)
    skey.write_text(stale.key_pem)
    assert _provision_run("--robot-cert", str(scert), "--robot-key", str(skey)) == 1
    assert "already expired" in capsys.readouterr().err


def test_a_malformed_ca_file_is_a_one_line_error_not_a_traceback(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    junk = tmp_path / "junk.crt"
    junk.write_text("-----BEGIN CERTIFICATE-----\nnot base64\n-----END CERTIFICATE-----\n")
    assert _setup_run("--auth", "anonymous", "--ca", str(junk)) == 1
    assert "not a readable PEM certificate" in capsys.readouterr().err


def test_forgetting_a_robot_takes_its_private_key_with_it(store: RobotProfileStore) -> None:
    """Left behind it is a key belonging to a robot nobody here remembers — and
    the directory stays non-empty, so the robot returns as damaged."""
    seed(store)
    assert _provision_run() == 0
    assert store.has_robot_identity("LR4C123456")
    assert main(["forget", "LR4C123456", "--yes"]) == 0
    assert not store.has_robot_identity("LR4C123456")
    assert not (store.root / "robots" / "LR4C123456").exists(), "the robot came back damaged"


def test_rotating_the_authority_reaches_an_identity_no_profile_names(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """An aborted provision leaves one behind that `list_robot_profiles()` skips, and
    `robot_identity()` would hand it back later as a cache hit."""
    seed(store)
    store.robot_identity("LR4C999999")
    (store.root / "robots" / "LR4C999999" / "profile.json").unlink(missing_ok=True)
    # The rotation prompt is only reached by a store that cannot sign, which is
    # also the state somebody rotating out of is usually in.
    store.save_ca_cert_only(store.ca_path.read_text())
    answers = iter(["2", "yes"])
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": next(answers)),
    ):
        assert _setup_run() == 0
    assert not store.has_robot_identity("LR4C999999"), "a retired identity survived"


def _supplied_store(store: RobotProfileStore, tmp_path: Path) -> tuple[str, str]:
    """A `supplied` store, ready to be handed a robot certificate."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    mine = pki.issue_client(pki.read_pair(Path(cert), Path(key)), "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)
    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", str(cpath), "--client-key", str(kpath)) == 0
    return cert, key


def test_a_certificate_with_no_extensions_at_all_is_accepted(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Minimal certificates from a hand-rolled CA are common and work. Refusing
    one for lacking extensions would strand somebody whose setup is fine."""
    from whiskerless import pki

    cert, key = _supplied_store(store, tmp_path)
    bare = _bare_client(pki.read_pair(Path(cert), Path(key)), "LR4C123456")
    bcert, bkey = tmp_path / "bare.crt", tmp_path / "bare.key"
    bcert.write_text(bare.cert_pem)
    bkey.write_text(bare.key_pem)
    assert _provision_run("--robot-cert", str(bcert), "--robot-key", str(bkey)) == 0
    assert store.has_robot_identity("LR4C123456")


def test_a_certificate_marked_for_the_wrong_purpose_is_reported(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A leaf that chains and names the robot, but says it is for a server. Warned
    rather than refused: brokers that check extended key usage reject it, and
    plenty do not."""
    from cryptography.x509.oid import ExtendedKeyUsageOID

    from whiskerless import pki

    cert, key = _supplied_store(store, tmp_path)
    odd = _bare_client(
        pki.read_pair(Path(cert), Path(key)), "LR4C123456",
        eku=ExtendedKeyUsageOID.SERVER_AUTH,
    )
    ocert, okey = tmp_path / "o.crt", tmp_path / "o.key"
    ocert.write_text(odd.cert_pem)
    okey.write_text(odd.key_pem)
    assert _provision_run("--robot-cert", str(ocert), "--robot-key", str(okey)) == 0
    assert "not marked for client authentication" in capsys.readouterr().err


def test_another_robots_certificate_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It chains, it is a leaf, it is in date — and the broker takes the robot's
    username from its common name, so this robot would connect as another one."""
    cert, key = _supplied_store(store, tmp_path)
    theirs_cert, theirs_key = _their_robot_cert(tmp_path, cert, key, "LR4C999999")
    assert _provision_run("--robot-cert", theirs_cert, "--robot-key", theirs_key) == 1
    assert "names LR4C999999, not LR4C123456" in capsys.readouterr().err


def test_a_broker_certificate_from_another_authority_is_reported(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Setup's next line says to restart the broker with it, so every way it can
    be wrong has to be said here."""
    from whiskerless import pki

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other_cert, other_key = _ca_files(elsewhere)
    assert other_key is not None
    store.save_broker_certs(
        pki.issue_server(pki.read_pair(Path(other_cert), Path(other_key)), "192.0.2.10")
    )
    cert, _ = _ca_files(tmp_path)
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert "was not signed by the CA" in capsys.readouterr().err


def test_an_expired_broker_certificate_is_reported(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    ca = pki.read_pair(Path(cert), Path(key))
    stale = _expired_client(ca, "192.0.2.10")
    store.save_broker_certs(stale)
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert "it has expired" in capsys.readouterr().err


def test_a_supplied_store_that_lost_its_identity_says_so_instead_of_going_anonymous(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Connecting anonymously would SUCCEED on a listener that still allows it,
    while the store went on saying `supplied` — the exact silence the stored mode
    exists to end."""
    _supplied_store(store, tmp_path)
    store.forget_client()
    with pytest.raises(RobotProfileError, match="Nothing here can issue another"):
        store.settings()


def test_an_aborted_provision_leaves_the_stored_identity_alone(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """In `supplied` mode the certificate being replaced cannot be recreated, so
    an abort between the flag and the BLE write must not have consumed it."""
    cert, key = _supplied_store(store, tmp_path)
    first_cert, first_key = _their_robot_cert(tmp_path, cert, key, "LR4C123456")
    assert _provision_run("--robot-cert", first_cert, "--robot-key", first_key) == 0
    held = store.load_robot_identity("LR4C123456").cert_pem

    replacement = tmp_path / "again"
    replacement.mkdir()
    new_cert, new_key = _their_robot_cert(replacement, cert, key, "LR4C123456")
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=False)),
    ):
        assert main(["provision", "--serial", "LR4C123456", "--wifi-ssid", "home",
                     "--wifi-pass", "pw", "--yes",
                     "--robot-cert", new_cert, "--robot-key", new_key]) == 1
    assert store.load_robot_identity("LR4C123456").cert_pem == held


def test_forgetting_says_the_private_key_goes_too(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Approving "only removes the saved broker details" and losing a key that
    cannot be reissued is a surprise, not a confirmation."""
    cert, key = _supplied_store(store, tmp_path)
    robot_cert, robot_key = _their_robot_cert(tmp_path, cert, key, "LR4C123456")
    assert _provision_run("--robot-cert", robot_cert, "--robot-key", robot_key) == 0
    asked: list[str] = []

    def _decline(prompt: str = "") -> str:
        asked.append(prompt)
        return "no"

    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", _decline),
    ):
        assert main(["forget", "LR4C123456"]) == 1
    question = " ".join(asked)
    assert "private key" in question and "only copy" in question
    assert store.has_robot_identity("LR4C123456"), "declining still deleted it"


def test_a_broker_certificate_naming_another_host_in_its_san_is_reported(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Modern issuers leave the CN empty, so treating a missing one as fine
    passes a certificate for some other broker."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    ca = pki.read_pair(Path(cert), Path(key))
    store.save_broker_certs(pki.issue_server(ca, "192.0.2.99"))
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert "does not name 192.0.2.10" in capsys.readouterr().err


def test_the_ca_cannot_be_filed_as_this_machines_identity(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It would leave the signing key on a machine whose mode says it never
    arrives."""
    cert, key = _ca_files(tmp_path)
    assert key is not None
    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", cert, "--client-key", key) == 1
    assert "not a client certificate" in capsys.readouterr().err
    assert not store.has_client(), "it was left on file anyway"


def test_a_client_certificate_from_another_authority_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other_cert, other_key = _ca_files(elsewhere)
    assert other_key is not None
    stray = pki.issue_client(pki.read_pair(Path(other_cert), Path(other_key)), "whiskerless")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(stray.cert_pem)
    kpath.write_text(stray.key_pem)
    cert, _ = _ca_files(tmp_path)
    assert _setup_run("--auth", "supplied", "--ca", cert,
                      "--client-cert", str(cpath), "--client-key", str(kpath)) == 1
    assert "was not signed by the CA" in capsys.readouterr().err
    assert not store.has_client()


def test_switching_to_supplied_while_the_signing_key_is_here_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mode recorded as a fact has to be one: `supplied` states the signing key
    is not on this machine."""
    cert, key = _ca_files(tmp_path)
    assert key is not None
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    assert _setup_run("--auth", "supplied") == 1
    said = capsys.readouterr().err
    assert "is on it" in said
    assert "do not delete it" in said, "deleting it can strand the whole fleet"
    assert store.load_broker().auth is AuthMode.MUTUAL, "the mode changed anyway"


def test_switching_to_anonymous_keeps_the_key_without_complaint(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """`anonymous` says nothing about where the signing key lives, only that
    robots keep the certificate they shipped with."""
    cert, key = _ca_files(tmp_path)
    assert key is not None
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    assert _setup_run("--auth", "anonymous") == 0
    assert store.load_broker().auth is AuthMode.ANONYMOUS
    assert store.has_ca(), "the key was taken away"


def test_reissue_in_supplied_mode_says_it_has_nothing_to_issue_with(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Answering "rotate this compromised certificate" with "provisioned
    successfully" and the same certificate is the worst of the options."""
    cert, key = _supplied_store(store, tmp_path)
    robot_cert, robot_key = _their_robot_cert(tmp_path, cert, key, "LR4C123456")
    assert _provision_run("--robot-cert", robot_cert, "--robot-key", robot_key) == 0
    assert _provision_run("--reissue") == 1
    assert "nothing to issue with" in capsys.readouterr().err


def test_a_certificate_that_is_not_valid_yet_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The broker refuses it until the hour it starts, and says nothing useful."""
    from whiskerless import pki

    cert, key = _supplied_store(store, tmp_path)
    future = _future_client(pki.read_pair(Path(cert), Path(key)), "LR4C123456")
    fcert, fkey = tmp_path / "f.crt", tmp_path / "f.key"
    fcert.write_text(future.cert_pem)
    fkey.write_text(future.key_pem)
    assert _provision_run("--robot-cert", str(fcert), "--robot-key", str(fkey)) == 1
    assert "not valid until" in capsys.readouterr().err


def test_a_certificate_with_no_common_name_is_flagged_not_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It works on a broker that does not key off the name, so refusing would
    strand somebody whose setup is fine — but they should know what they lose."""
    from whiskerless import pki

    cert, key = _supplied_store(store, tmp_path)
    nameless = _bare_client(pki.read_pair(Path(cert), Path(key)), "")
    ncert, nkey = tmp_path / "n.crt", tmp_path / "n.key"
    ncert.write_text(nameless.cert_pem)
    nkey.write_text(nameless.key_pem)
    assert _provision_run("--robot-cert", str(ncert), "--robot-key", str(nkey)) == 0
    assert "has no common name" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("pattern", "host", "matches"),
    [
        ("*.example.lan", "mqtt.example.lan", True),
        ("*.EXAMPLE.lan", "mqtt.example.lan", True),
        ("*.example.lan", "example.lan", False),
        ("*.example.lan", "a.b.example.lan", False),
        ("*.example.lan", ".example.lan", False),
        ("mqtt.example.lan", "mqtt.example.lan", True),
        ("mqtt.example.lan", "other.example.lan", False),
    ],
)
def test_a_dns_name_is_compared_the_way_tls_compares_it(
    pattern: str, host: str, matches: bool
) -> None:
    """A false negative here prints advice to replace a certificate that was
    already correct."""
    from whiskerless.cli import _dns_name_matches

    assert _dns_name_matches(pattern, host) is matches


def test_a_rejected_replacement_leaves_this_machines_identity_working(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The store may hold the only copy of the one being replaced."""
    from whiskerless import pki

    cert, key = _supplied_store(store, tmp_path)
    working = store.load_client().cert_pem

    ca = pki.read_pair(Path(cert), Path(key))
    stale = _expired_client(ca, "whiskerless-test")
    scert, skey = tmp_path / "old.crt", tmp_path / "old.key"
    scert.write_text(stale.cert_pem)
    skey.write_text(stale.key_pem)
    assert _setup_run("--client-cert", str(scert), "--client-key", str(skey)) == 1
    assert "already expired" in capsys.readouterr().err
    assert store.load_client().cert_pem == working, "the working identity was consumed"


def test_a_broker_certificate_placed_with_a_wildcard_name_is_not_overwritten(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Signed by this store's CA, and valid for the broker by TLS's rules.
    Overwriting it destroys the private key beside it."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from whiskerless import pki
    from whiskerless.pki import KeyPair

    cert, key = _ca_files(tmp_path)
    assert key is not None
    assert _setup_run("--ca", cert, "--ca-key", key) == 0

    ca = pki.read_pair(Path(cert), Path(key))
    issuer = x509.load_pem_x509_certificate(ca.cert_pem.encode())
    signing = serialization.load_pem_private_key(ca.key_pem.encode(), password=None)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    import datetime as _dt

    now = _dt.datetime.now(_dt.UTC)
    wildcard = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([]))
        .issuer_name(issuer.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=1))
        .not_valid_after(now + _dt.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("*.example.lan")]), False)
        .sign(signing, hashes.SHA256())  # type: ignore[arg-type]
    )
    placed = KeyPair(
        cert_pem=wildcard.public_bytes(serialization.Encoding.PEM).decode(),
        key_pem=leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    store.save_broker_certs(placed)
    assert main(["setup", "--host", "mqtt.example.lan"]) == 0
    assert (store.broker_dir / "server.crt").read_text() == placed.cert_pem


def test_a_ca_dated_into_the_future_is_refused(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stored, it makes every chain fail until that date — including at every
    robot that was given it."""
    import datetime as _dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    later = _dt.datetime.now(_dt.UTC) + _dt.timedelta(days=7)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "not yet")])
    authority = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(later)
        .not_valid_after(later + _dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    fpath = tmp_path / "future-ca.crt"
    fpath.write_text(authority.public_bytes(serialization.Encoding.PEM).decode())
    assert _setup_run("--auth", "anonymous", "--ca", str(fpath)) == 1
    assert "not valid until" in capsys.readouterr().err


def test_a_broker_certificate_dated_into_the_future_is_reported(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    store.save_broker_certs(_future_client(pki.read_pair(Path(cert), Path(key)), "192.0.2.10"))
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert "not valid until" in capsys.readouterr().err


def test_a_cached_supplied_certificate_that_has_expired_stops_the_provision(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A WiFi password change is a re-provision, and what was in date when it was
    filed may not be now."""
    from whiskerless import pki

    cert, key = _supplied_store(store, tmp_path)
    stale = _expired_client(pki.read_pair(Path(cert), Path(key)), "LR4C123456")
    store.save_robot_identity("LR4C123456", stale)
    assert _provision_run() == 1
    assert "already expired" in capsys.readouterr().err


def test_a_cached_issued_certificate_that_has_expired_is_replaced(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """This store signs, so an expired cached certificate is one mint away —
    writing it would produce a robot the broker refuses."""
    from whiskerless import pki

    seed(store)
    stale = _expired_client(store.load_ca(), "LR4C123456")
    store.save_robot_identity("LR4C123456", stale)
    assert _provision_run() == 0
    assert "has expired — issuing another" in capsys.readouterr().out
    assert pki.certificate_common_name(
        store.load_robot_identity("LR4C123456").cert_pem
    ) == "LR4C123456"
    assert store.load_robot_identity("LR4C123456").cert_pem != stale.cert_pem


def test_an_expired_machine_certificate_says_why_instead_of_failing_at_tls(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Nothing here can mint a replacement, so this is the only place the reason
    can be given."""
    from whiskerless import pki

    cert, key = _supplied_store(store, tmp_path)
    store.save_client(_expired_client(pki.read_pair(Path(cert), Path(key)), "whiskerless-test"))
    with pytest.raises(RobotProfileError, match="not valid at the moment"):
        store.settings()


def test_a_broker_certificate_of_ours_that_expired_is_reissued(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """This store can sign, so advertising an out-of-date certificate for
    installation would send somebody to restart their broker for nothing."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    store.save_broker_certs(_expired_client(pki.read_pair(Path(cert), Path(key)), "192.0.2.10"))
    capsys.readouterr()
    assert _setup_run() == 0
    assert "it was out of date" in capsys.readouterr().out
    assert pki.is_current((store.broker_dir / "server.crt").read_text())


def test_a_broker_certificate_with_no_key_beside_it_is_not_advertised(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mosquitto cannot serve a certificate without its key, and setup's next line
    tells somebody to install both."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    store.save_broker_certs(pki.issue_server(pki.read_pair(Path(cert), Path(key)), "192.0.2.10"))
    (store.broker_dir / "server.key").unlink()
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert "is not beside it" in capsys.readouterr().err


def test_a_broker_certificate_with_the_wrong_key_is_not_advertised(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    assert key is not None
    ca = pki.read_pair(Path(cert), Path(key))
    store.save_broker_certs(pki.issue_server(ca, "192.0.2.10"))
    (store.broker_dir / "server.key").write_text(pki.issue_server(ca, "192.0.2.10").key_pem)
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0
    assert "is not the key for it" in capsys.readouterr().err


def test_an_expired_authority_stops_a_provision_before_the_robot_is_touched(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An authority managed elsewhere can expire between two robots, and writing
    it produces one that cannot verify the broker — another walk to the machine."""
    import datetime as _dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert, _ = _ca_files(tmp_path)
    assert _setup_run("--auth", "anonymous", "--ca", cert) == 0

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=400)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "old authority")])
    dead = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(past)
        .not_valid_after(past + _dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    store.ca_path.write_text(dead.public_bytes(serialization.Encoding.PEM).decode())
    assert _provision_run() == 1
    assert "already expired" in capsys.readouterr().err


def test_a_certificate_whose_only_san_is_irrelevant_falls_back_to_its_name(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """A URI SAN does not participate in hostname verification, so OpenSSL reads
    the common name and accepts it. Treating any SAN at all as authoritative would
    call this foreign and overwrite it, private key and all."""
    import datetime as _dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from whiskerless import pki
    from whiskerless.pki import KeyPair

    cert, key = _ca_files(tmp_path)
    assert key is not None
    assert _setup_run("--ca", cert, "--ca-key", key) == 0

    ca = pki.read_pair(Path(cert), Path(key))
    issuer = x509.load_pem_x509_certificate(ca.cert_pem.encode())
    signing = serialization.load_pem_private_key(ca.key_pem.encode(), password=None)
    leaf = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.datetime.now(_dt.UTC)
    built = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "192.0.2.10")]))
        .issuer_name(issuer.subject)
        .public_key(leaf.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=1))
        .not_valid_after(now + _dt.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier("urn:whiskerless")]),
            False,
        )
        .sign(signing, hashes.SHA256())  # type: ignore[arg-type]
    )
    placed = KeyPair(
        cert_pem=built.public_bytes(serialization.Encoding.PEM).decode(),
        key_pem=leaf.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    store.save_broker_certs(placed)
    assert _setup_run() == 0
    assert (store.broker_dir / "server.crt").read_text() == placed.cert_pem


# --- diagnose -------------------------------------------------------------------
async def _fake_diagnose(*_: object, **kw: object) -> list[Any]:
    from whiskerless.ble.messages import WifiConnectFailedReason, WifiStationState, WifiStatus

    on_step = kw.get("on_step")
    samples = [
        WifiStatus(WifiStationState.CONNECTING),
        WifiStatus(WifiStationState.CONNECTION_FAILED,
                   fail_reason=WifiConnectFailedReason.AUTH_ERROR),
    ]
    if callable(on_step):
        for index, _sample in enumerate(samples):
            on_step(f"{index:>2}  sample")
    return samples


def test_diagnose_reports_the_robots_own_verdict(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command exists so "blinking blue" becomes an answer. AUTH_ERROR is one
    of the two verdicts that survives the pairing-mode confound, so it must reach
    the user rather than being buried in the sample list."""
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.diagnose_wifi", _fake_diagnose),
    ):
        assert main(["diagnose", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "AUTH_ERROR" in out
    assert "provision" in out, "it must say how to put the robot back"


def test_diagnose_warns_that_it_takes_the_robot_off_wifi(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading status needs pairing mode, and pairing mode wipes the robot's saved
    network. A diagnostic that strands the patient has to say so BEFORE it runs,
    and must not run at all if the answer is no."""
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.diagnose_wifi", _fake_diagnose),
    ):
        assert main(["diagnose"]) == 1
    captured = capsys.readouterr()
    assert "TAKES IT OFF WIFI" in captured.out
    assert "aborted" in captured.err


def test_diagnose_says_so_when_no_robot_is_advertising(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _nothing(**_: object) -> list[Any]:
        return []

    with patch("whiskerless.ble.scan", _nothing):
        assert main(["diagnose", "--yes"]) == 1
    assert "BLINKS YELLOW" in capsys.readouterr().err


# --- picking, naming and saying which robot (backlog #85, #86) ------------------------
def _two(store: RobotProfileStore) -> None:
    seed(store, serial="LR4C111111", name="Upstairs")
    seed(store, serial="LR4C222222", name="Downstairs")


def test_several_robots_and_no_default_still_errors_when_nobody_can_be_asked(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The non-interactive contract, unchanged: scripts and CI get the ambiguity error and a
    non-zero exit, never a hang waiting on stdin nobody is attached to."""
    _two(store)
    with patch("sys.stdin.isatty", return_value=False):
        assert run("state") != 0
    assert "several robots are set up" in capsys.readouterr().err


def test_a_tty_is_offered_the_list_instead_of_being_sent_away(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    _two(store)
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="2"):
        _pick_saved_robot(store)
    out = capsys.readouterr().out
    assert "Upstairs" in out and "Downstairs" in out
    # The serial is shown beside the name so the list can be told apart when two robots share one.
    assert "LR4C111111" in out


def test_the_picker_marks_the_default(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    _two(store)
    store.set_default("LR4C222222")
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="1"):
        _pick_saved_robot(store)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "Downstairs" in ln]
    assert lines and "(default)" in lines[0]


def test_the_picker_returns_the_chosen_robot(store: RobotProfileStore) -> None:
    _two(store)
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="2"):
        chosen = _pick_saved_robot(store)
    assert chosen is not None
    assert chosen.display_name == "Downstairs"


@pytest.mark.parametrize("answer", ["", "0", "3", "banana"])
def test_a_bad_choice_declines_rather_than_guessing(
    store: RobotProfileStore, answer: str
) -> None:
    """Guessing here would act on a robot the person did not pick — and half these commands write."""
    _two(store)
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer):
        assert _pick_saved_robot(store) is None


def test_one_saved_robot_is_never_a_question(store: RobotProfileStore) -> None:
    seed(store, serial="LR4C111111")
    with patch("sys.stdin.isatty", return_value=True):
        assert _pick_saved_robot(store) is None


def test_a_robot_can_be_selected_by_its_name(store: RobotProfileStore) -> None:
    """Being made to type LR4C… for a robot you called "Upstairs" is what stops people naming
    them at all."""
    _two(store)
    assert store.resolve("Upstairs").serial.value == "LR4C111111"


def test_a_serial_wins_over_a_name_that_looks_like_one(store: RobotProfileStore) -> None:
    """The serial is the identity and a name is only a label, so a mischievous name must never
    shadow a real robot."""
    seed(store, serial="LR4C111111", name="Upstairs")
    seed(store, serial="LR4C222222", name="LR4C111111")
    assert store.resolve("LR4C111111").display_name == "Upstairs"


def test_rename_changes_the_label_and_nothing_else(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(store, serial="LR4C111111", name="Upstairs")
    assert run("rename", "Upstairs", "Attic") == 0
    after = store.load("LR4C111111")
    assert after.display_name == "Attic"
    # Identity is untouched: topics, the client-id and the certificate CN all key on the serial.
    assert after.serial.value == "LR4C111111"
    assert "Upstairs is now Attic" in capsys.readouterr().out


def test_rename_refuses_an_empty_name(store: RobotProfileStore) -> None:
    seed(store, serial="LR4C111111", name="Upstairs")
    assert run("rename", "Upstairs", answer="") == 1
    assert store.load("LR4C111111").display_name == "Upstairs"


def test_a_write_command_names_the_robot_it_is_about_to_act_on(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half of #85 with teeth. With two robots saved, `whiskerless power` used to toggle one
    without ever printing which — and a robot switched off has left the network, so nothing over
    MQTT brings it back. Named even when the choice was unambiguous: the point is to make the
    wrong-robot mistake visible at the moment it matters, not only when the CLI was unsure."""
    seed(store, serial="LR4C111111", name="Upstairs")
    run("power", "--serial", "LR4C111111")
    assert "acting on Upstairs" in capsys.readouterr().out


def test_a_read_command_stays_quiet(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the commands that CHANGE something announce. `read` on a one-robot machine printing a
    banner every time is noise, and noise is what stops people reading the banner that matters."""
    seed(store, serial="LR4C111111", name="Upstairs")
    run("read", "0x01", "--serial", "LR4C111111")
    assert "acting on" not in capsys.readouterr().out


def test_the_picker_choice_is_what_the_command_acts_on(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: ambiguous, a person present, and the robot they picked is the one announced."""
    _two(store)
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="2"):
        run("power")
    assert "acting on Downstairs" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("command", "extra"),
    [("power", ()), ("wifi-toggle", ()), ("empty-cycle", ()), ("clean-cycle", ())],
)
def test_a_confirmation_names_the_robot_it_is_asking_about(
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str],
    command: str, extra: tuple[str, ...],
) -> None:
    """A confirmation that does not say WHICH robot is not informed consent. `monitor` already
    resolved before printing its banner so it could not say "monitoring None"; that reasoning had
    never reached the four commands where getting it wrong is the expensive direction."""
    seed(store, serial="LR4C111111", name="Upstairs")
    run(command, "--serial", "LR4C111111", *extra, answer="no")
    assert "Upstairs" in capsys.readouterr().out


def test_a_store_from_a_newer_version_is_refused_rather_than_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_open()` is what refuses a store a newer release wrote. Caching before it ran meant the
    refusal was swallowed by the update-check block, and every later command reused an unopened
    store — free to rewrite profile data this version has already said it cannot read."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".layout").write_text('{"layout_version": "9999", "min_tool_version": "99.0.0"}\n')
    args = SimpleNamespace(store=None)
    with pytest.raises(RobotProfileError):
        cli_store(args)
    assert args.store is None, "an unopened store was cached and would be reused"


def test_an_explicit_serial_with_no_saved_profile_still_names_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fully explicit path returned before the announcement — and a write to a robot with no
    saved profile is the one case where nobody can check the target against a name."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    args = SimpleNamespace(serial="LR4C0000000001", command="set", store=None)
    chosen = _profile(args)
    assert chosen.serial.value == "LR4C0000000001"
    assert "acting on" in capsys.readouterr().out


def test_forget_accepts_the_display_name_it_now_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`resolve()` accepts a display name, but `forget` reparsed the argument as a serial: it
    looked for `robots/UPSTAIRS`, failed, and left the robot saved. A name with a space in it did
    not survive `Serial()` at all."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    store = RobotProfileStore.from_env()
    store.save(RobotProfile(serial=Serial("LR4C123456"), name="Up Stairs"))
    assert main(["forget", "Up Stairs", "--yes"]) == 0
    assert list(RobotProfileStore.from_env().list_robot_profiles()) == []


def test_an_ambiguous_name_is_refused_rather_than_treated_as_a_serial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name meaning two robots is not an unknown serial. Treating it as one built a topic out of
    the name — a robot that does not exist — while the command reported success."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    store = RobotProfileStore.from_env()
    store.save(RobotProfile(serial=Serial("LR4C111111"), name="Bathroom"))
    store.save(RobotProfile(serial=Serial("LR4C222222"), name="Bathroom"))
    assert main(["state", "--serial", "Bathroom"]) == 1
    assert "more than one robot" in capsys.readouterr().err


def test_a_migration_that_fails_while_stamping_still_reports_what_it_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_open()` retires the legacy broker fields and then stamps `.layout`. Failing between the
    two left the facts about what was discarded only on that object — and on the retry the legacy
    fields are gone, so the one-time warning could never be reconstructed."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))

    def _boom(self, legacy):
        # The store is frozen, and `migration` is a mutable record on it — which is how the real
        # `_open()` records what it retired before it stamps the layout.
        object.__setattr__(self, "migration", replace(self.migration, from_legacy=True,
                                                      moved_to=tmp_path))
        raise OSError("disk full")

    monkeypatch.setattr(RobotProfileStore, "_open", _boom)
    assert main(["robots"]) == 1
    assert str(tmp_path) in capsys.readouterr().err


def test_calibration_saves_against_the_robot_the_picker_chose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With several robots and no default the picker asks which one. Re-resolving the empty
    argument afterwards asked again, or gave up and threw away a calibration it had just taken."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    store = RobotProfileStore.from_env()
    store.save(RobotProfile(serial=Serial("LR4C111111"), name="Upstairs"))
    store.save(RobotProfile(serial=Serial("LR4C222222"), name="Downstairs"))
    args = SimpleNamespace(serial=None, command="calibrate", store=None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with patch("builtins.input", return_value="1"):
        chosen = _profile(args)
    assert store.resolve(chosen.serial.value).serial == chosen.serial


def test_a_concurrent_calibration_endpoint_is_not_erased(tmp_path: Path) -> None:
    """Writing both endpoints from a profile read earlier meant an empty calibration carried its
    stale `None` full value back over a full calibration that had completed in between — erasing a
    finished endpoint while reporting success."""
    store = RobotProfileStore(tmp_path)
    store.save(RobotProfile(serial=Serial("LR4C123456")))
    store.update("LR4C123456", lambda c: replace(c, litter_full_mm=40))
    store.update("LR4C123456", lambda c: replace(c, litter_empty_mm=120))
    final = RobotProfileStore(tmp_path).load("LR4C123456")
    assert (final.litter_full_mm, final.litter_empty_mm) == (40, 120)


def test_a_mistyped_saved_name_is_refused_rather_than_invented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`Serial()` accepts almost any word — it is a containment rule for a directory name — so a
    typo for a saved name became a valid one-off and the CLI published to a topic no robot
    subscribes to, while an edge-triggered command reported success."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    store = RobotProfileStore.from_env()
    store.save(RobotProfile(serial=Serial("LR4C123456"), name="Upstairs"))
    assert main(["state", "--serial", "Upstair"]) == 1
    assert "UPSTAIR" not in capsys.readouterr().out


def test_an_unsaved_but_real_serial_still_works_as_a_one_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one-off path is how this behaved before there was a store, and it must survive."""
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path))
    args = SimpleNamespace(serial="LR4C000000", command="state", store=None)
    assert _profile(args).serial.value == "LR4C000000"
