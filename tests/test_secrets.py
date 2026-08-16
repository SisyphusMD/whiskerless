"""The keychain wrapper: never raises, never guesses, never stores silently."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from whiskerless import secrets


def test_a_secret_survives_a_round_trip(keychain: dict[str, str]) -> None:
    assert secrets.put("broker:me@10.0.0.1", "hunter2") is True
    assert keychain == {"broker:me@10.0.0.1": "hunter2"}
    assert secrets.get("broker:me@10.0.0.1") == "hunter2"
    assert secrets.forget("broker:me@10.0.0.1") is True
    assert secrets.get("broker:me@10.0.0.1") is None


def test_nothing_stored_reads_as_nothing_stored(keychain: dict[str, str]) -> None:
    assert secrets.get("wifi:never-seen") is None


def test_an_empty_secret_is_not_stored(keychain: dict[str, str]) -> None:
    """A blank answer at a password prompt means "skip", not "the password is ''"."""
    assert secrets.put("wifi:home", "") is False
    assert keychain == {}


def test_the_keys_are_shared_by_broker_and_by_network() -> None:
    """Two robots behind one broker share a password; keying per robot would ask
    for the same secret twice and let the copies drift apart."""
    assert secrets.broker_key("mqtt-user", "10.0.0.1", 8883) == "broker:mqtt-user@10.0.0.1:8883"
    assert secrets.broker_key("mqtt-user", "10.0.0.2", 8883) != secrets.broker_key(
        "mqtt-user", "10.0.0.1", 8883
    )
    assert secrets.broker_key("mqtt-user", "10.0.0.1", 1883) != secrets.broker_key(
        "mqtt-user", "10.0.0.1", 8883
    ), "two brokers on one host, split by port, are two servers"
    assert secrets.wifi_key("Casa") == "wifi:Casa"


def test_the_env_var_turns_the_whole_thing_off(keychain: dict[str, str]) -> None:
    """Wanted by more than tests: shared accounts, headless boxes, and people who
    would simply rather type it."""
    keychain["wifi:Casa"] = "already-here"
    assert secrets.available() is True
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(secrets.DISABLE_ENV, "1")
        assert secrets.available() is False
        assert secrets.get("wifi:Casa") is None
        assert secrets.put("wifi:Casa", "new") is False
        assert secrets.forget("wifi:Casa") is False
    assert keychain == {"wifi:Casa": "already-here"}


def test_no_keyring_installed_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """It is not a dependency on Linux, which is exactly where a headless box is."""
    monkeypatch.delenv(secrets.DISABLE_ENV, raising=False)
    # None in sys.modules is the documented way to make an import raise.
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert secrets.available() is False
    assert secrets.get("wifi:Casa") is None
    assert secrets.put("wifi:Casa", "x") is False
    assert secrets.forget("wifi:Casa") is False


def test_a_machine_with_no_backend_reads_as_no_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """keyring always resolves to SOMETHING; with no keychain that something
    raises on first use, which callers must never see."""
    import keyring
    from keyring.backends.fail import Keyring as NoBackend

    monkeypatch.delenv(secrets.DISABLE_ENV, raising=False)
    monkeypatch.setattr(keyring, "get_keyring", NoBackend)
    assert secrets.available() is False


def test_a_backend_that_raises_on_init_reads_as_no_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring

    def _explode() -> Any:
        raise RuntimeError("no Secret Service on this box")

    monkeypatch.delenv(secrets.DISABLE_ENV, raising=False)
    monkeypatch.setattr(keyring, "get_keyring", _explode)
    assert secrets.available() is False


@pytest.mark.parametrize(
    ("call", "attempt", "refused"),
    [
        ("get_password", lambda: secrets.get("wifi:Casa"), None),
        ("set_password", lambda: secrets.put("wifi:Casa", "x"), False),
        ("delete_password", lambda: secrets.forget("wifi:Casa"), False),
    ],
)
def test_a_locked_keychain_degrades_instead_of_failing(
    keychain: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    call: str,
    attempt: Any,
    refused: object,
) -> None:
    """A keychain can refuse mid-command — locked, or the user clicked Deny. That
    must cost the command a prompt, not an exception."""
    import keyring

    def _refuse(*_args: object) -> Any:
        raise RuntimeError("user denied access")

    monkeypatch.setattr(keyring, call, _refuse)
    assert attempt() is refused


def test_forgetting_something_that_was_never_there_is_false(keychain: dict[str, str]) -> None:
    """The fake backend raises KeyError, exactly as a real one raises
    PasswordDeleteError — absent and removed are the same outcome."""
    assert secrets.forget("wifi:never-seen") is False
