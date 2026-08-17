"""Repository-wide invariants that no other check enforces.

Each of these found a real defect during the work that added them, and each was
only ever verified by someone remembering to look. They are cheap, they need
neither Home Assistant nor a broker, and they fail on the file that drifted.
"""

from __future__ import annotations

import json
import re
import subprocess
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
    }
)
#: Every network name the repository is allowed to use as an example.
EXAMPLE_NETWORKS = frozenset(
    {
        "", "MyIoT", "HomeNet", "Guest", "IoT", "home", "hidden",
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
