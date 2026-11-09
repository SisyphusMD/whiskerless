"""The shipped examples reference entities this integration actually creates.

`docs/setup/home-assistant.md` links `examples/` as ready-to-copy, so an entity
that is renamed or moved between platforms turns those files into instructions
that silently do nothing. That already happened once: the dashboard card kept
listing `select.<robot>_clean_cycle_wait_time` after the control became a number,
and the only thing that noticed was someone reading it.

References are collected structurally — every `entity_id` / `entity` value in the
YAML, including the fenced blocks inside the README — rather than by matching
entity-shaped text. A pattern has to describe what a correct reference looks
like, so a mistyped one stops matching and quietly leaves the set being checked;
a key lookup keeps the typo and reports it.

Entity IDs are generated from the *translated name*, not the description key, so
this compares against a real set-up integration rather than a key list.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from custom_components.whiskerless.const import (
    CONF_CLOUD_HOST,
    CONF_CLOUD_PREFIX,
    CONF_IDENTITY_DIR,
    CONF_KIND,
    CONF_LOCAL_PREFIX,
    CONF_SERIAL,
    DEFAULT_CLOUD_HOST,
    DEFAULT_CLOUD_PREFIX,
    DEFAULT_IDENTITY_DIR,
    DEFAULT_LOCAL_PREFIX,
    DOMAIN,
    KIND_CLOUD_BRIDGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_FENCED_YAML = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)


def _entity_values(node: Any) -> set[str]:
    """Every `entity_id` / `entity` value anywhere in a loaded YAML document."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("entity_id", "entity"):
                found |= {value} if isinstance(value, str) else set(value or ())
            found |= _entity_values(value)
    elif isinstance(node, list):
        for item in node:
            found |= _entity_values(item)
    return found


def _defined_scripts(node: Any) -> set[str]:
    """The `script.<id>` entities a document defines under a top-level `script:` key."""
    if isinstance(node, dict) and isinstance(node.get("script"), dict):
        return {f"script.{name}" for name in node["script"]}
    return set()


def _documents() -> list[Any]:
    docs: list[Any] = []
    for path in sorted(EXAMPLES.rglob("*")):
        text = path.read_text(encoding="utf-8") if path.suffix in {".yaml", ".md"} else None
        if text is None:
            continue
        blocks = _FENCED_YAML.findall(text) if path.suffix == ".md" else [text]
        docs.extend(yaml.safe_load(block) for block in blocks)
    return docs


async def test_the_examples_reference_real_entities(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str, tmp_path: Path
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    bridge = await _setup_bridge(hass, tmp_path)

    referenced, defined = set(), set()
    for document in _documents():
        referenced |= _entity_values(document)
        defined |= _defined_scripts(document)
    # Only Home Assistant's own sentinels are exempt. Dropping everything without
    # a dot would look tidier and would discard `sensor_litter_robot_4_status`,
    # which is precisely the typo worth reporting.
    referenced -= {"all", "none"}
    assert referenced, "no entity references found — has the examples layout changed?"

    # Disabled-by-default entities are legitimate to document, so compare against
    # everything the integration can produce, not only what is currently enabled.
    registry = er.async_get(hass)
    real = defined | {
        entry.entity_id
        for config_entry in (mock_config_entry, bridge)
        for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id)
    }
    missing = sorted(referenced - real)
    assert not missing, f"examples reference entities that do not exist: {missing}"


async def _setup_bridge(hass: HomeAssistant, config_dir: Path) -> MockConfigEntry:
    """A cloud bridge entry as the cloud-bridge examples assume it: serial LR4C000001."""
    hass.config.config_dir = str(config_dir)
    identity = config_dir / DEFAULT_IDENTITY_DIR
    identity.mkdir(parents=True)
    for name in ("root_ca.pem", "device.crt", "device.key"):
        (identity / name).write_text("-----BEGIN SYNTHETIC-----\nAA==\n-----END SYNTHETIC-----\n")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Cloud bridge LR4C000001",
        unique_id=f"{KIND_CLOUD_BRIDGE}_LR4C000001",
        data={
            CONF_KIND: KIND_CLOUD_BRIDGE,
            CONF_SERIAL: "LR4C000001",
            CONF_CLOUD_HOST: DEFAULT_CLOUD_HOST,
            CONF_LOCAL_PREFIX: DEFAULT_LOCAL_PREFIX,
            CONF_CLOUD_PREFIX: DEFAULT_CLOUD_PREFIX,
            CONF_IDENTITY_DIR: DEFAULT_IDENTITY_DIR,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
