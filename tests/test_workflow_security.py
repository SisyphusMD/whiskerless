"""Least-privilege invariants for release workflows that handle repository or signing secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_MACOS = _ROOT / ".github" / "workflows" / "release-macos.yml"
# Both spellings: a forge accepts `.yaml` too, and a workflow that escaped this glob would be
# exempt from every check below while still running.
_FORGEJO = tuple(
    sorted((_ROOT / ".forgejo" / "workflows").glob("*.yml"))
    + sorted((_ROOT / ".forgejo" / "workflows").glob("*.yaml"))
)

_SIGNING_STEP = "Sign, package, notarize, staple"

_CERT_SECRETS = {
    "MACOS_APP_CERT_P12",
    "MACOS_INSTALLER_CERT_P12",
    "MACOS_CERT_PASSWORD",
}
_SIGN_SECRETS = {
    "MACOS_APP_IDENTITY",
    "MACOS_INSTALLER_IDENTITY",
    "MACOS_NOTARY_KEY_P8",
    "MACOS_NOTARY_KEY_ID",
    "MACOS_NOTARY_ISSUER",
}


def _step(text: str, name: str) -> str:
    """One step's text, ending where the next step begins.

    Bounded deliberately: a slice that ran to end-of-file would let a later, unrelated step satisfy
    an assertion about this one.
    """
    marker = f"      - name: {name}\n"
    start = text.index(marker)
    end = text.find("\n      - ", start + len(marker))
    return text[start:] if end < 0 else text[start:end]


def _triggers(document: dict[str, Any]) -> dict[str, Any]:
    """A workflow's `on:` block. PyYAML resolves the bare key `on` to the boolean True."""
    return document.get(True, document.get("on"))  # type: ignore[return-value]


def _conditions(document: dict[str, Any]) -> list[str]:
    """Every `if:` expression in a workflow, at job and step level.

    Values, not lines: `if: >-` folds a condition across several lines, and a line-wise scan reads
    only the first of them.
    """
    found: list[str] = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        if "if" in job:
            found.append(str(job["if"]))
        found.extend(
            str(step["if"])
            for step in job.get("steps") or []
            if isinstance(step, dict) and "if" in step
        )
    return found


def _gate_lines() -> list[str]:
    return [
        line
        for workflow in _FORGEJO
        for line in workflow.read_text().splitlines()
        if "check-mirror-ci.sh" in line and not line.lstrip().startswith("#")
    ]


def test_apple_secrets_exist_only_on_the_two_steps_that_consume_them() -> None:
    text = _MACOS.read_text()
    build = text[text.index("  build:\n"):text.index("\n  publish:\n")]
    assert "\n    env:\n" not in build

    imports = _step(text, "Import signing certificates")
    signing = _step(text, _SIGNING_STEP)
    for secret in _CERT_SECRETS:
        assert f"${{{{ secrets.{secret} }}}}" in imports
        assert text.count(f"secrets.{secret}") == 1
    for secret in _SIGN_SECRETS:
        assert f"${{{{ secrets.{secret} }}}}" in signing
        assert text.count(f"secrets.{secret}") == 1


def test_temporary_apple_credentials_are_removed_by_the_consuming_steps() -> None:
    """On a trap, not as a trailing command.

    These steps run under `set -e`, so a removal written as the last line is exactly the one that
    does not happen when signing or notarization fails — leaving a private key and two
    certificates on the runner in the case somebody then re-runs and inspects.
    """
    text = _MACOS.read_text()
    assert "trap 'rm -f app.p12 installer.p12' EXIT" in _step(text, "Import signing certificates")
    assert "trap 'rm -f notary.p8' EXIT" in _step(text, _SIGNING_STEP)


def test_forgejo_workflows_do_not_use_unsupported_permissions_field() -> None:
    """Forgejo warns and ignores `permissions:`, so relying on one there is a silent no-op.

    Parsed rather than grepped: the substring appears in comments and in shell that mentions it,
    and a real key written `permissions :` is missed.
    """
    for workflow in _FORGEJO:
        document = yaml.safe_load(workflow.read_text())
        assert "permissions" not in document, workflow
        for name, job in (document.get("jobs") or {}).items():
            assert isinstance(job, dict) and "permissions" not in job, f"{workflow.name}:{name}"


