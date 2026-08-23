"""Least-privilege invariants for release workflows that handle repository or signing secrets."""

from __future__ import annotations

import re
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


def test_the_prune_job_never_runs_on_a_prerelease_tag() -> None:
    """The rc sweep is the only irreversible release operation, and it publishes through the same
    workflow the rc itself does.

    Gating it on `-rc.` reads as correct and is not: it excludes exactly one prerelease spelling, so
    any other (`-beta.1`, `-alpha`) is treated as a stable and authorizes a sweep that deletes real
    releases, tags and packages. Every prerelease tag is hyphenated and no stable one is, so the
    hyphen is the honest test.

    Ordering is asserted too. The sweep must not start until the tap has re-pointed the rc formula at
    the stable, or the rc brew channel resolves to a release that has just been deleted. That
    dependency travels through `homebrew-bottles` today, which means an edit to the bottles job could
    drop it with nothing to say so.
    """
    document = yaml.safe_load((_ROOT / ".forgejo" / "workflows" / "publish.yml").read_text())
    prune = document["jobs"]["prune-rcs"]

    condition = str(prune["if"])
    assert "'-'" in condition, f"prune is not gated on the hyphen every prerelease tag carries: {condition}"
    assert "'-rc.'" not in condition, (
        f"prune is gated on one prerelease spelling, so every other one prunes: {condition}"
    )

    needs = prune["needs"]
    for required in ("homebrew-tap", "reconcile", "registry", "nas-bridge"):
        assert required in needs, f"prune does not wait for {required}: {needs}"


def test_the_prune_sweep_cannot_fail_an_already_published_release() -> None:
    """By the time the sweep runs the stable is published on all three registries.

    A non-zero exit here would redden a release that fully succeeded, and send somebody looking for a
    publishing failure that did not happen. The sweep reports its own problems and exits 0; the guard
    at the call site is what holds when it ever does not.
    """
    document = yaml.safe_load((_ROOT / ".forgejo" / "workflows" / "publish.yml").read_text())
    steps = document["jobs"]["prune-rcs"]["steps"]
    run = next(str(s["run"]) for s in steps if isinstance(s, dict) and "run" in s)
    assert "prune-rcs.sh" in run
    assert "::warning::" in run, f"a failing prune would fail the release: {run}"


