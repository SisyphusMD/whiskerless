"""Repository-wide invariants that no other check enforces.

Each of these found a real defect during the work that added them, and each was
only ever verified by someone remembering to look. They are cheap, they need
neither Home Assistant nor a broker, and they fail on the file that drifted.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
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


# --- nothing personal ever ships ------------------------------------------------
# The owner's real robot serials were committed for a week in August 2026 and took
# a full `git filter-repo` rewrite to remove — one that could not reach the PyPI
# sdists that had already carried them, because PyPI has no delete API. Then a test
# written AFTER that rewrite put a real serial straight back, and it reached a
# published release candidate before a collaborator spotted it by hand.
#
# So this is not a style rule. A serial is the MQTT client-id and both topic
# segments; an SSID names somebody's house. Neither is recoverable once it is on
# PyPI, and the only reliable reviewer is one that runs on every commit.
#
# Deliberately an ALLOWLIST, never a denylist of the real values: a test naming
# what must not leak would be the leak.
EXAMPLE_SERIALS = frozenset(
    {
        "LR3C000001", "LR3C123456", "LR4C000000", "LR4C000001",
        "LR4C111111", "LR4C123456", "LR4C222222", "LR4C654321", "LR4C999999",
        # A model letter this project has never seen, used to prove the scrubber redacts the whole
        # `LR3/LR4<letter>` shape provisioning accepts and not just the LR4C it happens to know.
        "LR4D123456",
    }
)
#: Every network name the repository is allowed to use as an example.
EXAMPLE_NETWORKS = frozenset(
    {
        "", "MyIoT", "HomeNet", "Guest", "IoT", "home", "hidden",
        # Punctuation on purpose: an SSID may contain any octet, and this one proves the scrubber
        # does not stop at a comma and publish the rest of somebody's network name.
        "My,Home",
        "Near", "Far", "Cafe", "Seen", "x",
        r"Guest\x1b[31m\nEvil",  # the control-character escaping fixture
    }
)

# Deliberately wider than the two units this project has seen. `provision`
# accepts any LR4-prefixed serial on purpose, so pinning the guard to the `C`
# designator would wave through a real `LR4D…` from somebody else's robot — and
# the whole point is to catch the serial nobody thought to look for.
_SERIAL = re.compile(r"\bLR[0-9][A-Z]?[0-9]{6}\b", re.IGNORECASE)
#: Every syntactic form an SSID is written in here — `wifi_ssid=`, `ssid=`,
#: `"ssid":` and the CLI flag. Free prose is not checkable; these are.
#: A QUOTED value in every case, including after the flag: unquoted prose such as
#: "--wifi-ssid skips the chooser" is not an SSID, and a guard that cries wolf is
#: a guard somebody deletes.
_SSID = re.compile(
    r"""(?:wifi[_-]?ssid|ssid)["']?\s*[:=]\s*["']([^"']*)["']|--wifi-ssid[= ]["']([^"']+)["']"""
)


def _tracked_text() -> list[tuple[Path, str]]:
    """Every tracked file git considers text, with its contents.

    Tracked rather than walked: the working tree also holds virtualenvs, caches
    and scratch files, and none of those are what gets published.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    )
    found = []
    for name in listed.stdout.split("\0"):
        path = REPO / name
        if not name or not path.is_file():
            continue
        try:
            found.append((path, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue  # a binary asset cannot carry a serial in a form that matters
    return found


TRACKED = _tracked_text()


def test_no_real_robot_serial_is_committed() -> None:
    """Every serial-shaped token in the tree is one of the invented examples."""
    strays = {
        f"{path.relative_to(REPO)}: {found}"
        for path, text in TRACKED
        for found in _SERIAL.findall(text)
        if found.upper() not in EXAMPLE_SERIALS
    }
    assert not strays, (
        "a serial that is not a documented example is in the tree — if it is real, it "
        f"must not be committed; if it is a new example, add it to EXAMPLE_SERIALS: {sorted(strays)}"
    )


def test_no_real_network_name_is_committed() -> None:
    """Same rule for SSIDs, wherever one is syntactically identifiable.

    Only where the code or a fixture *names* the field — free prose is not
    mechanically checkable, and pretending otherwise would be a guard that
    quietly covers less than it claims.
    """
    strays = {
        f"{path.relative_to(REPO)}: {found}"
        for path, text in TRACKED
        for match in _SSID.findall(text)
        for found in (next((g for g in match if g), ""),)
        if found not in EXAMPLE_NETWORKS and not found.startswith(("<", "{", "%", "$"))
    }
    assert not strays, (
        "a network name that is not a documented example is in the tree — add it to "
        f"EXAMPLE_NETWORKS if it is invented: {sorted(strays)}"
    )


def test_the_readme_network_picker_uses_only_example_names() -> None:
    """The README is PyPI's long description, so it lands in every wheel's
    METADATA — the one place a stray name is published even when the sdist is
    not. Its scan-output block is prose to every other check here."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    # Anchored on the channel column, so the menu of numbered *choices* higher up
    # the transcript ("1  Generate one for me") is not read as a network name.
    picker = re.compile(r"^\s{4}\d\s{2}(\S+)\s.*\bch \d+\s*$", re.MULTILINE)
    names = set(picker.findall(readme))
    assert names, "the provisioning transcript's network picker is no longer recognisable"
    assert names <= EXAMPLE_NETWORKS, f"not example names: {sorted(names - EXAMPLE_NETWORKS)}"


# --- the two Homebrew formulae must not drift ------------------------------------
# `whiskerless.rb` and `whiskerless-rc.rb` differ only in name, description and
# which one they conflict with. Everything that decides whether `brew install`
# WORKS — the dependency list, the resource closure, the install body — has to be
# identical, because only one of them is ever exercised by any given CI run.
#
# Both halves of this have already shipped broken: the resource closure went stale
# in both when cryptography became a dependency, and the macOS build fix had to be
# applied to each by hand. Nothing checked either.
FORMULAE = [Path("packaging/homebrew/whiskerless.rb"), Path("packaging/homebrew/whiskerless-rc.rb")]


