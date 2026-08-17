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
    # A developer who exported this for a real backup would otherwise silently
    # satisfy the prompts these tests exist to exercise.
    monkeypatch.delenv("WHISKERLESS_BACKUP_PASSWORD", raising=False)
