"""Root pytest config.

The integration tests under ``tests/integration`` need Home Assistant's test
harness (``pytest-homeassistant-custom-component``, Python 3.13). When that isn't
installed, skip them so the standalone library tests still run.
"""

from __future__ import annotations

collect_ignore: list[str] = []

try:
    import homeassistant  # noqa: F401
except ImportError:
    # Skip the whole directory (its package __init__ imports Home Assistant).
    collect_ignore = ["tests/integration"]
