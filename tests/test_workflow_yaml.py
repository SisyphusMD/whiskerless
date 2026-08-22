"""Workflow YAML that a forge will actually accept."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml")) + sorted(
    (REPO / ".forgejo" / "workflows").glob("*.yml")
)


class _NoDuplicates(yaml.SafeLoader):
    """A loader that refuses duplicate mapping keys.

    `yaml.safe_load` accepts them silently and keeps the last — which is how a
    workflow with two `name:` keys passed a local "is this valid YAML" check and
    would have been rejected by GitHub, leaving the release gate polling a run
    that never existed.
    """


def _no_duplicate_keys(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise AssertionError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_NoDuplicates.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _no_duplicate_keys,
)


def test_there_are_workflows_to_check() -> None:
    assert WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_workflow_parses_without_duplicate_keys(path: Path) -> None:
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicates)
    assert isinstance(loaded, dict) and loaded.get("jobs"), f"{path.name} declares no jobs"