def _formula(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    body = text.split(start, 1)
    assert len(body) == 2, f"marker {start!r} missing"
    return body[1].split(end, 1)[0]


def test_both_formulae_declare_the_same_dependencies() -> None:
    """A build dependency added to one and not the other is a formula that fails
    only on the channel nobody tested."""
    declared = [
        sorted(
            line.strip()
            for line in _formula(str(p)).splitlines()
            if line.strip().startswith("depends_on")
        )
        for p in FORMULAE
    ]
    assert declared[0] == declared[1], f"formula dependencies drifted: {declared}"


def test_both_formulae_carry_the_same_resource_closure() -> None:
    """`packaging/homebrew-resources.py` emits one block for both. Regenerating
    into a single file is the exact mistake that shipped a formula whose every
    command died on `ModuleNotFoundError: cryptography`."""
    blocks = [_between(_formula(str(p)), "BEGIN RESOURCES", "END RESOURCES") for p in FORMULAE]
    assert blocks[0] == blocks[1], "resource closures drifted between the two formulae"


def test_both_formulae_install_the_same_way() -> None:
    """The install body carries the macOS build fix; applying it to one formula
    only leaves the other producing a binary dyld refuses to load."""
    bodies = [_between(_formula(str(p)), "def install", "\n  end") for p in FORMULAE]
    assert bodies[0] == bodies[1], "install bodies drifted between the two formulae"


# --- the man page cannot silently fall behind the CLI -----------------------------
def test_the_man_page_documents_every_subcommand() -> None:
    """A man page is only worth shipping if it is true. Adding a subcommand and
    forgetting the page is invisible in review — and once the packages are in a
    repository, lintian checks the page EXISTS but never that it is complete."""
    from whiskerless.cli import build_parser

    page = (REPO / "packaging" / "whiskerless.1").read_text(encoding="utf-8")
    sub = next(a for a in build_parser()._actions if getattr(a, "_name_parser_map", None))
    # Only .TP entries count as documentation. A bare `.B backup` mention in
    # ENVIRONMENT is a cross-reference, not an entry — matching on those meant
    # deleting a command's actual entry still passed.
    entries = set()
    lines = page.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == ".TP" and index + 1 < len(lines):
            following = lines[index + 1]
            if following.startswith(".B "):
                entries.add(following[3:].split()[0].strip('"'))
    missing = sorted(set(sub.choices) - entries)
    assert not missing, f"no .TP entry in whiskerless.1 for: {missing}"


def test_the_man_page_is_installed_by_the_packages() -> None:
    """Writing it is half the job; lintian cares that it reaches
    /usr/share/man/man1."""
    recipe = yaml.safe_load((REPO / "packaging" / "nfpm.yaml").read_text(encoding="utf-8"))
    destinations = {entry["dst"] for entry in recipe["contents"]}
    assert "/usr/share/man/man1/whiskerless.1.gz" in destinations, (
        "Debian policy requires man pages compressed; dpkg does not gzip them and "
        "nfpm is not debhelper, so the recipe must install the .gz"
    )


# --- bottles: the matrix, the formula templates and the expected counts agree ------
#
# Three files have to say "four platforms" at once — the build matrix, the merge
# that refuses a short set, and the wait that counts manifests off the release.
# Nothing fails when they drift: the release publishes, and whoever is on the
# platform that lost its bottle quietly compiles cryptography for several
# minutes, which is the entire cost bottles were added to remove.
BOTTLES_WORKFLOW = REPO / ".github" / "workflows" / "bottles.yml"


def _bottle_matrix() -> list[dict[str, str]]:
    loaded = yaml.safe_load(BOTTLES_WORKFLOW.read_text(encoding="utf-8"))
    return loaded["jobs"]["build"]["strategy"]["matrix"]["include"]


def test_every_formula_template_can_receive_a_bottle_block() -> None:
    """A template that lost its marker publishes an un-bottled formula on that
    channel only, and update-tap.sh has nothing to fail on."""
    for path in FORMULAE:
        assert "REPLACE_BOTTLE_BLOCK" in _formula(str(path)), f"{path} cannot take a bottle block"


def test_the_bottle_matrix_covers_one_arch_per_platform() -> None:
    labels = sorted(entry["label"] for entry in _bottle_matrix())
    assert labels == ["arm64_linux", "arm64_sequoia", "sequoia", "x86_64_linux"], labels


def test_the_merge_demands_exactly_as_many_bottles_as_the_matrix_builds() -> None:
    """`--expect-tags` is what turns a missing platform from silent into fatal;
    it is only true while it matches the matrix."""
    tap = (REPO / "packaging" / "update-tap.sh").read_text(encoding="utf-8")
    demanded = re.search(r"--expect-tags (\d+)", tap)
    assert demanded, "update-tap.sh no longer demands a bottle count"
    assert int(demanded.group(1)) == len(_bottle_matrix())


def test_the_publish_wait_counts_both_formulae_on_a_stable_tag() -> None:
    """A candidate bottles one formula, a release bottles both — because a
    bottle's keg is rooted at `<formula>/<version>/` and cannot be renamed into
    the other channel. The wait has to expect the right number or it either
    times out or proceeds on a half-built set."""
    publish = (REPO / ".forgejo" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    platforms = len(_bottle_matrix())
    assert re.search(rf"\*-rc\.\*\)\s*expected={platforms} ", publish), "rc tag expects one formula"
    assert re.search(rf"\*\)\s*expected={platforms * 2} ", publish), "stable tag expects both formulae"


# --- the install matrix is a gate, not a notification -------------------------------
#
# It was written, it went red on a real candidate, and nothing stopped that
# candidate being promotable — because the workflow's own header said "what it can
# gate is the next stable cut" and no such gate had been built. A comment is not a
# control. These assert the control.
RELEASE_WORKFLOW = REPO / ".forgejo" / "workflows" / "release.yml"
INSTALL_MATRIX = REPO / ".github" / "workflows" / "install-matrix.yml"
INSTALL_MATRIX_LINUX = REPO / ".forgejo" / "workflows" / "install-matrix.yml"


def test_a_stable_cut_is_gated_on_the_candidates_install_matrix() -> None:
    release = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert "candidate-gate" in release["jobs"], "the candidate gate is gone"
    assert "candidate-gate" in release["jobs"]["tag"]["needs"], (
        "the tag job no longer waits on the candidate gate — a red candidate is promotable again"
    )


def test_the_candidate_gate_checks_out_the_tags_it_reasons_about() -> None:
    """It derives the version from the tags. A shallow checkout has none, so it
    would ask about 0.0.1, find no candidates, and pass — loudest silence there
    is."""
    release = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    checkout = release["jobs"]["candidate-gate"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0, "candidate-gate would run on a tagless checkout"


def test_both_install_matrices_record_which_tag_they_tested() -> None:
    """Each forge keeps it in a different place, and the gate reads both.

    A tag PUSH is self-describing (head_branch on GitHub, prettyref on Forgejo). A
    re-dispatch is not: it runs from main on purpose, so a fix to these scripts is
    what re-runs rather than the copies frozen at the tag. GitHub records the
    subject in the run-name; Forgejo IGNORES run-name entirely — a dispatched run's
    title is just the workflow name — so there it has to live in a job name, which
    Forgejo does evaluate. Lose either and a re-dispatched green matrix becomes
    unfindable, and the gate blocks a release that is fine."""
    gate = (REPO / "packaging" / "check-rc-install-matrix.sh").read_text(encoding="utf-8")

    github = yaml.safe_load(INSTALL_MATRIX.read_text(encoding="utf-8"))
    run_name = github.get("run-name", "")
    assert run_name.startswith("Install matrix (macOS + Linux arm64)"), run_name
    assert "inputs.tag" in run_name and "github.ref_name" in run_name, run_name
    assert "Install matrix (macOS + Linux arm64) $TAG" in gate, (
        "the gate stopped matching the GitHub run-name"
    )

    linux = yaml.safe_load(INSTALL_MATRIX_LINUX.read_text(encoding="utf-8"))
    assert "run-name" not in linux, "Forgejo ignores run-name; it would be a decoy here"
    wait_name = linux["jobs"]["wait"]["name"]
    assert "inputs.tag" in wait_name and "github.ref_name" in wait_name, wait_name
    assert "/jobs" in gate and "contains($t)" in gate, (
        "the gate stopped reading job names, which is the only place Forgejo keeps the tag"
    )


def test_a_stable_cut_requires_both_halves_of_the_install_matrix() -> None:
    """Linux amd64 runs on Forgejo, macOS and Linux arm64 on GitHub, so a gate that
    asked only one forge would qualify a candidate on half a matrix — the same
    fail-open as not asking at all."""
    gate = (REPO / "packaging" / "check-rc-install-matrix.sh").read_text(encoding="utf-8")
    assert "api.github.com" in gate, "the gate stopped asking GitHub about the macOS + arm64 half"
    assert "forgejo.bryantserver.com" in gate, "the gate stopped asking Forgejo about the amd64 half"
    # Scoped server-side on both forges. Unscoped, each asks for a page of every
    # run there has ever been and stops containing the one it wants.
    assert "actions/workflows/install-matrix.yml/runs" in gate, "the GitHub query lost its scope"
    assert "workflow_id=install-matrix.yml" in gate, "the Forgejo query lost its scope"


def test_both_architectures_install_test_the_same_channels() -> None:
    """One script, two callers, because the amd64 and arm64 halves of the matrix now
    live in different files on different forges. Inlining either channel list is how
    an arm64-only packaging break survives a green matrix."""
    forgejo = (REPO / ".forgejo" / "workflows" / "install-matrix.yml").read_text(encoding="utf-8")
    github = INSTALL_MATRIX.read_text(encoding="utf-8")
    assert "install-matrix-arch.sh amd64" in forgejo, "the amd64 half stopped using the shared list"
    assert "install-matrix-arch.sh arm64" in github, "the arm64 half stopped using the shared list"
    script = (REPO / "packaging" / "install-matrix-arch.sh").read_text(encoding="utf-8")
    # It refuses to run for an architecture the host is not, so a leg that lands on
    # the wrong runner fails loudly instead of quietly reporting on an emulator.
    assert "that would be emulation" in script, "the shared script stopped refusing emulation"


def test_every_install_channel_is_actually_run() -> None:
    """The Dockerfile is the definition and the shared script is the caller. A channel
    added to one and not the other fails silently in the direction that matters:
    buildx errors on a target that does not exist, but a target nobody builds is
    never tested while still looking like coverage."""
    dockerfile = (REPO / "packaging" / "install-smoke.Dockerfile").read_text(encoding="utf-8")
    defined = set(re.findall(r"^FROM scratch AS ([a-z0-9-]+)-result$", dockerfile, re.M))
    assert defined, "the Dockerfile defines no channels"
    script = (REPO / "packaging" / "install-matrix-arch.sh").read_text(encoding="utf-8")
    listed = re.search(r"^CHANNELS=\(\n(.*?)^\)$", script, re.M | re.S)
    assert listed, "install-matrix-arch.sh no longer declares a channel list"
    channels = set(listed.group(1).split())
    assert channels == defined, (
        f"the matrix runs {sorted(channels)}, Dockerfile defines {sorted(defined)}"
    )


def test_the_wait_is_one_definition_used_by_both_matrices() -> None:
    """A stable release carries both formulae's bottles. Pooling them makes the
    checksum comparison unsatisfiable, and the wait spends its whole deadline
    before failing a release that was fine. Two COPIES of this would drift, and
    the drift shows up as one forge passing a half-published release."""
    for path in (INSTALL_MATRIX, INSTALL_MATRIX_LINUX):
        assert "packaging/wait-for-release.sh" in path.read_text(encoding="utf-8"), (
            f"{path.name} grew its own copy of the wait"
        )
    wait = (REPO / "packaging" / "wait-for-release.sh").read_text(encoding="utf-8")
    assert re.search(r"\*-rc\.\*\)\s*FORMULA=whiskerless-rc", wait), "rc tags lost their formula"
    assert re.search(r"\*\)\s*FORMULA=whiskerless\b", wait), "stable tags lost their formula"
    assert 'select(.formula.name == $f)' in wait, (
        "the wait pools every manifest again — it can never balance on a stable tag"
    )


# --- one renderer, and it never emits a marker --------------------------------------
#
# Three places used to perform this substitution — the tap's two passes and the
# install smoke — and teaching only two of them about a newly added marker shipped
# a formula carrying the bare word `REPLACE_BOTTLE_BLOCK`. Ruby PARSES a bare word
# happily (it is a constant reference), so `ruby -c` cannot catch it and neither
# can any container: it surfaced only when Homebrew loaded the formula, on macOS,
# on the job that gates every release.
#
# The fix is structural — one renderer — so these check the structure holds, by
# running the real script rather than reimplementing what it does.
RENDER = REPO / "packaging" / "render-formula.sh"
RENDER_CALLERS = [REPO / "packaging" / "update-tap.sh", REPO / "packaging" / "test-homebrew-formula.sh"]


def _render(template: Path, block: str | None = None) -> str:
    args = [str(RENDER), str(template), "0.2.0rc28", "0" * 64]
    with tempfile.TemporaryDirectory() as tmp:
        if block is not None:
            blockfile = Path(tmp) / "block"
            blockfile.write_text(block)
            args.append(str(blockfile))
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"render-formula.sh failed:\n{proc.stderr}"
    return proc.stdout


@pytest.mark.parametrize("path", FORMULAE, ids=lambda p: Path(p).name)
def test_rendering_a_template_leaves_no_marker(path: Path) -> None:
    assert "REPLACE_" not in _render(path)


@pytest.mark.parametrize("path", FORMULAE, ids=lambda p: Path(p).name)
def test_rendering_with_a_bottle_block_leaves_no_marker(path: Path) -> None:
    block = "\n".join(
        ["  bottle do", '    root_url "https://example.invalid/d"']
        + [
            f'    sha256 cellar: "/opt/homebrew/Cellar", {tag}: "{"a" * 64}"'
            for tag in ("arm64_sequoia", "sequoia", "x86_64_linux", "arm64_linux")
        ]
        + ["  end"]
    )
    rendered = _render(path, block)
    assert "REPLACE_" not in rendered
    assert "bottle do" in rendered


def test_the_renderer_refuses_a_template_it_cannot_fully_render() -> None:
    """The property the whole consolidation rests on: an unhandled marker is fatal
    where it is introduced, not silent until Homebrew loads the formula."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.rb"
        bad.write_text('class X < Formula\n  url "u"\n  REPLACE_SOMETHING_NEW\nend\n')
        proc = subprocess.run(
            [str(RENDER), str(bad), "0.2.0rc28", "0" * 64], capture_output=True, text=True, check=False
        )
    assert proc.returncode != 0, "an unrendered marker was emitted instead of refused"
    assert "REPLACE_SOMETHING_NEW" in proc.stderr


def test_nothing_renders_a_formula_behind_the_renderers_back() -> None:
    """A fourth copy of the substitution would reintroduce exactly the drift that
    broke the release gate, so the callers must delegate rather than sed it."""
    for caller in RENDER_CALLERS:
        text = caller.read_text(encoding="utf-8")
        assert "render-formula.sh" in text, f"{caller.name} does not use the shared renderer"
        assert "REPLACE_SDIST_SHA256" not in text, (
            f"{caller.name} substitutes markers itself instead of delegating"
        )


# --- the dnf config pins our key and only our key ---------------------------------
#
# dnf accepts a package signed by ANY key listed in `gpgkey`, so adding Forgejo's
# registry key "as well, to be safe" is not additive — it makes a compromise of the
# single host that serves the packages sufficient to install arbitrary code on
# every subscriber. Checked against the live registry, both ways: with both keys
# listed, a package signed only by Forgejo's key installs; with ours alone, the
# same package is refused.
#
# Our key is the one worth pinning because it is the only one that does not live on
# that host — Forgejo keeps its registry keys in the database, in plaintext.
REPO_FILES = sorted((REPO / "packaging").glob("*.repo"))
FORGEJO_REGISTRY_KEY = "/api/packages/SisyphusMD/rpm/repository.key"
OUR_KEY = "packaging/sisyphusmd-signing-key.asc"


def test_there_are_repo_files_to_check() -> None:
    assert REPO_FILES


OUR_KEY_URL = (
    "https://forgejo.bryantserver.com/SisyphusMD/whiskerless"
    "/raw/branch/main/packaging/sisyphusmd-signing-key.asc"
)
SIGNING_KEY_ID = "CCE50015D058E9BF"


def _gpgkey_urls(text: str) -> list[str]:
    """Every key the file trusts, including INI continuation lines.

    An indented line after `gpgkey=` continues the value, which is exactly how a
    second key gets added without touching the `gpgkey=` line itself — so reading
    only that one line would miss it.
    """
    urls: list[str] = []
    collecting = False
    for line in text.splitlines():
        if line.startswith("gpgkey="):
            collecting = True
            urls += line[len("gpgkey=") :].split()
        elif collecting and line[:1] in (" ", "\t"):
            urls += line.split()
        elif collecting:
            collecting = False
    return urls


@pytest.mark.parametrize("path", REPO_FILES, ids=lambda p: p.name)
def test_the_dnf_config_trusts_our_key_alone(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    config = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert _gpgkey_urls(config) == [OUR_KEY_URL], (
        f"{path.name} must trust exactly one key, ours — dnf accepts a package signed "
        f"by ANY key listed here"
    )
    assert FORGEJO_REGISTRY_KEY not in config, (
        f"{path.name} trusts Forgejo's registry key; a package signed by it would then install"
    )
    assert "gpgcheck=1" in config, f"{path.name} does not verify package signatures at all"
    # Exact value, not merely absent: flipping this to 1 makes dnf verify the index
    # against Forgejo's key, which this file deliberately does not list — so the
    # repository stops working entirely.
    assert "repo_gpgcheck=0" in config, (
        f"{path.name} must set repo_gpgcheck=0 — it lists no key that could verify the index"
    )


def test_the_pinned_key_is_the_one_this_repository_ships() -> None:
    """The URL could be right while the file behind it is some other key."""
    key = REPO / "packaging" / "sisyphusmd-signing-key.asc"
    assert key.exists(), "the signing key the .repo files pin is not in the repository"
    if not shutil.which("gpg"):
        pytest.skip("no gpg available to read the key's fingerprint")
    proc = subprocess.run(
        ["gpg", "--show-keys", "--with-colons", str(key)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    fingerprints = [ln.split(":")[9] for ln in proc.stdout.splitlines() if ln.startswith("fpr:")]
    assert any(f.endswith(SIGNING_KEY_ID) for f in fingerprints), (
        f"the shipped key is not {SIGNING_KEY_ID}: {fingerprints}"
    )


@pytest.mark.parametrize("path", REPO_FILES, ids=lambda p: p.name)
def test_the_dnf_config_names_a_distribution_the_publisher_writes(path: Path) -> None:
    """A baseurl pointing at a group nothing publishes to is a repository that
    resolves, returns an empty index, and reports no candidate."""
    publisher = (REPO / "packaging" / "publish-registry.sh").read_text(encoding="utf-8")
    baseurl = next(ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("baseurl="))
    distribution = baseurl.rstrip("/").rsplit("/", 1)[1]
    assert re.search(rf'dists="[^"]*\b{distribution}\b', publisher), (
        f"{path.name} points at '{distribution}', which publish-registry.sh never writes to"
    )


# --- in-page anchors, which two forges do not agree how to spell ---------------------
#
# The project is read on Forgejo and on the GitHub mirror, and their heading
# sluggers differ on exactly one character: an apostrophe. GitHub DROPS it
# (`What's not here` -> `whats-not-here`); Forgejo turns it into a hyphen
# (`what-s-not-here`). The link is rewritten to GitHub's spelling either way, so a
# heading with an apostrophe renders a link that works on the mirror and is dead
# on the primary — silently, and only for the people reading it there.
#
# Commas, colons and parentheses were checked against both rendered pages and
# agree; the apostrophe is the whole rule.
def test_no_in_page_anchor_targets_a_heading_with_an_apostrophe() -> None:
    offenders = []
    # TRACKED files only. `.claude/` holds git-ignored working notes; letting a
    # local-only file fail the suite would block work on content that cannot even
    # be committed, and it renders on neither site.
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    for name in filter(None, listed.split("\0")):
        md = REPO / name
        text = md.read_text(encoding="utf-8")
        headings = [
            re.sub(r"[*_`]", "", h).strip() for h in re.findall(r"^#+\s+(.*)$", text, re.M)
        ]
        targeted = set(re.findall(r"\]\((#[^)]+)\)", text))
        for heading in headings:
            if not ("'" in heading or "\u2019" in heading):
                continue
            lowered = heading.lower()
            # Both spellings are broken, just on opposite sites: whichever one is
            # written, the other forge computes the other and finds nothing.
            github = re.sub(r"[^a-z0-9 -]", "", lowered).replace(" ", "-")
            # Only the apostrophe differs. Commas, colons and parentheses were
            # read off both rendered pages and slug identically, so hyphenating
            # them here would compute a slug neither forge emits — and the check
            # would look for a link nobody could have written.
            forgejo = re.sub(r"[^a-z0-9 -]", "", lowered.replace("'", "-").replace("\u2019", "-"))
            forgejo = forgejo.replace(" ", "-")
            for slug in (github, forgejo):
                if f"#{slug}" in targeted:
                    offenders.append(f"{name}: {heading!r} <- #{slug}")
    assert offenders == [], (
        "an apostrophe in a linked heading is dead on one of the two forges:\n  "
        + "\n  ".join(offenders)
    )


# --- which forge runs what ----------------------------------------------------------
#
# Forgejo runs everything; GitHub runs only what cannot run anywhere else. The rule
# and its reasoning are in docs/design/ci-split.md — this is what keeps it true.
#
# It exists because the rule used to be carried by a COMMENT, and the comment was
# wrong: bottles.yml stated that Forgejo's Linux runner is arm64-only, when every
# Forgejo runner is x86_64 and arm64 is the emulated one. Anyone following it sent
# work to the wrong forge believing they had no choice.
#
# An exception is fine. An exception nobody wrote a reason for is not.
GITHUB_ONLY: dict[tuple[str, str], str] = {
    ("hassfest.yml", "*"):
        "a GitHub-ecosystem action; the Forgejo runner resolves actions from "
        "data.forgejo.org, which does not carry home-assistant/actions",
    ("ci-pr.yml", "*"):
        "pull requests are on GitHub by project policy, so Forgejo never sees the event",
    ("retry-infra-failures.yml", "*"):
        "it re-runs GitHub workflow runs through the GitHub API — nothing to do elsewhere",
    ("bottles.yml", "*"):
        "three of the four tags need macOS or native arm64 anyway; x86_64_linux is built "
        "beside them because bottle-block.py refuses a set whose manifests disagree on "
        "cellar, and one matrix in one run is how that stays true — splitting this one leg "
        "across forges would mean collecting manifests across them too",
    ("release-macos.yml", "publish"):
        "it appends the artifacts the macOS jobs produced IN THE SAME RUN; artifacts are "
        "run-scoped, so on another forge there would be nothing to append",
    ("install-matrix.yml", "wait"):
        "sequences the macOS and native-arm64 legs that must run on this forge",
    ("install-matrix.yml", "summary"):
        "reports the macOS and native-arm64 legs that must run on this forge",
    ("release-linux-arm64.yml", "build"):
        "ubuntu-24.04-arm is native arm64, which nothing here has; the alternative is "
        "the emulation this project removed",
}


def _runner_labels(job: dict[str, Any]) -> set[str]:
    """Every concrete runner a job can land on, resolving a matrix expression."""
    runs_on = job.get("runs-on", "")
    if isinstance(runs_on, list):
        return {str(r) for r in runs_on}
    runs_on = str(runs_on)
    if "${{" not in runs_on:
        return {runs_on}
    key = runs_on.split(".")[-1].split("}")[0].strip()
    matrix = job.get("strategy", {}).get("matrix", {})
    labels = {str(entry[key]) for entry in matrix.get("include", []) if key in entry}
    if isinstance(matrix.get(key), list):
        labels |= {str(value) for value in matrix[key]}
    # An unresolvable expression must not read as "no Linux here".
    return labels or {runs_on}


def _github_jobs() -> list[tuple[str, str, set[str]]]:
    found = []
    # Both spellings: Actions accepts .yaml too, and a rule that only sees .yml is
    # a rule anyone can step around without meaning to.
    workflows = (REPO / ".github" / "workflows")
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (loaded.get("jobs") or {}).items():
            found.append((path.name, str(job_id), _runner_labels(job)))
    return found


def test_there_are_github_jobs_to_check() -> None:
    """The sweep below passes trivially if the glob ever stops matching."""
    assert len(_github_jobs()) >= 8


def test_github_only_runs_what_only_github_can_run() -> None:
    unjustified = []
    for workflow, job_id, labels in _github_jobs():
        # Architecture decides the forge: macOS and arm64 have no native runner here,
        # and the alternative to GitHub for either is emulation, which this project
        # does not do anywhere. Everything else belongs on Forgejo.
        if labels and all(label.startswith("macos") or label.endswith("-arm") for label in labels):
            continue
        if (workflow, "*") in GITHUB_ONLY or (workflow, job_id) in GITHUB_ONLY:
            continue
        unjustified.append(f"{workflow}:{job_id} runs on {sorted(labels)}")
    assert unjustified == [], (
        "these run on GitHub without being macOS or a recorded exception — move them to "
        ".forgejo/workflows/, or add them to GITHUB_ONLY with the reason "
        "(see docs/design/ci-split.md):\n  " + "\n  ".join(unjustified)
    )


def test_no_exception_outlives_the_job_it_excused() -> None:
    """A stale entry silently re-permits whatever later takes that name."""
    present = {(w, "*") for w, _, _ in _github_jobs()} | {(w, j) for w, j, _ in _github_jobs()}
    stale = sorted(f"{w}:{j}" for (w, j) in GITHUB_ONLY if (w, j) not in present)
    assert stale == [], f"GITHUB_ONLY excuses jobs that no longer exist: {stale}"


# --- what HACS demands of the manifest ----------------------------------------------
#
# `hacs/action` checks this on the mirror, and found `issue_tracker` missing the
# first time it ran — eight of its nine checks passed and that one did not, which is
# how a repository ends up looking installable while HACS declines it. The action is
# the authority; this is here so the requirement is visible in the tree and fails
# fast, rather than only on a forge some contributors never look at.
def test_the_integration_manifest_carries_what_hacs_requires() -> None:
    manifest = json.loads(
        (REPO / "custom_components" / "whiskerless" / "manifest.json").read_text(encoding="utf-8")
    )
    for key in ("domain", "name", "documentation", "issue_tracker", "version", "codeowners"):
        assert manifest.get(key), f"manifest.json is missing {key}, which HACS requires"
    assert manifest["issue_tracker"].startswith("https://github.com/SisyphusMD/whiskerless"), (
        "issues go to GitHub, not the primary forge"
    )


def test_the_manifest_keys_are_ordered_the_way_hassfest_wants() -> None:
    """domain and name first, everything else alphabetical. Adding a key in the
    wrong place is a hassfest failure on the mirror and nowhere else."""
    manifest = json.loads(
        (REPO / "custom_components" / "whiskerless" / "manifest.json").read_text(encoding="utf-8")
    )
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"], keys[:2]
    assert keys[2:] == sorted(keys[2:]), keys[2:]



# --- Renovate policy, shared with dreame-valetudo ------------------------------------
#
# Both projects automerge patch, minor and digest on green, and both allow a dependency to be held
# back ONLY when green cannot see the risk. The identical test lives in both repos.
def test_every_renovate_hold_says_what_CI_cannot_reach() -> None:
    """A hold must carry its reason, and the only admissible reason is that green says nothing.

    A hold with no stated reason is a chore: it stops a bump for a risk nobody can name, and the
    person who added it is not the person who has to clear the PR six months later. But a blanket
    ban is too strong, because some dependencies are genuinely outside what CI can exercise —
    `bleak` here, `pyusb` in the sibling. No runner has a Bluetooth radio, and the transport is
    faked at the bleak boundary, so a green run is silent about the code that re-points a robot.
    Automerging on a signal that cannot see the risk is worse than holding.

    So: hold if you must, but say what CI cannot reach, in `prBodyNotes`, where the reviewer sees it.
    """
    config = json.loads((REPO / ".renovaterc.json").read_text(encoding="utf-8"))
    undocumented = [
        rule.get("matchDepNames") or rule.get("matchManagers") or rule.get("description", "?")[:60]
        for rule in config["packageRules"]
        if rule.get("automerge") is False and not rule.get("prBodyNotes")
    ]
    assert undocumented == [], f"held with no stated reason: {undocumented}"


def test_the_macos_and_linux_releases_freeze_with_the_same_toolchain() -> None:
    """One release, one PyInstaller, one CPython — across two forges and three architectures.

    The Linux pins live in packaging/release-pins.env; the macOS job installs its own, because it
    builds on a Mac and never sources that file. Nothing structural keeps the two equal, so they
    drifted: macOS asked for an unpinned `pyinstaller` and a fuzzy `3.14` while Linux pinned exact
    versions. That means the .pkg and the .deb of the SAME release could be frozen by different
    versions of the one dependency that has already cost this project a release, silently.

    Renovate holds both under one depName, so they bump in a single PR — this is what makes sure
    they were equal to begin with. The sibling project pins the same coupling.
    """
    pins = (REPO / "packaging" / "release-pins.env").read_text(encoding="utf-8")
    macos = (REPO / ".github" / "workflows" / "release-macos.yml").read_text(encoding="utf-8")

    linux_pyi = re.search(r'PYINSTALLER="([^"]+)"', pins)
    macos_pyi = re.search(r"pyinstaller==([0-9][\w.]*)", macos)
    assert linux_pyi and macos_pyi, "a PyInstaller pin is missing or unrecognisable"
    assert linux_pyi.group(1) == macos_pyi.group(1), (
        f"PyInstaller differs: linux {linux_pyi.group(1)}, macOS {macos_pyi.group(1)}"
    )

    linux_py = re.search(r'PYTHON_VERSION="([^"]+)"', pins)
    macos_py = re.search(r'python-version: "([^"]+)"', macos)
    assert linux_py and macos_py, "a CPython pin is missing or unrecognisable"
    assert linux_py.group(1) == macos_py.group(1), (
        f"CPython differs: linux {linux_py.group(1)}, macOS {macos_py.group(1)}"
    )
    # Exact, not a series: "3.14" resolves to whatever the runner image happens to ship that week.
    assert macos_py.group(1).count(".") == 2, f"macOS CPython is not exact: {macos_py.group(1)}"


def test_no_publish_job_outruns_the_ref_guard() -> None:
    """publish.yml is dispatchable so a partly-failed release can be finished. The guard job refuses
    a dispatch whose ref is not a release tag, because "main" would otherwise BE the version:
    packages named for it, and releases called `main` created on all three registries.

    But several jobs carry `always()` or `!cancelled()` so that one registry failing does not skip
    the others — and those override a FAILED dependency, not merely an unsuccessful release. A guard
    that refused the ref therefore stopped nothing: every external-write job downstream still ran.
    Naming the guard in `needs` is not enough either; the condition has to test its result.
    """
    workflow = yaml.safe_load(
        (REPO / ".forgejo" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    )
    assert "guard" in workflow["jobs"], "the ref guard is gone"
    unguarded = []
    for name, job in workflow["jobs"].items():
        condition = str(job.get("if") or "")
        if "always()" not in condition and "cancelled()" not in condition:
            continue  # the implicit needs-success gate already covers it
        needs = job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else list(needs)
        if "guard" not in needs or "needs.guard.result" not in condition:
            unguarded.append(name)
    assert unguarded == [], (
        "these run even when the guard refused the ref, and write to registries while they do: "
        f"{unguarded}"
    )


def test_renovate_still_reads_the_pins_after_they_moved() -> None:
    """The build pins live in `packaging/release-pins.env` because two forges build one
    release and one file is what keeps their pins equal. Renovate's custom managers are
    path-scoped, and they were written when those pins were inline in a workflow. A
    pattern that no longer matches does not fail — it finds nothing, opens no PR, and
    every pin quietly stops being updated while the config still looks correct.

    Same for `refresh-pins.sh`: it recomputes PYTHON_SHA256, and Renovate runs it as a
    postUpgradeTask on a branch nobody reads. Pointed at the wrong file it would rewrite
    a checksum that is not there, and a Python bump would automerge green and break every
    later release inside linux.Dockerfile.
    """
    pins = REPO / "packaging" / "release-pins.env"
    assert pins.exists(), "the shared build pins are gone"
    annotated = {
        line.split("=", 1)[0]
        for line in pins.read_text(encoding="utf-8").splitlines()
        if "=" in line and line[:1].isupper()
    }
    assert {"PYINSTALLER", "PYTHON_VERSION", "PYTHON_SHA256"} <= annotated, annotated

    config = json.loads((REPO / ".renovaterc.json").read_text(encoding="utf-8"))
    managers = config.get("customManagers", [])
    reaching = [
        m for m in managers
        if any("release-pins" in pattern for pattern in m.get("managerFilePatterns", []))
    ]
    assert len(reaching) == 2, (
        "both custom managers must scan release-pins.env — the docker-digest one for the "
        f"manylinux and nfpm images, the version one for PyInstaller and CPython; {len(reaching)} do"
    )
    assert "packaging/release-pins.env" in config["postUpgradeTasks"]["fileFilters"], (
        "refresh-pins.sh rewrites release-pins.env, so that is a file Renovate must keep"
    )
    refresh = (REPO / "packaging" / "refresh-pins.sh").read_text(encoding="utf-8")
    assert "release-pins.env" in refresh, "refresh-pins.sh is still editing the old location"


def test_renovate_automerges_patch_minor_and_digest_on_green() -> None:
    """The same set as the sibling. CI here is the stronger of the two — two suites at a 99% floor,
    two strict mypy invocations, a 25-channel install matrix, hassfest — so if green is trustworthy
    anywhere it is trustworthy here. Runtime deps are floors with no rangeStrategy, so a satisfied
    `>=` bound never moves and what actually lands is the dev toolchain and pinned action SHAs."""
    config = json.loads((REPO / ".renovaterc.json").read_text(encoding="utf-8"))
    blanket = [r for r in config["packageRules"] if r.get("automerge") is True]
    assert len(blanket) == 1, "more than one blanket automerge rule"
    assert sorted(blanket[0]["matchUpdateTypes"]) == ["digest", "minor", "patch"]


# --- the public surface, and the one consumer that proves it ------------------------
def test_the_integration_imports_nothing_the_library_does_not_promise() -> None:
    """The bundled integration is this library's reference consumer, so what it reaches for IS the
    API whether or not anything says so.

    It was reaching past the declared surface — `devices.litter_robot_4.calibration` and `.derive`
    were imported by the integration and absent from the device package's `__all__`. That is the
    quiet failure mode of a compatibility promise: the promise stays small and true while the real
    consumed surface grows around it, so a "safe" rename breaks a consumer the promise said was not
    there. Anything the integration needs is public; if that feels like too much to promise, the
    answer is for the integration to need less, not for the promise to look smaller than reality.
    """
    import ast

    # The integration is written for Home Assistant's interpreter (3.13+) and uses PEP 695 syntax —
    # `type X = ...`, `def f[T]`. This suite also runs on the LIBRARY's 3.11.0 floor, where parsing
    # that is a SyntaxError in ast itself, not a finding about the code. The floor exists for the
    # library; the integration has its own 3.13 job and its own mypy invocation.
    if sys.version_info < (3, 12):
        pytest.skip("the integration uses PEP 695 syntax, which this interpreter cannot parse")

    core = _module_names(REPO / "src" / "whiskerless" / "__init__.py")
    device = _module_names(REPO / "src" / "whiskerless" / "devices" / "litter_robot_4" / "__init__.py")

    unpromised: list[str] = []
    for path in sorted((REPO / "custom_components" / "whiskerless").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("whiskerless"):
                continue
            parts = node.module.split(".")
            # `from whiskerless.devices.litter_robot_4.<sub> import X` is reaching into a submodule:
            # the submodule itself has to be public, and X has to be in ITS __all__.
            if len(parts) == 4:
                sub = REPO / "src" / "whiskerless" / "devices" / "litter_robot_4" / f"{parts[3]}.py"
                if parts[3] not in device:
                    unpromised.append(f"{path.name}: submodule {parts[3]}")
                    continue
                names = _module_names(sub)
                if not names:
                    # A module with no `__all__` promises nothing, so skipping it here let every
                    # import from it pass — the check reported parity while enforcing nothing.
                    unpromised.append(f"{path.name}: {parts[3]} declares no __all__")
                    continue
                unpromised += [
                    f"{path.name}: {parts[3]}.{a.name}"
                    for a in node.names
                    if a.name not in names
                ]
            elif node.module == "whiskerless":
                unpromised += [f"{path.name}: {a.name}" for a in node.names if a.name not in core]
            elif node.module == "whiskerless.devices.litter_robot_4":
                unpromised += [f"{path.name}: {a.name}" for a in node.names if a.name not in device]
            else:
                # Everything else under `whiskerless.` is INTERNAL, per CONTRIBUTING.md. Falling
                # through silently meant `from whiskerless.safety import assert_sendable` passed
                # this check entirely, so moving `safety` could have broken the published-library
                # consumer with nothing in CI noticing.
                unpromised.append(f"{path.name}: {node.module} is an internal module")

    assert unpromised == [], "the integration imports names the library does not promise:\n  " + "\n  ".join(unpromised)


def _module_names(path: Path) -> set[str]:
    """The names a module declares in `__all__`, or an empty set if it declares none."""
    import ast

    if not path.exists():
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}  # type: ignore[attr-defined]
    return set()


def test_the_infra_retry_watches_every_github_workflow() -> None:
    """A runner fault is not selective about which workflow it lands on, so a partial watch list is
    just an undetected flake somewhere else. This started at three of seven — missing the bottle
    build and the install matrix, which are the longest-running and most exposed of the lot."""
    retry = REPO / ".github" / "workflows" / "retry-infra-failures.yml"
    watched = set(yaml.safe_load(retry.read_text(encoding="utf-8"))[True]["workflow_run"]["workflows"])
    present = {}
    for path in sorted((REPO / ".github" / "workflows").glob("*.y*ml")):
        found = re.search(r"^name:\s*(.+)$", path.read_text(encoding="utf-8"), re.M)
        if found:
            present[found.group(1).strip()] = path.name
    # Itself excluded: a retry workflow retrying its own runner failure would recurse.
    unwatched = {n: f for n, f in present.items() if n not in watched and f != retry.name}
    assert unwatched == {}, f"GitHub workflows with no infra-retry cover: {unwatched}"
    assert watched <= set(present), f"watches workflows that do not exist: {watched - set(present)}"


def test_the_retired_signing_key_is_referenced_nowhere() -> None:
    """The key migration replaced the uppercase spelling everywhere and missed the lowercase one
    in two rpm signature assertions, which would have failed the install matrix for every
    correctly-signed package. Matched case-insensitively so a spelling cannot hide again."""
    # Assembled rather than written out, or this test is itself an offender.
    retired = "4bbacd5a" + "6ff38564"
    listed = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-co", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    offenders = []
    for name in listed:
        path = REPO / name
        if not path.is_file() or path.suffix in {".asc", ".png", ".gz"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # The CHANGELOG legitimately records the migration itself.
        if retired in text.lower() and name not in {"CHANGELOG.md", "docs/backlog.md"}:
            offenders.append(name)
    assert offenders == [], f"retired signing key still referenced: {offenders}"


def test_the_retired_key_path_still_serves_the_current_key() -> None:
    """`packaging/whiskerless-signing-key.asc` is kept as a byte-identical copy of the namespace
    key, and must not be deleted.

    Two 0.2.0 release candidates shipped a `whiskerless.repo` whose `gpgkey=` names that URL. A
    machine configured from one of them never rereads the file in this repository — it has its own
    copy under /etc/yum.repos.d — so deleting the key it points at leaves dnf unable to import the
    key the new packages are signed with, and that machine cannot upgrade at all.
    """
    legacy = REPO / "packaging" / "whiskerless-signing-key.asc"
    current = REPO / "packaging" / "sisyphusmd-signing-key.asc"
    assert legacy.exists(), "a machine configured from a 0.2.0 rc fetches this exact path"
    assert legacy.read_bytes() == current.read_bytes()


def test_the_pinned_standard_version_matches_what_is_actually_vendored() -> None:
    """Renovate bumps the pin. It does not re-vendor the files.

    The pin in `packaging/release-pins.env` records which standard this repo SHOULD carry;
    `STANDARD.lock` records which one it actually does. Nothing else compares them, and a bumped pin
    whose files were never re-synced leaves this repo green while running a different standard than
    it claims — the drift the lock exists to prevent, arriving through the one door the lock does not
    watch, since every vendored file still matches the older lock perfectly.

    The pin omits the leading `v` the tag carries, because the shared Renovate matchString requires a
    digit first and a `v`-prefixed value matches nothing at all, silently.
    """
    pins = (REPO / "packaging" / "release-pins.env").read_text(encoding="utf-8")
    found = re.search(r'^PROJECT_STANDARD="([^"]+)"', pins, re.M)
    assert found, "packaging/release-pins.env does not pin PROJECT_STANDARD"
    pinned = found.group(1)
    assert not pinned.startswith("v"), f"the pin carries a leading v, which Renovate will not match: {pinned}"

    lock = json.loads((REPO / "STANDARD.lock").read_text(encoding="utf-8"))
    assert lock["source_tag"] == f"v{pinned}", (
        f"pinned v{pinned}, but the vendored files come from {lock['source_tag']} — "
        "re-vendor from the pinned tag and land both together"
    )


def test_every_hold_survives_rule_ordering() -> None:
    """Renovate applies every matching packageRule in order, and the LAST one to set a field wins.

    So a hold placed ABOVE the broad patch/minor/digest automerge rule is silently undone by it: the
    config still reads as a hold, review still looks required, and the dependency automerges anyway.
    Position is not the property, so this resolves the rules the way Renovate does and asserts the
    value that actually results — for every held dependency, not just the newest one.
    """
    rules = json.loads((REPO / ".renovaterc.json").read_text(encoding="utf-8"))["packageRules"]

    def resolved(dep: str, update_type: str) -> object:
        value: object = None
        for rule in rules:
            names = rule.get("matchDepNames") or rule.get("matchPackageNames")
            if names is not None and dep not in names:
                continue
            types = rule.get("matchUpdateTypes")
            if types is not None and update_type not in types:
                continue
            if "automerge" in rule:
                value = rule["automerge"]
        return value

    held = sorted({
        dep
        for rule in rules
        if rule.get("automerge") is False
        for dep in (rule.get("matchDepNames") or rule.get("matchPackageNames") or [])
    })
    assert held, "no held dependencies found; this invariant would assert nothing"
    for dep in held:
        for update_type in ("patch", "minor", "digest"):
            assert resolved(dep, update_type) is False, (
                f"{dep} is written as a hold but resolves to automerge on {update_type}: "
                "its rule sits above the broad automerge rule, which overrides it"
            )


def test_renovate_never_edits_a_vendored_file() -> None:
    """A vendored file is owned by the standard, and editing it in place breaks STANDARD.lock.

    Renovate does not know that. Pointed at a locked path that carries a `# renovate:` annotation it
    opens a perfectly reasonable pin bump — and that PR then fails this repo's own drift check,
    because the file no longer matches the lock it was vendored under. The bump has to originate in
    the standard and arrive here as a re-vendor, so no manager may scan a locked path at all.
    """
    config = json.loads((REPO / ".renovaterc.json").read_text(encoding="utf-8"))
    vendored = set(json.loads((REPO / "STANDARD.lock").read_text(encoding="utf-8"))["files"])
    assert vendored, "no vendored files recorded; this invariant would assert nothing"

    scanned = [
        (index, path)
        for index, manager in enumerate(config.get("customManagers", []))
        for pattern in manager.get("managerFilePatterns", [])
        for path in sorted(vendored)
        if re.search(pattern.strip("/"), path)
    ]
    assert not scanned, (
        f"customManagers scan vendored files, whose bumps would fail the drift check: {scanned}"
    )


def test_the_inline_shellcheck_pin_matches_the_vendored_script() -> None:
    """Two copies of one pin, and they have to move together.

    `packaging/shellcheck-all.sh` is vendored, and the fork-PR workflow deliberately does NOT call
    it: that job runs on untrusted refs, where `actions/checkout` puts a FORK's copy of the script in
    the workspace, so the command has to be text this repo defines. The cost of that safety is a
    second copy of the image pin, which silently rots unless something compares them — a fork PR then
    qualifies against a different shellcheck than every other gate.
    """
    workflow = (REPO / ".github" / "workflows" / "ci-pr.yml").read_text(encoding="utf-8")
    script = (REPO / "packaging" / "shellcheck-all.sh").read_text(encoding="utf-8")

    found = re.search(r'SHELLCHECK="([^"]+)"', script)
    assert found, "packaging/shellcheck-all.sh no longer pins SHELLCHECK"
    assert f'SHELLCHECK="{found.group(1)}"' in workflow, (
        "the fork-PR workflow pins a different shellcheck image than the vendored script; "
        "the pin is owned by the standard, so re-vendor and update both copies together"
    )


def test_every_job_that_writes_the_tap_shares_one_concurrency_group() -> None:
    """Two tap writers running at once both clone the same tip.

    The loser pushes a non-fast-forward, and the tap keeps whichever formula won the race — a
    published tap missing the formula the release just built, with every job green. Mirrored from
    dreame-valetudo, which writes the same tap from the same three jobs.
    """
    publish = yaml.safe_load((REPO / ".forgejo" / "workflows" / "publish.yml").read_text())
    for job in ("homebrew-tap", "homebrew-bottles"):
        assert job in publish["jobs"], job
        group = publish["jobs"][job].get("concurrency", {}).get("group")
        assert group == "tap-write", f"{job} writes the tap outside the shared group: {group}"

    bottles = yaml.safe_load((REPO / ".forgejo" / "workflows" / "tap-bottles.yml").read_text())
    assert bottles.get("concurrency", {}).get("group") == "tap-write", bottles.get("concurrency")


def test_publishing_refuses_to_ship_unsigned_packages() -> None:
    """An unsigned package installs perfectly well, so nothing downstream notices.

    It fails only for subscribers running `gpgcheck=1` — the people who configured the repository
    the way the docs tell them to. Both forges build packages, so both have to hand the key in: an
    arm64 release signed by nobody would look identical to a signed one everywhere it was tested.

    Mirrored from dreame-valetudo, which builds and signs the same way.
    """
    build = (REPO / "packaging" / "build-linux-arch.sh").read_text()

    # `:?` and not a default: a missing key must end the build, not silently produce packages
    # nobody signed.
    assert "GPG_SIGNING_KEY:?" in build
    assert "NFPM_SIGNING_KEY_FILE" in build
    assert "GPG_SIGNING_KEY is not set" not in build, "the key is optional somewhere"

    # Written outside the build context. `docker cp . :/w` sends the whole tree, so a key staged
    # inside the workspace would be copied into the image alongside the package it signs.
    assert 'KEYFILE="$(mktemp)"' in build
    assert 'rm -f "$KEYFILE"' in build, "the key outlives the build"

    for workflow in (
        REPO / ".forgejo" / "workflows" / "publish.yml",
        REPO / ".github" / "workflows" / "release-linux-arm64.yml",
    ):
        assert "GPG_SIGNING_KEY: ${{ secrets.GPG_SIGNING_KEY }}" in workflow.read_text(), (
            f"{workflow.name} builds packages without handing in the signing key"
        )


def test_every_install_matrix_fetch_retries_and_stays_portable() -> None:
    """A single-attempt download makes the matrix only as reliable as one DNS lookup.

    Not hypothetical: a candidate's macOS leg died on `Could not resolve host: astral.sh`, and the
    infra-retry workflow rightly declined to rescue it — the failure was inside one of our own
    steps, which is exactly what that workflow refuses to launder into green.

    curl's `--retry` does NOT cover a name-resolution failure; only `--retry-all-errors` does, and
    that arrived in curl 7.71 while Rocky 8 ships 7.61 and rejects the option outright. So the
    container fetches retry in the shell, through `fetch.sh`, which every stage carries. The uv
    installer is the one exception: it runs on GitHub runners and Debian-family images where the
    flag exists — and it is written to a file first, because curl cannot rewind a pipe on retry.
    """
    dockerfile = REPO / "packaging" / "install-smoke.Dockerfile"
    text = dockerfile.read_text()

    assert (REPO / "packaging" / "fetch.sh").is_file(), "the retrying fetch helper is missing"

    # Every stage that can smoke can also fetch.
    smoke = text.count("COPY packaging/installed-smoke.sh /smoke.sh")
    helper = text.count("COPY packaging/fetch.sh /fetch")
    assert smoke == helper, f"{smoke} stages carry the smoke script but {helper} carry fetch.sh"

    raw = []
    for number, line in enumerate(text.splitlines(), 1):
        if not re.search(r"\bcurl\s+-[A-Za-z]+\s", line):
            continue
        if "astral.sh/uv/install.sh" in line:
            assert "--retry-all-errors" in line, f"install-smoke.Dockerfile:{number} cannot retry DNS"
            assert "| sh" not in line, f"install-smoke.Dockerfile:{number} pipes a retryable body to sh"
            continue
        raw.append(f"install-smoke.Dockerfile:{number}")
    assert not raw, f"fetches raw instead of through /fetch, so a DNS blip is fatal: {raw}"

    for name in (".github/workflows/install-matrix.yml", ".forgejo/workflows/install-matrix.yml"):
        path = REPO / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not re.search(r"\bcurl\s+-[A-Za-z]+\s", line):
                continue
            # These run on hosted runners only, never on the old curl the containers must
            # tolerate, so the flag that actually covers a failed DNS lookup is required here.
            assert "--retry-all-errors" in line, f"{path.name}:{number} cannot retry a DNS failure"
            assert re.search(r"--retry(?:\s|=)\d", line), f"{path.name}:{number} does not retry"
            assert "| sh" not in line, f"{path.name}:{number} pipes a retryable body to sh"


def test_the_macos_signing_step_survives_a_bad_minute_at_apples_timestamp_service() -> None:
    """`codesign` and `productsign` each request a trusted timestamp from Apple, `notarytool`
    uploads, and `stapler` downloads the ticket back. Every one reaches a network service on every
    invocation, and a release that cannot reach it dies with "A timestamp was expected but was not
    found."

    Dropping the timestamp is not an option: it is what keeps the signature verifiable past the
    certificate's expiry, and notarization refuses a build without one. So the retry wraps the call.
    Keychain grants (`security import -T /usr/bin/codesign`) name the tools without invoking them
    and are deliberately not matched here.
    """
    assert (REPO / "packaging" / "retry.sh").is_file(), "the retry helper is missing"

    workflow = (REPO / ".github" / "workflows" / "release-macos.yml").read_text()
    bare = []
    for number, line in enumerate(workflow.splitlines(), 1):
        if "security import" in line or line.lstrip().startswith("#"):
            continue
        if not re.search(r"\b(codesign|productsign|notarytool submit|stapler staple)\b", line):
            continue
        if "retry.sh" not in line:
            bare.append(f"{number}: {line.strip()[:60]}")
    assert not bare, f"reaches Apple without a retry, so one bad minute ends the release: {bare}"

    # The claim above is only worth making if the schedule backs it. Derived from the script and the
    # workflow rather than restated, so widening one without the other cannot pass quietly.
    helper = (REPO / "packaging" / "retry.sh").read_text()
    step = re.search(r"sleep \$\(\(n \* (\d+)\)\)", helper)
    assert step, "retry.sh no longer backs off between attempts"
    seconds = int(step.group(1))

    attempts = [int(n) for n in re.findall(r"retry\.sh (\d+) ", workflow)]
    assert attempts, "nothing in the release goes through the retry helper"
    for count in attempts:
        window = sum(seconds * n for n in range(1, count))
        assert window >= 120, (
            f"{count} attempts {seconds}s apart only covers {window}s; a minute-long outage wins"
        )


def test_every_install_matrix_caller_states_its_cache_ceiling() -> None:
    """The ceiling cannot be measured from inside the job, so the caller has to say it.

    The self-hosted runner reaches its Docker daemon over TCP, so a `df` in the job container
    measures a different filesystem entirely and would do it silently. The default is deliberately
    the small one, because a ceiling ABOVE the disk never prunes at all -- the failure that looks
    like nothing is wrong. Left implicit, a large runner would quietly keep the small default.
    """
    for name in (".forgejo/workflows/install-matrix.yml", ".github/workflows/install-matrix.yml"):
        path = REPO / name
        if not path.is_file():
            continue
        document = yaml.safe_load(path.read_text())
        for job, spec in document["jobs"].items():
            for step in spec.get("steps") or []:
                if "install-matrix-arch.sh" not in str(step.get("run", "")):
                    continue
                ceiling = (step.get("env") or {}).get("CACHE_CEILING_GB")
                assert ceiling is not None, (
                    f"{path.name}:{job} runs the matrix without stating a cache ceiling"
                )
                assert str(ceiling).isdigit(), f"{path.name}:{job} ceiling is not a number"


def test_ci_can_be_redispatched_without_an_unrelated_commit() -> None:
    """Forgejo has no rerun API.

    Without a dispatch trigger, a fault outside this repository - a runner losing the network, a
    hosted action failing to fetch its own manifest - leaves main red and the only way back is an
    unrelated commit, which is a lie in the history about what changed and why.
    """
    document = yaml.safe_load((REPO / ".forgejo" / "workflows" / "ci.yml").read_text())
    # PyYAML resolves a bare `on:` to the boolean True under YAML 1.1.
    triggers = document.get("on") or document.get(True) or {}
    assert "workflow_dispatch" in triggers, (
        f"ci.yml cannot be redispatched, so an infrastructure fault strands main: {sorted(triggers)}"
    )


def test_ci_supersedes_itself_and_publishing_never_does() -> None:
    """The two workflows want opposite concurrency, and getting either backwards is expensive.

    A second push to a branch makes the first CI answer irrelevant, so that run should be cancelled
    rather than left competing for runners. A publish is the reverse: cancelling one midway leaves a
    release half-written across three registries, and a group any wider than the tag lets a later
    tag displace an earlier tag's still-pending publication and leave it assetless.
    """
    def concurrency(name: str) -> dict:
        document = yaml.safe_load((REPO / ".forgejo" / "workflows" / name).read_text())
        value = document.get("concurrency")
        assert isinstance(value, dict), f"{name} declares no workflow-level concurrency: {value!r}"
        return value

    ci = concurrency("ci.yml")
    assert "github.ref" in str(ci["group"]), f"ci.yml does not group per ref: {ci['group']}"
    assert ci.get("cancel-in-progress") is True, "a superseded CI run should not keep a runner"

    publish = concurrency("publish.yml")
    # `github.ref`, not `ref_name`: the short name drops refs/heads and refs/tags alike, so a
    # branch sharing a tag's name shares its group - and publish.yml can be dispatched on one.
    assert re.search(r"github\.ref\s*}}", str(publish["group"])), (
        f"publish.yml groups wider than the exact ref, so one ref can displace another: "
        f"{publish['group']}"
    )
    assert publish.get("cancel-in-progress") is False, (
        "cancelling a publish leaves a release half-written across registries"
    )


def test_dependencies_that_move_together_are_reviewed_together() -> None:
    """The two manylinux builders are one upstream release under two names.

    They move to the same dated tag together, so reviewing them apart shows half the change - and a
    toolchain skew BETWEEN the arches is exactly the risk their hand-review exists to catch. It also
    doubles the rebase churn, since merging either rebases the other open PR and restarts its checks.

    The versioning regex belongs with it: without one, `latest` is offered as an upgrade over a
    dated tag, and the reviewer loses the version they need to judge the bump at all.
    """
    config = json.loads((REPO / ".renovaterc.json").read_text())
    arches = {
        "quay.io/pypa/manylinux_2_28_x86_64",
        "quay.io/pypa/manylinux_2_28_aarch64",
    }
    grouped = [
        rule for rule in config.get("packageRules", [])
        if rule.get("groupName") and arches <= set(rule.get("matchDepNames") or [])
    ]
    assert grouped, "the manylinux arches are not grouped, so they arrive as separate reviews"
    assert len(grouped) == 1, f"more than one rule groups them: {[r['groupName'] for r in grouped]}"
    assert "regex:" in str(grouped[0].get("versioning", "")), (
        "without a dated-tag versioning scheme, `latest` is offered as an upgrade over a dated tag"
    )
    # Grouping alone does not stop a lone arch arriving: Renovate opens a branch as soon as ONE
    # update in the group exists, so whichever arch Quay published first would be reviewed by
    # itself - the exact skew the grouping is for.
    assert grouped[0].get("minimumGroupSize", 1) >= len(arches), (
        f"a branch can open with fewer than both arches: {grouped[0].get('minimumGroupSize')}"
    )

    # And the group size still only COUNTS updates; it does not compare their targets. If the pins
    # already lag a release and Quay publishes the next tag for one arch first, both arches have an
    # update and the branch opens with mismatched targets. Renovate cannot express "same tag", so
    # the pins themselves are what proves it: whatever lands, the two must agree.
    tags = re.findall(r"manylinux_2_28_(?:x86_64|aarch64):([0-9.]+-\d+)@sha256:", (REPO / "packaging" / "release-pins.env").read_text())
    assert len(tags) == 2, f"expected both manylinux pins, found {len(tags)}"
    assert tags[0] == tags[1], f"the two arches are pinned to different builder releases: {tags}"

def test_homebrew_bottles_come_from_the_mirror_where_it_is_reachable() -> None:
    """Homebrew fetches bottles with its own HTTPS client, so neither dockerd's registry mirror nor
    BuildKit's applies to them - and they are the bulk of what these jobs download.

    It has to be ARTIFACT_DOMAIN. `HOMEBREW_BOTTLE_DOMAIN` makes Homebrew request a legacy flat file
    (`.../oniguruma-6.9.10.x86_64_linux.bottle.tar.gz`) that an OCI registry does not serve, so every
    bottle 404s and falls back upstream: configured, and mirroring nothing. ARTIFACT_DOMAIN rewrites
    only the scheme and host and keeps `/v2/homebrew/core/...`, which is why the registry serves that
    namespace at its root rather than under the usual per-upstream one.

    Self-hosted only. The hosted runners are not on that network, and pointing them at it buys a
    timeout before the fallback rather than a cache hit.
    """
    for name in ("packaging/install-smoke.Dockerfile", "packaging/homebrew-smoke.Dockerfile"):
        text = (REPO / name).read_text()
        assert "ARG BREW_MIRROR=" in text, f"{name} cannot receive a mirror"
        # Setting ARTIFACT_DOMAIN makes Homebrew drop the anonymous `Bearer QQ==` it would
        # otherwise send to ghcr.io, so a bottle the mirror cannot serve falls back and gets a 401
        # instead. That is what reverted this the first time, and nothing else in the file says so.
        assert "HOMEBREW_DOCKER_REGISTRY_TOKEN" in text, (
            f"{name} sets a mirror without restoring the anonymous ghcr credential, so any mirror "
            "miss 401s on fallback instead of downloading the bottle"
        )
        assert 'export HOMEBREW_ARTIFACT_DOMAIN="$BREW_MIRROR"' in text, (
            f"{name} must export ARTIFACT_DOMAIN when a mirror was given"
        )
        assert '[ -z "$BREW_MIRROR" ] ||' in text, (
            f"{name} must export nothing when no mirror was given"
        )
        # A pull-through registry sends nothing while it buffers a blob it has never seen, and
        # Homebrew's default three tries expire in about seven seconds. Without this the FIRST job
        # to want a new bottle version fails, which is every version bump.
        assert "HOMEBREW_CURL_RETRIES" in text, (
            f"{name} keeps the default retry count, which no cold fetch survives"
        )
        assert "HOMEBREW_BOTTLE_DOMAIN" not in text, (
            f"{name} uses BOTTLE_DOMAIN, which an OCI registry cannot serve"
        )

    def mirrored(path: Path) -> bool:
        for job in yaml.safe_load(path.read_text())["jobs"].values():
            for step in job.get("steps") or []:
                if "BREW_MIRROR" in (step.get("env") or {}):
                    return True
                if "BREW_MIRROR=" in str(step.get("run", "")):
                    return True
        return False

    forgejo = REPO / ".forgejo" / "workflows"
    assert mirrored(forgejo / "install-matrix.yml"), "the self-hosted matrix does not mirror bottles"

    # Every self-hosted build of the formula smoke, found rather than listed: the release path
    # builds it a second time, and a fixed list would have passed while that one bypassed the
    # mirror to pull the same rust and llvm bottles again.
    for path in sorted(forgejo.glob("*.yml")):
        document = yaml.safe_load(path.read_text())
        for job, spec in (document.get("jobs") or {}).items():
            for step in spec.get("steps") or []:
                if "homebrew-smoke.Dockerfile" not in str(step.get("run", "")):
                    continue
                assert "BREW_MIRROR=" in str(step["run"]), (
                    f"{path.name}:{job} builds the formula smoke without the mirror"
                )
    assert not mirrored(REPO / ".github" / "workflows" / "install-matrix.yml"), (
        "a hosted runner was pointed at a mirror it cannot reach"
    )


def test_the_formula_is_built_on_every_macos_lane_the_library_is() -> None:
    """A formula proven on current arm64 only leaves the two axes that differ to a tag.

    Both formulae compile native code on the installing machine - a Rust extension here, a C
    resource in the sibling - so a break can be specific to Intel or to the macOS floor. The
    bottle build covers those lanes but runs at tag time, and a tag is immutable by the time it
    reports. Whatever set `ci-macos.yml` holds the library to, the formula is held to as well.
    """
    def lanes(name: str) -> set[str]:
        document = yaml.safe_load((REPO / ".github" / "workflows" / name).read_text())
        job = next(iter(document["jobs"].values()))
        include = (((job.get("strategy") or {}).get("matrix") or {}).get("include")) or []
        return {entry["os"] for entry in include} or {job["runs-on"]}

    library, formula = lanes("ci-macos.yml"), lanes("formula-macos.yml")
    assert formula == library, (
        f"the formula is built on {sorted(formula)} while the library is tested on "
        f"{sorted(library)}; the difference is where a break reaches a tag unseen"
    )

def test_ci_is_not_green_until_native_macos_agrees() -> None:
    """CI ran the Linux suites and called that a verdict, while macOS ran only on the mirror.

    A pull request could therefore read green with its macOS matrix red, and nothing noticed until
    the release gate refused to tag - at which point the bad commit was already on main. The gate
    waits by EXACT head SHA so a newer green branch run cannot qualify an older revision.

    Three things this pins beyond its existence, each of which would break something real:

    - It must not run for a TAG. A prerelease stamps a commit that is pushed only as a tag, and the
      mirrored workflow runs on branch pushes, so no run can ever exist for that sha - the gate
      would poll to its timeout and fail every prerelease. Either this repository's CI does not
      trigger on tags at all, or the gate excludes them.
    - It must hold no WRITE credential. Reading public run conclusions needs a scopeless token;
      going without one shares a 60-request hour with everything else leaving this network,
      including the sibling's copy of this gate, which turns a fine commit into a timeout.
    - Checkout must not persist credentials, or the repository token sits in git config while a
      script from a PR-controlled ref runs beside it.
    """
    text = (REPO / ".forgejo" / "workflows" / "ci.yml").read_text()
    document = yaml.safe_load(text)
    # Bounded at the next top-level job. A tail slice would read whatever is appended after this
    # one as part of it, which both invents failures and hides real ones.
    start = text.index("\n  macos:\n") + 1
    rest = text[start + 1 :]
    end = re.search(r"^  [a-z][a-z0-9-]*:$", rest, re.MULTILINE)
    job = rest[: end.start()] if end else rest

    assert "check-mirror-ci.sh" in job, "the macos gate does not consult the mirror"
    assert ".github/workflows/ci-macos.yml" in job, "the gate names no macOS workflow to wait on"
    assert '["pull_request"]["head"]["sha"]' in job, (
        "the gate does not resolve the PR head, so it can qualify the wrong commit"
    )
    assert "needs:" in job, "the macos gate does not run after the suites it should follow"
    assert "persist-credentials: false" in job, (
        "the gate's checkout leaves the repository token in git config"
    )

    # Case-insensitive: secret expressions are not required to be shouted, and a
    # `secrets.write_pat` that this missed would be a silently unguarded credential.
    for secret in re.findall(r"secrets\.([A-Za-z_0-9]+)", job):
        assert secret.upper() == "GH_REPO_READ_PAT", (
            f"the macos gate takes {secret}; it runs on every push and needs only to READ "
            "public run conclusions"
        )

    triggers = document.get("on") or document.get(True) or {}
    tagged = "tags" in (triggers.get("push") or {})
    if tagged:
        assert "refs/tags/" in str(document["jobs"]["macos"].get("if", "")), (
            "CI runs on tags and the macOS gate does not exclude them, so every prerelease will "
            "wait for a mirrored run that cannot exist and fail"
        )


def test_the_bottle_wait_outlasts_a_slow_publish() -> None:
    """`build-bottles.sh` waits for publish.yml's first tap pass, and the budget is the whole
    protection.

    The two halves of that handshake run on different forges with no shared clock, so the only
    thing keeping them together is that this wait outlasts however long publish takes to write the
    formula. Publish has been measured reaching that point anywhere between 17 and 37 minutes, and
    a budget inside that spread silently costs a release its bottles and then the install matrix
    that waits on them.

    Widening is close to free because the loop breaks the moment the formula appears, so this is a
    failure bound rather than a delay. Hence a floor of 60 minutes: clear of the top of the
    observed spread, not the middle of it.
    """
    text = (REPO / "packaging" / "build-bottles.sh").read_text()
    match = re.search(r"for _ in \$\(seq 1 (\d+)\); do", text)
    assert match, "the tap wait loop is not recognisable; did its shape change?"
    sleep = re.search(r"\n\s*sleep (\d+)\n\s*done", text)
    assert sleep, "the tap wait has no recognisable sleep"
    seconds = int(match.group(1)) * int(sleep.group(1))

    assert seconds >= 3600, (
        f"the tap wait is {seconds // 60} minutes; publish has been measured at 37, and a "
        "budget under 60 loses the release's bottles to a slow publish"
    )


def test_the_install_wait_outlasts_the_bottle_wait_it_depends_on() -> None:
    """The install matrix waits for a release to be installable, and a bottle is part of that.

    So this wait sits DOWNSTREAM of the one above: bottles cannot appear until build-bottles.sh
    stops waiting for the tap and then spends about half an hour building. Budget the two
    independently and the downstream one can expire while the thing it waits for is still legitimately
    coming — which reports a healthy release as a failed one, on both forges at once, because they
    share this script.

    Derived from the upstream budget rather than written as a number, so raising one and forgetting
    the other cannot happen quietly.
    """
    bottles = (REPO / "packaging" / "build-bottles.sh").read_text()
    up_n = re.search(r"for _ in \$\(seq 1 (\d+)\); do", bottles)
    up_s = re.search(r"\n\s*sleep (\d+)\n\s*done", bottles)
    assert up_n and up_s, "the tap wait is not recognisable; did its shape change?"
    upstream = int(up_n.group(1)) * int(up_s.group(1))

    wait = (REPO / "packaging" / "wait-for-release.sh").read_text()
    dn_n = re.search(r'ATTEMPTS="\$\{WAIT_ATTEMPTS:-(\d+)\}"', wait)
    dn_s = re.search(r'INTERVAL="\$\{WAIT_INTERVAL:-(\d+)\}"', wait)
    assert dn_n and dn_s, "the install wait no longer declares a default budget"
    downstream = int(dn_n.group(1)) * int(dn_s.group(1))

    # The build itself, on top of however long the upstream wait is allowed to run.
    assert downstream >= upstream + 1800, (
        f"the install wait is {downstream // 60} minutes but the bottle wait it depends on may "
        f"itself run {upstream // 60}; leave room for the build that follows it"
    )


def test_every_apt_base_sets_the_retry_policy() -> None:
    """A mirror that drops a connection is not this project failing, and apt's default is to treat
    it as fatal anyway.

    Derived stages inherit the policy file from their base, so the only way to lose it is to add a
    NEW base for a new distro and not think about it — which is exactly the case a reader of the
    comment beside it would assume was covered. Checked per `apt-get update`, because that is the
    call that fetches and so the one that can be killed by someone else's network.
    """
    text = (REPO / "packaging" / "install-smoke.Dockerfile").read_text(encoding="utf-8")
    lines = text.splitlines()
    # A negative is only worth asserting once the search that produced it is known to find
    # anything at all: a refactor that renames these calls would otherwise leave nothing to flag
    # and this test would pass by looking at an empty set.
    updates = [i + 1 for i, line in enumerate(lines) if "apt-get update" in line]
    assert len(updates) >= 4, (
        f"only {len(updates)} apt-get update sites found; the scan no longer matches what it is "
        "meant to guard, so finding none unguarded proves nothing"
    )
    unguarded = [
        i + 1
        for i, line in enumerate(lines)
        if "apt-get update" in line
        and "99retries" not in line
        and (i == 0 or "99retries" not in lines[i - 1])
    ]
    assert not unguarded, (
        f"apt-get update without a retry policy at line(s) {unguarded}; a mirror hiccup there "
        "reddens an install leg for a fault that is not ours"
    )


def test_the_install_matrix_is_reachable_for_every_release() -> None:
    """The Linux matrix is dispatched by publish.yml, and nothing else starts it.

    It used to trigger on the tag push, which is the same instant publish starts, so its wait job
    held one of this runner's few slots for its whole budget polling for artifacts the publish it
    was starving had not built yet. Moving it behind publish removes that, but replaces a trigger
    that cannot silently disappear with a step that can — and a release whose matrix never ran is
    not obviously different from one whose matrix passed.

    So both halves are pinned here: the matrix must NOT race the publish, and the publish must
    still hand it over, after everything the matrix installs from exists.
    """
    # Both halves, because they are one matrix split by hardware rather than two kinds of test —
    # and a mechanism that differs per forge is how the two drift apart.
    for forge in (".forgejo", ".github"):
        matrix = yaml.safe_load(
            (REPO / forge / "workflows" / "install-matrix.yml").read_text(encoding="utf-8")
        )
        # YAML 1.1 reads a bare `on` as the boolean true, which is why this is not matrix["on"].
        triggers = matrix.get(True, matrix.get("on"))
        assert "workflow_dispatch" in triggers, f"{forge} matrix can no longer be dispatched at all"
        assert "push" not in triggers, (
            f"{forge} matrix triggers on push again — it starts before the release it installs exists"
        )

    publish = yaml.safe_load(
        (REPO / ".forgejo" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    )
    handoff = [
        job
        for job in publish["jobs"].values()
        if "install-matrix.yml/dispatches" in yaml.dump(job)
    ]
    assert len(handoff) == 1, (
        "publish.yml no longer hands the release to the install matrix; nothing else will, so "
        "the release would go untested until the promotion gate refused it"
    )
    assert "homebrew-bottles" in handoff[0]["needs"], (
        f"the handoff runs after {handoff[0]['needs']}, which can precede the bottle block"
    )
    # A producer can fail its upload and reconcile can heal the release afterwards. Under the
    # default needs-semantics that healed, COMPLETE release would have its handoff skipped, which
    # is the no-matrix-at-all state this whole job exists to avoid.
    assert "reconcile" in handoff[0]["needs"], "the handoff can precede the healing it depends on"
    dispatched = yaml.dump(handoff[0]).count("install-matrix.yml/dispatches")
    assert dispatched == 2, (
        f"the handoff dispatches {dispatched} matrix half/halves; both forges are one matrix and "
        "starting only one leaves the other never running at all"
    )
    assert "!cancelled()" in str(handoff[0].get("if", "")), (
        "the handoff is gated on its producers succeeding, so a healed release gets no matrix"
    )


def test_both_package_formats_are_gated_before_publish() -> None:
    """nfpm builds the .deb and the .rpm in separate passes, which can fail independently.

    Smoking only one of them publishes the other on the strength of a different artifact — the
    failure is invisible until a user installs it, because every later check reads the published
    package rather than the built one. Pinned per format rather than by counting calls, so dropping
    one and duplicating the other cannot pass.
    """
    script = (REPO / "packaging" / "build-linux-arch.sh").read_text(encoding="utf-8")
    smoked = set(re.findall(r"^smoke_pkg (deb|rpm) ", script, re.M))
    assert smoked == {"deb", "rpm"}, f"pre-publish smoke covers {sorted(smoked) or 'nothing'}"
    for name in ("package-smoke.Dockerfile", "package-smoke-rpm.Dockerfile"):
        assert (REPO / "packaging" / name).is_file(), f"{name} is referenced but missing"


def test_every_distro_rung_belongs_to_its_group() -> None:
    """Each rung is annotated `-compat` or `-current`, and the groups match on that suffix.

    The suffix is therefore load-bearing rather than decorative: a new distro pinned as
    `fedora-45` instead of `fedora-45-current` still builds, still gets bumped, and silently
    escapes the review its siblings share. Nothing else would notice, so this does.

    Scanned over TRACKED files rather than a walk: the working tree also holds virtualenvs and
    scratch files, and an annotation-shaped string in local debris would fail this on one checkout
    and pass in CI. Tracked also picks up release-pins.env, which the docker manager reads too.
    """
    config = json.loads((REPO / ".renovaterc.json").read_text(encoding="utf-8"))
    grouped = {
        name
        for rule in config["packageRules"]
        if rule.get("groupName", "").startswith("distro ")
        for name in rule["matchDepNames"]
    }
    assert grouped == {"/-current$/", "/-compat$/"}, (
        f"the distro groups no longer match by suffix: {sorted(grouped)}"
    )

    annotated = {
        name
        for _, text in TRACKED
        for name in re.findall(
            r"depName=((?:debian|ubuntu|fedora|rocky|opensuse)[a-z0-9.-]*)", text
        )
    }
    assert annotated, "no distro annotations found — has the naming changed?"
    stray = {n for n in annotated if not n.endswith(("-compat", "-current"))}
    assert not stray, f"distro rungs outside both groups: {sorted(stray)}"


def test_every_supported_version_the_readme_promises_is_install_tested() -> None:
    """The README's table is a promise: "tested on every minimum version below".

    Nothing enforced that, and three claims had already drifted from reality — a promised Fedora
    floor the shipped .rpm was never installed on, an openSUSE minimum stated above the version
    actually tested, and a whole matrix missing from one of the two projects. Each was invisible
    because the table and the Dockerfile are read by different people at different times.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    pins = (REPO / "packaging" / "install-smoke.Dockerfile").read_text(encoding="utf-8")

    rows = re.findall(r"^\| (Debian[^|]*|Ubuntu|Fedora|RHEL-compatible|openSUSE Leap) \|([^|]*)\|([^|]*)\|$",
                      readme, re.M)
    assert rows, "the support matrix is gone from the README"

    images = {
        "Debian": "debian:{v}-slim",
        "Ubuntu": "ubuntu:{v}",
        "Fedora": "fedora:{v}",
        "RHEL-compatible": "rockylinux/rockylinux:{v}",
        "openSUSE Leap": "opensuse/leap:{v}",
    }
    # Resolved through the stage graph, not by searching the file: a pinned base with no channel
    # installing on it is exactly the Fedora gap this exists to catch, and `pin in text` cannot
    # tell those apart.
    # {stage: whatever it derives from}, built in that direction on purpose: several stages share
    # one base, so a {base: stage} map silently keeps only the last and loses half the graph.
    parent = {stage: base for base, stage in re.findall(r"^FROM (\S+) AS ([a-z0-9-]+)$", pins, re.M)}
    channels = set(
        re.search(r"^CHANNELS=\(\n(.*?)^\)$", (REPO / "packaging" / "install-matrix-arch.sh").read_text(encoding="utf-8"), re.M | re.S)
        .group(1)
        .split()
    )
    exercised = set()
    for channel in channels:
        stage, seen = channel, set()
        while stage in parent and stage not in seen:
            seen.add(stage)
            base = parent[stage]
            if base in parent:      # another stage — keep walking down to the real image
                stage = base
                continue
            exercised.add(base.split("@")[0])
            break
    exercised = " ".join(sorted(exercised))

    # The matrix builds `<channel>-result`, not `<channel>`, and BuildKit follows the COPY rather
    # than the name. A result stage copying from the wrong place would execute a different graph
    # while every name-based check above still agreed.
    for channel in channels:
        copied = re.search(
            r"^FROM scratch AS " + re.escape(channel) + r"-result\nCOPY --from=([a-z0-9-]+) ",
            pins,
            re.M,
        )
        assert copied, f"{channel}-result is missing or does not copy from a stage"
        assert copied.group(1) == channel, (
            f"{channel}-result copies from {copied.group(1)}, so building it exercises that stage "
            f"instead of {channel}"
        )

    checked = 0
    for label, minimum, also in rows:
        key = next((k for k in images if label.startswith(k)), None)
        assert key, f"unmapped support-matrix row: {label}"
        for cell in (minimum, also):
            for version in re.findall(r"\b(\d+\.\d+|\d+)\b", cell):
                if key == "openSUSE Leap" and "." not in version:
                    continue  # Leap versions are always X.Y; a bare number here is prose
                pin = images[key].format(v=version)
                assert pin in exercised, (
                    f"README promises {label} {version} but no install channel puts the shipped "
                    f"package on {pin}"
                )
                checked += 1
    assert checked >= 8, f"only {checked} promised versions checked — the parse has gone stale"

    # Two rows name a system no lane installs on: RHEL has no public image to install into, and
    # Raspberry Pi OS is Debian underneath. Both are honest only while the README says so, and the
    # version parse above cannot notice their absence — "RHEL" and "Bookworm" carry no number.
    for system, phrase in (
        ("Raspberry Pi OS", "Raspberry Pi OS** is not tested as its own image"),
        ("RHEL", "**RHEL** is not tested directly"),
    ):
        assert phrase in readme, (
            f"the README no longer says {system} is covered by inheritance rather than its own "
            "lane, which turns it back into a promise nothing tests"
        )


def test_each_matrix_half_runs_every_shard_it_declares() -> None:
    """The shard list and the count handed to the script have to agree, in both directions.

    Declare four shards while passing two and the extra jobs fail loudly on a range check, which is
    survivable. The other way round is the dangerous one: pass four while declaring two and half the
    channels are simply never selected, the two shards that do run pass, and the matrix reports the
    architecture green having installed half of what it publishes. Nothing else compares these two
    numbers — they live in different parts of the same file.
    """
    for forge in (".forgejo", ".github"):
        spec = yaml.safe_load(
            (REPO / forge / "workflows" / "install-matrix.yml").read_text(encoding="utf-8")
        )
        job = next(
            name for name, body in spec["jobs"].items()
            if "install-matrix-arch" in yaml.dump(body)
        )
        declared = spec["jobs"][job]["strategy"]["matrix"]["shard"]
        run = next(
            step["run"] for step in spec["jobs"][job]["steps"]
            if "install-matrix-arch" in step.get("run", "")
        )
        passed = int(run.strip().split()[-1])
        assert declared == list(range(passed)), (
            f"{forge}: the matrix runs shards {declared} but tells the script there are {passed}; "
            "a shard the script never selects is a channel nobody installs"
        )
