"""Least-privilege invariants for release workflows that handle repository or signing secrets."""

from __future__ import annotations

import json
import re
import subprocess
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


def _is_soft(step: dict[str, Any]) -> bool:
    """Whether a step's failure is swallowed.

    Anything but an absent or literally-false setting counts: `continue-on-error: ${{ true }}` is a
    valid spelling that reaches PyYAML as a string, so an identity test against True reads a swallowed
    step as fail-hard.
    """
    setting = step.get("continue-on-error")
    if setting is None or setting is False:
        return False
    # `${{ false }}` is a valid spelling that evaluates to false. Reading every expression as soft
    # would reject a fail-hard step rather than catch a swallowed one.
    return str(setting).replace(" ", "") not in {"${{false}}", "false", "False"}


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

    # The other half of the same decision: STRICT turns a stop into a non-zero exit, which is what the
    # manual dispatch wants and what this path must never have. Swallowing already covers it today,
    # but the two guards protect against opposite edits — someone removing the swallow here, or
    # someone copying the manual step's env wholesale.
    steps_env = next(s.get("env", {}) for s in steps if isinstance(s, dict) and "run" in s)
    assert "STRICT" not in steps_env, (
        f"the post-release sweep opts into reddening a published release: {steps_env.get('STRICT')!r}"
    )


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

    What that buys is precise because the step also sets `STRICT: "true"`. Every way the sweep can fail
    to do its job then reddens the job: stopping early on a partial picture, leaving residue behind a
    delete it could not verify, or keeping a candidate because a package index would not answer.
    publish.yml leaves STRICT unset and swallows the exit instead, for the reason above. Green here
    certifies only that the sweep ran to completion, never that any particular rc was removed.

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
        "STRICT": "true",
    }, f"the sweep's environment is not its four tokens, DRY_RUN and STRICT: {sweep['env']!r}"

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


def test_every_release_gate_runs_the_release_script_suite() -> None:
    """The release scripts are shell, so the Python gate above says nothing about them.

    ci.yml runs `tests/release/*.sh` on every push, which proves them on a branch. It does not prove
    them on the commit being tagged, and the release workflows are exactly where that matters: the rc
    sweep deletes across three registries, and the release helpers are what publish. A gate that
    stops at pytest would tag a commit whose shell half was last checked somewhere else.
    """
    for name in ("release.yml", "prerelease.yml"):
        document = yaml.safe_load((_ROOT / ".forgejo" / "workflows" / name).read_text())
        # The `gate` job specifically, and the command itself rather than a mention of the path. A
        # substring search over every job would be satisfied by this very comment, by an `echo`, or by
        # the loop running in the tag job after the tag it was supposed to qualify already exists.
        steps = [s for s in (document["jobs"]["gate"].get("steps") or []) if isinstance(s, dict)]
        running = [
            s
            for s in steps
            if any(
                line.strip() == 'for t in tests/release/*.sh; do bash "$t"; done'
                for line in str(s.get("run", "")).splitlines()
            )
        ]
        assert len(running) == 1, f"{name}'s gate does not run the release suite exactly once"

        # And the step has to be able to fail the gate. Pinning the command alone would accept one
        # carrying `if: false` or `continue-on-error`, which reaches the same place as not running it.
        step = running[0]
        assert "if" not in step, f"{name}'s release suite can be skipped: {step.get('if')!r}"
        swallowed = step.get("continue-on-error")
        assert swallowed is None or swallowed is False, (
            f"{name}'s release suite cannot fail the gate: {swallowed!r}"
        )

        # And the shell has to carry the failure out of the loop. Without errexit a script failing on
        # any iteration but the last is overwritten by the ones after it, and the step exits 0 having
        # run a suite that did not pass. Errexit is required as the block's first COMMAND rather than
        # found by substring, which a comment or an `echo` would satisfy just as well.
        body = [line for line in str(step["run"]).splitlines() if line.strip()]
        first = next(line.strip() for line in body if not line.strip().startswith("#"))
        assert first == "set -euo pipefail", (
            f"{name}'s release gate does not begin with errexit: {first!r}"
        )
        relaxed = [
            line.strip()
            for line in body
            if not line.strip().startswith("#")
            and (line.strip().startswith("set +") or "set +o" in line)
        ]
        assert not relaxed, f"{name}'s release gate turns a shell guard back off: {relaxed}"


