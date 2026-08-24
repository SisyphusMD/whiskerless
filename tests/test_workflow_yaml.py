"""Workflow YAML that a forge will actually accept."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
# Both spellings, in both directories: a forge accepts `.yaml` too, and one that escaped this glob
# would be exempt from the parse while still running. The non-empty guard below cannot notice a
# single missing file, so the glob has to be the thing that is right.
WORKFLOWS = sorted(
    path
    for directory in (REPO / ".github" / "workflows", REPO / ".forgejo" / "workflows")
    for pattern in ("*.yml", "*.yaml")
    for path in directory.glob(pattern)
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


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_a_branch_push_and_pull_request_workflow_runs_once_per_commit(path: Path) -> None:
    """A workflow on both branch `push` and `pull_request` fires TWICE for one commit.

    Same-repo PR branches raise both events, so every job runs twice on identical code —
    on macOS, the scarcest runners there are. The push run is the one that counts: the
    release gate queries `event=push` for an exact SHA and deliberately ignores
    pull_request runs, so the duplicate decides nothing.

    Dropping the `pull_request` trigger is the wrong fix. A fork's PR never raises `push`
    in this repository, so that trigger is a fork's ONLY coverage here. What the job needs
    is a condition that keeps fork PRs and skips same-repo ones, which is a property of
    the `if`, not of the triggers.

    The skipped run is not a perfect duplicate — `pull_request` builds the synthetic merge
    of head into base — so this trades pre-merge macOS coverage of that merge for half the
    macOS runners. The merged commit is still tested when it reaches a branch the push
    filter matches.
    """
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicates)
    triggers = document.get("on") or document.get(True) or {}
    if not isinstance(triggers, dict) or "pull_request" not in triggers:
        return
    push = triggers.get("push")
    # A tag-only push never coincides with a pull_request, so it cannot double anything.
    if not isinstance(push, dict) or "branches" not in push:
        return
    branches = push["branches"]
    if isinstance(branches, str):
        branches = [branches]
    # Only a pattern that can match a PR's HEAD branch doubles the run. `branches: [main]`
    # cannot: a pull request raises `push` for nothing, because its head is never main.
    if not any("*" in str(pattern) for pattern in branches):
        return

    unguarded = []
    for job, spec in (document.get("jobs") or {}).items():
        condition = " ".join(str((spec or {}).get("if", "")).split())
        distinguishes_forks = (
            "pull_request.head.repo.full_name" in condition and "github.repository" in condition
        )
        if not distinguishes_forks:
            unguarded.append(job)
    assert not unguarded, (
        f"{path.name} runs on branch push AND pull_request, so these jobs run twice for every "
        f"same-repo PR commit: {sorted(unguarded)}. Gate them on "
        "github.event.pull_request.head.repo.full_name != github.repository."
    )
