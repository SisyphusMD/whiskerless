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
from whiskerless.profiles import Broker, ProfileStore, RobotProfile, Serial

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
    """A saved robot, plus the one broker and CA every robot in a store shares."""
    if not store.has_broker():
        store.save_broker(Broker(host="192.0.2.10"))
    if not store.has_ca_cert():
        store.save_ca_cert_only(CA)

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


_SHARED_CA: Path | None = None


def _shared_ca_file() -> str:
    """A CA file on disk for helpers that have no tmp_path of their own."""
    global _SHARED_CA
    if _SHARED_CA is None:
        import tempfile

        _SHARED_CA = Path(tempfile.mkdtemp()) / "ca.pem"
        _SHARED_CA.write_text(CA)
    return str(_SHARED_CA)


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
    store.save(RobotProfile(serial=Serial("LR4C123456", verified=True)))
    assert run("robots") == 0
    assert "unconfirmed" not in capsys.readouterr().out


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


# --- flags override, but only where given -------------------------------------
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


def test_debug_re_raises_so_a_bug_report_has_a_traceback(store: ProfileStore) -> None:
    with pytest.raises(WhiskerlessError):
        main(["state", "--debug"])  # nothing set up: a ProfileError


def test_the_debug_environment_variable_does_the_same(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WHISKERLESS_DEBUG", "1")
    with pytest.raises(WhiskerlessError):
        main(["state"])


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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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


def test_a_failed_provisioning_saves_nothing(store: ProfileStore, tmp_path: Path) -> None:
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
    with pytest.raises(ProfileError):
        store.load("LR4C123456")


def test_a_dry_run_saves_nothing_and_says_so(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    with pytest.raises(ProfileError):
        store.load("LR4C123456")


def test_the_first_robot_provisioned_becomes_the_default(
    store: ProfileStore, tmp_path: Path
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
    store: ProfileStore, tmp_path: Path
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store = ProfileStore.from_env()
    if not store.has_broker():
        store.save_broker(Broker(host="192.0.2.10"))
    if not store.has_ca_cert():
        store.save_ca_cert_only(ca.read_text())
    return [
        "provision", "--serial", "LR4C123456",
        "--wifi-ssid", "home", "--wifi-pass", "secret", "--yes", *extra,
    ]


def _prepared(store: ProfileStore | None = None, *, with_key: bool = False) -> None:
    """What `whiskerless setup` leaves behind, without running it."""
    from whiskerless import pki

    store = store or ProfileStore.from_env()
    if not store.has_broker():
        store.save_broker(Broker(host="192.0.2.10"))
    if not store.has_ca_cert():
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


# --- what the robot gets for an identity --------------------------------------
def _provision_output(store: ProfileStore, *extra: str) -> str:
    _prepared(store)
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        main(["provision", "--serial", "LR4C123456",
              "--wifi-ssid", "home", "--wifi-pass", "pw", "--yes", *extra])
    return ""


def test_no_ca_key_says_loudly_that_the_broker_must_allow_anonymous(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Someone who expected mutual TLS and gets an anonymous listener has a broker
    standing open, and now is the only moment that is cheap to discover."""
    _provision_output(store)
    out = capsys.readouterr().out
    assert "NO CA KEY" in out
    assert "MUST therefore accept anonymous clients" in out
    assert "Whisker factory certificate (unchanged)" in out


def test_a_ca_we_can_sign_with_means_the_robot_gets_our_identity(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    _provision_output(store)
    out = capsys.readouterr().out
    assert "NO CA KEY" not in out
    assert "issued by your CA, CN=LR4C123456" in out


def test_the_identity_write_can_be_declined_even_with_a_ca(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An exit for the person who reads what it does and would rather not."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    ca = tmp_path / "ca.crt"
    ca.write_text(CA)
    _provision_output(store, "--no-client-cert")
    assert "NO CA KEY" in capsys.readouterr().out


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


def _first_run(store: ProfileStore, answers: list[str], *extra: str) -> None:
    """Interactive `setup`, then a provision — the order a first-time user takes."""
    it = iter(answers)
    with (
        patch("whiskerless.cli.sys.stdin.isatty", lambda: True),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", lambda _p="": next(it)),
        patch("whiskerless.cli.getpass.getpass", return_value="pw"),
    ):
        main(["setup", "--host", "192.0.2.10", *extra])
    if not ProfileStore.from_env().has_ca_cert():
        return  # setup declined or failed; nothing to provision onto
    with (
        patch("whiskerless.ble.scan", _fake_scan),
        patch("whiskerless.ble.read_device_mac", _fake_mac),
        patch("whiskerless.ble.provision_robot", _fake_provision(success=True)),
    ):
        main(["provision", "--serial", "LR4C123456",
              "--wifi-ssid", "home", "--wifi-pass", "pw", "--yes"])


def test_a_fresh_machine_is_offered_a_certificate_authority(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regenerating would strand every robot provisioned to trust the old one."""
    _first_run(store, [""])
    first = store.ca_path.read_text()
    capsys.readouterr()
    _first_run(store, [])
    assert store.ca_path.read_text() == first
    assert "NO CERTIFICATE AUTHORITY" not in capsys.readouterr().out


def test_a_supplied_ca_and_key_are_copied_into_the_store(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Copied, not remembered by path: a path breaks when the USB stick comes out."""
    cert, key = _ca_files(tmp_path)
    _first_run(store, ["2", cert, key])
    assert store.has_ca()
    assert store.ca_path.read_text() == Path(cert).read_text()


def test_a_supplied_ca_without_its_key_cannot_issue(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deliberate arrangement — the key lives in a secrets manager — not an
    unfinished one."""
    cert, _ = _ca_files(tmp_path, with_key=False)
    _first_run(store, ["2", cert, ""])
    assert store.has_ca_cert() and not store.has_ca()
    out = capsys.readouterr().out
    assert "NO CA KEY" in out
    assert "Whisker factory certificate (unchanged)" in out


def test_a_ca_certificate_on_file_is_not_asked_about_again(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, _ = _ca_files(tmp_path, with_key=False)
    _first_run(store, ["2", cert, ""])
    capsys.readouterr()
    _first_run(store, [])
    assert "NO CERTIFICATE AUTHORITY" not in capsys.readouterr().out


def test_a_server_certificate_is_missing_a_ca_and_says_so(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, key = _ca_files(tmp_path)
    _first_run(store, ["2", str(tmp_path / "nope.crt"), cert, key])
    assert "no such file" in capsys.readouterr().err


def test_an_unattended_run_with_no_ca_at_all_explains_the_flags(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
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


def test_the_issued_certificate_serial_is_recorded(store: ProfileStore) -> None:
    """The only trace kept of a robot's certificate, and it is not secret."""
    _first_run(store, [""])
    assert store.load("LR4C123456").cert_serial


def _setup_run(*extra: str) -> int:
    """`whiskerless setup` — this machine, its broker and its certificates."""
    return main(["setup", "--host", "192.0.2.10", *extra])


def _flag_run(store: ProfileStore, *setup_flags: str, provision: tuple[str, ...] = ()) -> int:
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
    store: ProfileStore, tmp_path: Path
) -> None:
    cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0
    assert store.has_ca()
    assert store.load("LR4C123456").cert_serial, "a robot certificate was issued"


def test_a_ca_key_without_its_certificate_says_why_both_are_needed(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca-key", key) == 1
    assert "--ca-key needs --ca" in capsys.readouterr().err


def test_a_client_certificate_can_be_supplied_by_flag(
    store: ProfileStore, tmp_path: Path
) -> None:
    """For somebody whose CA key lives elsewhere and cannot issue here."""
    from whiskerless import pki

    cert, key = _ca_files(tmp_path)
    ca = pki.read_pair(Path(cert), Path(key))
    mine = pki.issue_client(ca, "whiskerless-test")
    cpath, kpath = tmp_path / "c.crt", tmp_path / "c.key"
    cpath.write_text(mine.cert_pem)
    kpath.write_text(mine.key_pem)
    assert _flag_run(store, "--ca", cert, "--client-cert", str(cpath),
                     "--client-key", str(kpath)) == 0
    assert store.has_client()
    assert store.load_client().cert_pem == mine.cert_pem


def test_half_a_client_identity_is_refused(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, _key = _ca_files(tmp_path, with_key=False)
    assert _flag_run(store, "--ca", cert, "--client-cert", cert) == 1
    assert "go together" in capsys.readouterr().err


def test_an_expired_ca_is_refused(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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




def test_the_optional_ca_key_question_is_skipped_without_a_terminal() -> None:
    """`_ask(allow_skip=True)` must never be the thing that hangs a scripted run
    on a question it was never going to answer."""
    from whiskerless.cli import _ask, _readable_path

    with patch("whiskerless.cli.sys.stdin.isatty", lambda: False):
        assert _ask("path: ", None, _readable_path, allow_skip=True) == ""


def test_a_different_ca_is_refused_rather_than_swapped_in(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path
) -> None:
    """Re-running with the same files is idempotent, not an error."""
    cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0


def test_an_imported_ca_also_gives_this_machine_an_identity(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Otherwise the robot gets a certificate and the CLI does not, and a broker
    running `require_certificate true` refuses every command afterwards."""
    cert, key = _ca_files(tmp_path)
    assert _flag_run(store, "--ca", cert, "--ca-key", key) == 0
    assert store.has_client(), "the CLI can identify itself too"


@pytest.mark.parametrize("flag", [["--port", "1884"], ["--insecure"]])
def test_setup_refuses_to_point_the_cli_where_the_robot_cannot_follow(
    store: ProfileStore, flag: list[str]
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path
) -> None:
    """A scripted run cannot answer a question, so a re-run with nothing new must
    fall back to what is saved rather than prompting for a host it already has."""
    cert, key = _ca_files(tmp_path)
    assert _setup_run("--ca", cert, "--ca-key", key) == 0
    with patch("whiskerless.cli.sys.stdin.isatty", lambda: False):
        assert main(["setup"]) == 0
    assert store.load_broker().host == "192.0.2.10"


def test_setup_asks_for_the_broker_when_there_is_nothing_saved(
    store: ProfileStore, tmp_path: Path
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
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
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


def test_the_same_broker_keeps_the_certificate_it_already_has(store: ProfileStore) -> None:
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


def test_a_moved_broker_with_no_signing_key_is_told_to_replace_it(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing here can reissue it, and silently printing the stale one as a file
    to install is the failure this guard exists to prevent."""
    from whiskerless import pki

    ca = pki.generate_ca()
    store.save_ca_cert_only(ca.cert_pem)
    store.save_broker_certs(pki.issue_server(ca, "192.0.2.10"))
    assert main(["setup", "--host", "192.0.2.99"]) == 0
    assert "not 192.0.2.99" in capsys.readouterr().err


def test_a_broker_certificate_that_cannot_be_read_is_reported_not_replaced(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Importing a CA generates nothing to install; sending somebody looking for
    "the files above" when nothing was printed above is a wild goose chase."""
    cert, _ = _ca_files(tmp_path, with_key=False)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert]) == 0
    out = capsys.readouterr().out
    assert "install the files above" not in out
    assert "signed by this CA" in out


def test_bringing_your_own_ca_and_key_also_gets_a_broker_certificate(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from whiskerless import pki

    store.save_broker_certs(pki.issue_server(pki.generate_ca("not yours"), "192.0.2.10"))
    cert, _ = _ca_files(tmp_path, with_key=False)
    assert main(["setup", "--host", "192.0.2.10", "--ca", cert]) == 0
    assert "cannot verify a broker" in capsys.readouterr().err


def test_an_unreadable_broker_certificate_file_does_not_crash_setup(
    store: ProfileStore, tmp_path: Path
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
    store: ProfileStore, tmp_path: Path
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
