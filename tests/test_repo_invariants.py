"""Repository-wide invariants that no other check enforces.

Each of these found a real defect during the work that added them, and each was
only ever verified by someone remembering to look. They are cheap, they need
neither Home Assistant nor a broker, and they fail on the file that drifted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
INTEGRATION = REPO / "custom_components" / "whiskerless"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_shipped_english_matches_the_source_strings() -> None:
    """`strings.json` is the source; `translations/en.json` is what users read.

    Home Assistant renders the translation, so a key edited in one and not the
    other is invisible in review and wrong on the dashboard.
    """
    assert _json(INTEGRATION / "strings.json") == _json(INTEGRATION / "translations" / "en.json")


def test_every_icon_domain_is_a_platform_the_integration_ships() -> None:
    """An icon filed under a non-platform is never rendered by anything.

    Derived from which modules actually register entities, not from every module
    name — the latter would accept `coordinator` or `config_flow` as a domain.
    """
    icons = _json(INTEGRATION / "icons.json").get("entity", {})
    platforms = {
        path.stem
        for path in INTEGRATION.glob("*.py")
        if "AddConfigEntryEntitiesCallback" in path.read_text(encoding="utf-8")
    }
    assert platforms, "no entity platforms found — has the setup signature changed?"
    assert set(icons) <= platforms


# The Integration Quality Scale rules, as of Home Assistant 2026.8. hassfest
# validates this file only for core integrations (`validate_iqs_file` returns
# early when `not integration.core`), so nothing upstream checks ours. Refresh
# from script/hassfest/quality_scale.py when the scale gains a rule.
QUALITY_SCALE_RULES = {
    # Bronze
    "action-setup", "appropriate-polling", "brands", "common-modules",
    "config-flow", "config-flow-test-coverage", "dependency-transparency",
    "docs-actions", "docs-conditions", "docs-high-level-description",
    "docs-installation-instructions", "docs-removal-instructions", "docs-triggers",
    "entity-event-setup", "entity-unique-id", "has-entity-name", "runtime-data",
    "test-before-configure", "test-before-setup", "unique-config-entry",
    # Silver
    "action-exceptions", "config-entry-unloading", "docs-configuration-parameters",
    "docs-installation-parameters", "entity-unavailable", "integration-owner",
    "log-when-unavailable", "parallel-updates", "reauthentication-flow", "test-coverage",
    # Gold
    "devices", "diagnostics", "discovery", "discovery-update-info", "docs-data-update",
    "docs-examples", "docs-known-limitations", "docs-supported-devices",
    "docs-supported-functions", "docs-troubleshooting", "docs-use-cases",
    "dynamic-devices", "entity-category", "entity-device-class",
    "entity-disabled-by-default", "entity-translations", "exception-translations",
    "icon-translations", "reconfiguration-flow", "repair-issues", "stale-devices",
    # Platinum
    "async-dependency", "inject-websession", "strict-typing",
}


def _rules() -> dict[str, Any]:
    return yaml.safe_load((INTEGRATION / "quality_scale.yaml").read_text())["rules"]


def test_the_self_assessment_covers_every_rule_and_invents_none() -> None:
    assert set(_rules()) == QUALITY_SCALE_RULES


def test_no_rule_is_still_marked_todo() -> None:
    """The file claims platinum; a `todo` in it means the claim is out of date."""
    todo = [
        rule
        for rule, status in _rules().items()
        if (status if isinstance(status, str) else status["status"]) == "todo"
    ]
    assert todo == []


def test_every_exemption_says_why() -> None:
    """An exemption without a reason is indistinguishable from skipping the rule."""
    thin = [
        rule
        for rule, status in _rules().items()
        if isinstance(status, dict)
        and status["status"] == "exempt"
        and len(status.get("comment", "")) < 20
    ]
    assert thin == []


# --- the examples, which the setup docs link as ready to copy -----------------
EXAMPLE_FILES = sorted((REPO / "examples").rglob("*.yaml"))


def test_there_are_examples_to_check() -> None:
    assert EXAMPLE_FILES, "the docs link this directory as ready-to-copy"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_every_example_is_valid_yaml(path: Path) -> None:
    """They are advertised as copy-and-paste, so they have to at least parse."""
    assert yaml.safe_load(path.read_text(encoding="utf-8"))


AUTOMATION_FILES = [p for p in EXAMPLE_FILES if p.name == "automations.yaml"]


@pytest.mark.parametrize("path", AUTOMATION_FILES, ids=lambda p: p.name)
def test_every_example_automation_has_a_trigger_and_an_action(path: Path) -> None:
    """A file that loses its leading `-` stays valid YAML and stops being a list.

    Skipping non-lists would let that through, so an automations file is required
    to load as one rather than merely checked when it happens to be.
    """
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, list), f"{path.name} should be a list of automations"
    for automation in loaded:
        assert automation.get("triggers"), f"{path.name}: {automation.get('alias')}"
        assert automation.get("actions"), f"{path.name}: {automation.get('alias')}"