def test_both_release_jobs_promote_the_changelog_through_the_shared_script() -> None:
    """The gate qualifies a release diff and the tag job reproduces it byte for byte.

    Two copies of the promotion logic satisfy that only while they stay identical, and an inline awk
    rule has no fail-closed check: if it matches nothing the CHANGELOG is published unpromoted, and
    the byte-compare still passes because BOTH jobs produced the same wrong bytes. The shared script
    refuses that, and refuses a merge that left two `[Unreleased]` headings.
    """
    document = yaml.safe_load((_ROOT / ".forgejo" / "workflows" / "release.yml").read_text())
    jobs = document["jobs"]

    for name in ("gate", "tag"):
        # Uncommented command lines, not a substring of the whole block: a path mentioned in a comment
        # or echoed rather than run would satisfy a substring search while promoting nothing.
        commands = [
            line.strip()
            for step in (jobs[name].get("steps") or [])
            if isinstance(step, dict)
            for line in str(step.get("run", "")).splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert any(c.startswith("bash packaging/promote-changelog.sh ") for c in commands), (
            f"the {name} job does not execute the shared promoter"
        )
        # The awk that WRITES the heading, not any mention of it: both jobs legitimately grep for
        # `## [Unreleased]` as a precondition, and that guard is not a second promotion.
        assert not any('print "## [Unreleased]"' in c for c in commands), (
            f"the {name} job still carries an inline promotion, which cannot fail closed"
        )


def test_no_job_pip_installs_into_whatever_interpreter_it_finds() -> None:
    """A job that runs `pip install` has to set up its own Python first.

    Runner images mark their system interpreter externally managed (PEP 668), so pip refuses to
    install into it and the job dies on `error: externally-managed-environment`. Nothing in the
    workflow says which Python a step gets, so this is invisible until the image changes underneath
    a job that had worked for months — and on the publish path that lands mid-release, after the
    version is tagged and PyPI already has the upload.
    """
    # BOTH forges. The GitHub half builds and publishes the macOS and arm64 assets, so the same
    # externally-managed interpreter can stop a release there just as easily.
    workflows = list(_FORGEJO) + sorted(
        list((_ROOT / ".github" / "workflows").glob("*.yml"))
        + list((_ROOT / ".github" / "workflows").glob("*.yaml"))
    )
    assert workflows, "no workflows found to check"
    for path in workflows:
        document = yaml.safe_load(path.read_text())
        for name, job in (document.get("jobs") or {}).items():
            steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
            def installs_with_pip(step: dict[str, Any]) -> bool:
                """`pip install` in any of its spellings.

                pip3, `python -m pip`, flags between the two words, and backslash continuations all
                carry the same PEP 668 risk, so matching the bare phrase would skip them.
                """
                body = "\n".join(
                    line.split(" #", 1)[0]
                    for line in str(step.get("run", "")).splitlines()
                    if not line.strip().startswith("#")
                )
                while "\\\n" in body:
                    body = body.replace("\\\n", " ")
                # Bounded to one shell command: `install` after a `;`, `&&`, `||` or a comment is a
                # different program, and demanding a Python for it would be a false alarm.
                return bool(re.search(r"\bpip3?\b[^;&|#\n]*\binstall\b", body))

            first_pip = next(
                (i for i, step in enumerate(steps) if installs_with_pip(step)),
                None,
            )
            if first_pip is None:
                continue
            # EARLIER than the pip, and able to fail the job. A setup that runs afterwards, or whose
            # failure is swallowed, leaves the pip on the system interpreter anyway.
            #
            # Two shapes qualify. A plain unconditional setup, or the retry pair used across these
            # workflows: a `continue-on-error` attempt followed by one gated on THAT attempt's
            # outcome. The second shape is only fail-closed while the gate really references the
            # first attempt — an unrelated or never-true condition skips the retry and leaves the
            # swallowed failure as the whole story.
            def sets_up_python(step: dict[str, Any]) -> bool:
                """An actions/setup-python that actually installs a chosen interpreter.

                Without a version it may leave whatever the image already had on PATH, which is the
                externally-managed one this guard exists to avoid.
                """
                # The action itself, not a name containing it: a wrapper called setup-python-cache
                # can carry a python-version input and install no interpreter at all.
                if not str(step.get("uses", "")).startswith("actions/setup-python@"):
                    return False
                given = step.get("with") or {}
                return bool(given.get("python-version") or given.get("python-version-file"))

            soft_ids = {
                str(step.get("id"))
                for step in steps[:first_pip]
                if sets_up_python(step) and _is_soft(step) and step.get("id")
            }
            protected = False
            for step in steps[:first_pip]:
                if not sets_up_python(step):
                    continue
                if _is_soft(step):
                    continue
                condition = str(step.get("if", ""))
                if not condition:
                    protected = True
                    break
                # The exact fail-closed spelling the workflows document. `== 'success'` names the
                # same outcome and skips the retry precisely when it is needed, and `== 'failure'`
                # skips it whenever a runner leaves the outcome unset.
                normalized = condition.replace('"', "'").replace(" ", "")
                if any(normalized == f"steps.{i}.outcome!='success'" for i in soft_ids):
                    protected = True
                    break
            # The pip step must not outlive a failed setup either. Only the conditions that SURVIVE
            # a failure are rejected: `success()`, or a check that the setup itself succeeded, keeps
            # the guarantee, and rejecting every condition would fail safe edits.
            pip_condition = str(steps[first_pip].get("if", "")).replace(" ", "")
            survives_failure = any(
                token in pip_condition for token in ("always()", "failure()", "cancelled()")
            )
            assert not survives_failure, (
                f"{path.name}::{name} runs its pip step under {pip_condition!r}, which executes even "
                f"when the setup-python meant to guarantee the interpreter has failed"
            )
            assert protected, (
                f"{path.name}::{name} pip-installs with no setup-python that can fail the job: a "
                f"swallowed attempt and a retry gated on something other than its outcome both "
                f"leave the system interpreter in place"
            )



def test_every_compatibility_floor_is_clamped_against_renovate() -> None:
    """A floor leg exists to prove the OLDEST supported release still works.

    Renovate cannot tell a floor from a current-release alias. Unclamped, it bumps the tag and the leg
    becomes a second current test: it passes, it proves nothing it was written to prove, and nothing
    goes red to say so. The clamp is what keeps the leg old; the digest still refreshes, so the image
    stays patched.

    Keyed on the depName, because that is what a clamp matches. Any annotation whose name says floor
    or compat has to be answered by a rule that actually restricts it — an `allowedVersions`, a
    disabled manager, or a matchUpdateTypes narrowing.
    """
    # TRACKED files only. An rglob also reads .venv, build outputs and research scratch, so a stray
    # annotation in ignored local content could fail this for one machine and nobody else. Scanning
    # every tracked file rather than a suffix list also catches packaging/release-pins.env, which the
    # custom managers read and a suffix filter would miss.
    tracked = subprocess.run(
        ["git", "-C", str(_ROOT), "ls-files", "-z"],
        capture_output=True, check=True,
    ).stdout.decode().split("\0")
    annotated: set[str] = set()
    for name in tracked:
        if not name:
            continue
        path = _ROOT / name
        try:
            text = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for match in re.finditer(r"renovate:.*?depName=([A-Za-z0-9._/-]+)", text):
            annotated.add(match.group(1))

    config = json.loads((_ROOT / ".renovaterc.json").read_text())
    clamped = {
        name
        for rule in config.get("packageRules", [])
        for name in (rule.get("matchDepNames") or [])
        if rule.get("allowedVersions") or rule.get("enabled") is False or rule.get("matchUpdateTypes")
    }

    floors = {dep for dep in annotated if "floor" in dep or "compat" in dep}
    assert floors, "no compatibility floors found; this test is watching nothing"
    unclamped = sorted(floors - clamped)
    assert not unclamped, (
        f"these floors would drift to current on the next Renovate run: {unclamped}"
    )