def test_github_token_defaults_read_only_and_only_macos_publish_can_write() -> None:
    """Every scope, not just `contents`.

    A grep for the literal `contents: write` stays green while a job quietly takes `write-all` or
    `issues: write`, which is the same failure with a different word.
    """
    document = yaml.safe_load(_MACOS.read_text())
    assert document["permissions"] == {"contents": "read"}

    for name, job in document["jobs"].items():
        permissions = job.get("permissions")
        if permissions is None:
            continue
        assert name == "publish", f"{name} widens the token beyond the read-only default"
        assert permissions == {"contents": "write"}, f"{name}: {permissions}"


def test_mirror_gated_workflows_are_safe_to_gate_on() -> None:
    """A workflow a release gate reads has to answer for one commit, the same way, every time.

    The gate takes the first SUCCESSFUL run for a commit, whichever branch pushed it. That is only
    sound while a gated workflow does identical work on every branch: then two runs for one commit
    differ solely by scheduling or infrastructure, and a green one is evidence the commit builds.
    Add a branch condition and it stops being true — a run that skipped the real work on a topic
    branch would stand in for the branch the release is cut from. Enforced here rather than
    remembered, because the gate cannot see the difference.
    """
    lines = _gate_lines()
    assert lines, "no mirror-gated workflows found"
    # Every call site has to name its workflow file inline. One that wrapped onto the next line, or
    # passed the path through a variable, would be gated on without any check below seeing it.
    named = [line for line in lines if ".github/workflows/" in line]
    assert named == lines, "a check-mirror-ci.sh call site does not name its workflow file inline"
    gated = {line.split(".github/workflows/")[1].split()[0].strip('"') for line in named}

    for name in sorted(gated):
        path = _ROOT / ".github" / "workflows" / name
        assert path.is_file(), f"{name} is gated on but does not exist"
        document = yaml.safe_load(path.read_text())

        on = _triggers(document)
        assert on["push"]["branches"] == ["**"], f"{name} only runs on some branches: {on['push']}"

        # Keyed per COMMIT, and never cancelled. The gate reads this workflow's verdict for one
        # exact SHA, so a ref-keyed group with cancel-in-progress lets a push during a release cut
        # cancel the very run being waited on — leaving that commit with a cancelled-only run set,
        # no verdict, and no way for the gate to read it as anything but not-green. Permanently,
        # for a commit that never failed a test.
        concurrency = document["concurrency"]
        assert "github.sha" in concurrency["group"], \
            f"{name} is gated on but its concurrency group is not per-commit: {concurrency}"
        assert concurrency.get("cancel-in-progress") is False, \
            f"{name} is gated on but cancels its own runs: {concurrency}"

        for condition in _conditions(document):
            assert "github.ref" not in condition and "head_branch" not in condition, \
                f"{name} gates work on the branch: {condition}"
        # Branch logic inside a script skips the work just as effectively as a step-level `if`.
        for job in document["jobs"].values():
            for step in job.get("steps") or []:
                run = step.get("run", "") if isinstance(step, dict) else ""
                assert "github.ref" not in run, f"{name} branches on the ref inside a run block"


def test_the_prerelease_tag_push_never_trusts_a_branch_supplied_destination() -> None:
    """prerelease.yml is dispatchable from any branch, and this step holds the repo-write PAT.

    The steps before it run that branch's own next-version.sh and stamp-version.py, so `origin` is
    a value branch-supplied code had the chance to repoint — pushing there would hand the
    credential to whatever host it names. The destination is built from runner-provided variables
    instead, and the PAT travels in a header because git echoes a remote URL into the job log.
    """
    text = (_ROOT / ".forgejo" / "workflows" / "prerelease.yml").read_text()
    step = _step(text, "Push the prerelease tag")

    assert "push origin" not in step
    assert 'push "${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}.git" "$TAG"' in step
    assert "http.extraheader=Authorization: Basic" in step
    assert "x-access-token:${TOKEN}@" not in step
    # The same three checks the shared helper makes for the stable release.
    assert '[ "$(git cat-file -t "refs/tags/$TAG")" = tag ]' in step
    assert '[ "$(git rev-parse "$TAG^{commit}")" = "$(git rev-parse HEAD)" ]' in step
    assert 'test -z "$(git status --porcelain)"' in step
