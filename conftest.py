"""Root pytest config.

The integration tests under ``tests/integration`` need Home Assistant's test
harness (``pytest-homeassistant-custom-component``, Python 3.13). When that isn't
installed, skip them so the standalone library tests still run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

collect_ignore: list[str] = []

try:
    import homeassistant  # noqa: F401
except ImportError:
    # Skip the whole directory (its package __init__ imports Home Assistant).
    collect_ignore = ["tests/integration"]


@pytest.fixture(autouse=True)
def _isolated_profile_store(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep every test out of the developer's real ``~/.whiskerless``.

    The store resolves its root from the environment, so without this a test run
    would read — and `forget` would delete — the machine's own saved robots.
    """
    root: Path = tmp_path_factory.mktemp("whiskerless-home")
    monkeypatch.setenv("WHISKERLESS_HOME", str(root))
    # And out of the developer's real keychain. There is no tmp_path equivalent
    # for a keychain, so the only safe default is off: a test that means to
    # exercise storage fakes the backend, and one that forgets cannot write a
    # password into the login keyring of whoever ran the suite.
    monkeypatch.setenv("WHISKERLESS_NO_KEYRING", "1")


@pytest.fixture
def keychain(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A working keychain that lives in a dict, for the tests that need one.

    The exact inverse of the autouse fixture above: it turns storage back on for
    one test, against a fake backend. ``keyring`` delegates its module-level
    functions to whichever backend it resolved, so replacing those functions
    replaces the whole store without caring which platform is underneath.
    """
    import keyring

    from whiskerless import secrets

    vault: dict[str, str] = {}
    monkeypatch.delenv(secrets.DISABLE_ENV, raising=False)
    # Anything that is not the fail backend. What it IS never matters: nothing
    # calls through the object, only through the module functions faked below.
    monkeypatch.setattr(keyring, "get_keyring", lambda: object())
    monkeypatch.setattr(keyring, "get_password", lambda _service, key: vault.get(key))
    monkeypatch.setattr(
        keyring, "set_password", lambda _service, key, value: vault.__setitem__(key, value)
    )
    monkeypatch.setattr(keyring, "delete_password", lambda _service, key: vault.pop(key))
    return vault