def test_the_manual_prune_dispatch_cannot_delete_by_accident_or_report_a_failure_as_success() -> None:
    """The manual sweep is the one place a human aims a registry-wide delete at all three registries.

    Nothing upstream constrains it. The automatic sweep in publish.yml is gated on a stable tag shape
    and waits on six publishing jobs; this one starts the moment somebody clicks Run.

    So the shape is allowlisted whole, at every level, rather than probed for known-bad fields.
    Enumerating what must be ABSENT cannot be finished — `container`, `defaults`, `env`, `if`,
    `shell`, `continue-on-error`, `permissions` and `strategy` each reach the sweep by a different
    route — while enumerating what may be PRESENT can. Probing for the first matching step would
    likewise pass a workflow carrying a second checkout of the dispatch ref beside a compliant one.

    `ref: main` keeps the reviewed deletion guards in force when the dispatch came from a stale or
    feature branch, and the checkout's inputs are pinned whole because `ref` alone says nothing about
    WHOSE main: a `repository:` beside it hands four write tokens to another repo's copy of the
    script. The action itself is pinned to a full commit for the same reason.

    `dry_run` must DEFAULT to true and reach the step untouched. A wrong default, a hardcoded
    `DRY_RUN: false`, or a `${{ !inputs.dry_run }}` binding that still names the input, all delete
    real releases on a dispatch that accepted every default. A redundant preview costs ten seconds.

    A failure must reach the job. publish.yml deliberately swallows one, which makes this read like an
    oversight worth tidying away. It is not: there a nonzero exit would redden a release that had
    already fully succeeded, while here nothing is being released.

    Be precise about what that buys, because annotation severity and exit status are not the same
    thing here. The script exits nonzero at only a few points: it cannot enumerate the package
    registry, it cannot list a version's package files, or a transport error interrupts reading a
    stable. Every other trouble — including a failed package DELETE that logs `::error::` — is
    recorded as residue for a later sweep to retry and reaches an unconditional `exit 0`. Green
    therefore still does not mean "swept clean", and the warnings remain the real report; not
    swallowing is what makes those few fatal paths reach the maintainer at all.

    One limit this cannot reach at all: `workflow_dispatch` runs the definition belonging to the ref
    it was dispatched from, and only then does the pinned checkout replace the tree. Everything above
    therefore binds main's copy of the workflow; an older ref runs its own copy, guards and all.
    """
    document = yaml.safe_load((_ROOT / ".forgejo" / "workflows" / "prune-rcs.yml").read_text())

    # `True` is the `on:` key, which PyYAML resolves to a boolean.
    assert set(document) == {"name", True, "jobs"}, (
        f"unexpected workflow-level keys: {sorted(str(k) for k in document)}"
    )

    jobs = document["jobs"]
    assert len(jobs) == 1, f"the sweep grew a second job this test does not reach: {sorted(jobs)}"
    job = next(iter(jobs.values()))
    assert set(job) == {"name", "runs-on", "steps"}, f"unexpected job keys: {sorted(job)}"
    # The value too: a key-set check passes `runs-on: ${{ inputs.runner }}`, which would hand four
    # write tokens to whatever runner the dispatcher named.
    assert job["runs-on"] == "ubuntu-latest", f"the sweep's runner is not pinned: {job['runs-on']!r}"

    steps = job["steps"]
    assert len(steps) == 2, f"the sweep job is no longer checkout-then-prune: {len(steps)} steps"
    checkout, sweep = steps
    assert set(checkout) == {"uses", "with"}, f"unexpected checkout keys: {sorted(checkout)}"
    assert set(sweep) == {"name", "env", "run"}, f"unexpected sweep keys: {sorted(sweep)}"

    triggers = _triggers(document)
    assert set(triggers) == {"workflow_dispatch"}, (
        f"the sweep answers to something other than a manual dispatch: {sorted(triggers)}"
    )

    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", str(checkout["uses"])), (
        f"the checkout is not actions/checkout pinned to a full commit: {checkout['uses']!r}"
    )
    assert checkout["with"] == {"ref": "main"}, (
        f"the checkout takes inputs beyond a main pin: {checkout['with']!r}"
    )

    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"dry_run"}, f"the dispatch takes inputs beyond dry_run: {sorted(inputs)}"

    dry_run = inputs["dry_run"]
    assert dry_run["default"] is True, (
        f"a dispatch that leaves dry_run alone would delete: {dry_run['default']!r}"
    )

    # Values, not just key names: a CLUSTER_TOKEN bound to the NAS PAT keeps this mapping's shape
    # while sending a credential to the wrong host, and the read failure that follows is one the
    # script survives, so the dispatch would finish having pruned nothing.
    assert {k: str(v).replace(" ", "") for k, v in sweep["env"].items()} == {
        "CLUSTER_TOKEN": "${{secrets.CLUSTER_FORGEJO_REPO_WRITE_PAT}}",
        "NAS_TOKEN": "${{secrets.NAS_FORGEJO_REPO_WRITE_PAT}}",
        "GH_TOKEN": "${{secrets.GH_REPO_WRITE_PAT}}",
        "PACKAGE_TOKEN": "${{secrets.CLUSTER_FORGEJO_REGISTRY_PUSH_PAT}}",
        "DRY_RUN": "${{inputs.dry_run}}",
    }, f"the sweep's environment is not its four tokens plus DRY_RUN: {sweep['env']!r}"

    # The command is pinned rather than screened, because `||`, `; true`, `if ! cmd; then ... fi`, a
    # pipeline and `set +e` all turn a failed sweep green. Changing it on purpose means changing this
    # line on purpose.
    command = " ".join(
        line.strip()
        for line in str(sweep["run"]).splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    assert command == "bash packaging/prune-rcs.sh", (
        f"the sweep is no longer a bare invocation, so a failure need not reach the job: {command!r}"
    )
