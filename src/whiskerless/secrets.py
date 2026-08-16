"""Secrets in the OS keychain, or nowhere.

The profile store deliberately writes no secret to disk: a 0600 file beside the
config is not "stored securely" however it is described, and it follows people
into backups and dotfile sync without ever looking like a secret. The keychain is
the one place that genuinely is different — encrypted at rest, access-controlled
by the OS, and not swept up by a `cp -r ~`.

Two secrets are worth keeping, for opposite reasons. The **broker password** is
needed by every command that talks to the robot, so without storage the choice is
retyping it constantly or exporting it into the environment, and the environment
is where secrets leak into shell history and `ps`. The **WiFi passphrase** is
needed rarely — but *rarely* means "at the worst moment", halfway through a
re-provision at the machine, and a bench session that re-provisions four times
types it four times.

Every function here degrades rather than fails. ``keyring`` is not installed on
Linux by default (see pyproject), a headless box often has no Secret Service at
all, a locked keychain can refuse mid-command, and ``WHISKERLESS_NO_KEYRING``
turns the whole thing off. None of that is an error: it means the caller asks the
human instead, exactly as it did before.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

#: Set to any non-empty value to keep whiskerless out of the keychain entirely.
#: Wanted by more than tests: a shared account, a headless box whose Secret
#: Service prompts on a display nobody is looking at, and anyone who would simply
#: rather type the password.
DISABLE_ENV = "WHISKERLESS_NO_KEYRING"

#: One service for the whole tool, so a user can find and revoke everything by
#: searching their keychain for a single obvious name.
SERVICE = "whiskerless"


def _backend() -> object | None:
    """The keyring module, or None if there is no usable keychain here.

    Import is lazy and failure is total-but-quiet: an optional dependency that
    is absent, a platform with no backend, and a keyring that raises on init all
    mean the same thing to every caller — ask the human.
    """
    if os.environ.get(DISABLE_ENV):
        return None
    try:
        import keyring
        from keyring.backends.fail import Keyring as NoBackend
    except ImportError:
        return None
    try:
        # keyring always resolves to SOMETHING; on a machine with no keychain
        # that something is the fail backend, which raises on first use rather
        # than at import. Detecting it here keeps every caller's path identical
        # to "keyring is not installed".
        if isinstance(keyring.get_keyring(), NoBackend):
            return None
    except Exception as exc:  # noqa: BLE001 — see module docstring
        log.debug("no usable keyring backend: %s", exc)
        return None
    return keyring


def available() -> bool:
    """Whether anything can be stored at all — for telling the user, not gating."""
    return _backend() is not None


def broker_key(username: str, host: str, port: int) -> str:
    """One entry per login per broker, not per robot.

    Two robots on the same broker share one password; keying by robot would ask
    for the same secret twice and let the copies drift apart. The port is part of
    the broker's identity, not decoration: two brokers on one host, split by port,
    are two different servers and may well want two different logins.
    """
    return f"broker:{username}@{host}:{port}"


def wifi_key(ssid: str) -> str:
    """One entry per network. Robots on the same SSID share the passphrase."""
    return f"wifi:{ssid}"


def get(key: str) -> str | None:
    """The stored secret, or None if there is none — or no keychain to ask."""
    backend = _backend()
    if backend is None:
        return None
    try:
        stored = backend.get_password(SERVICE, key)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — a locked or broken keychain is not fatal
        log.debug("keyring read failed for %r: %s", key, exc)
        return None
    return str(stored) if stored is not None else None


def put(key: str, secret: str) -> bool:
    """Store a secret. False means it was not stored, which is never fatal."""
    backend = _backend()
    if backend is None or not secret:
        return False
    try:
        backend.set_password(SERVICE, key, secret)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — declining to store is not failing
        log.debug("keyring write failed for %r: %s", key, exc)
        return False
    return True


def forget(key: str) -> bool:
    """Remove a stored secret. False if there was nothing to remove."""
    backend = _backend()
    if backend is None:
        return False
    try:
        backend.delete_password(SERVICE, key)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — absent is the same as removed
        log.debug("keyring delete failed for %r: %s", key, exc)
        return False
    return True
