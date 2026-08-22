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


# --- workflow YAML that a forge will actually accept ------------------------------
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
    assert config["postUpgradeTasks"]["fileFilters"] == ["packaging/release-pins.env"], (
        "refresh-pins.sh rewrites release-pins.env, so that is the file Renovate must keep"
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
