"""Tests for the per-machine robot profile store."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from whiskerless import robot_profiles as robot_profiles_module
from whiskerless.exceptions import RobotProfileError
from whiskerless.robot_profiles import (
    HOME_ENV,
    AuthMode,
    Broker,
    RobotProfile,
    RobotProfileStore,
    Serial,
)

CA = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"


@pytest.fixture
def store(tmp_path: Path) -> RobotProfileStore:
    return RobotProfileStore(tmp_path / "home")


def make(serial: str = "LR4C123456", **kwargs: object) -> RobotProfile:
    return RobotProfile(serial=Serial(serial), **kwargs)  # type: ignore[arg-type]


# --- Serial -------------------------------------------------------------------
def test_serial_normalizes_case_and_whitespace() -> None:
    assert Serial("  lr4c123456 ").value == "LR4C123456"


def test_serial_defaults_to_unverified() -> None:
    assert Serial("LR4C123456").verified is False


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "ab",  # too short
        "../escape",
        "../../etc/passwd",
        "with/slash",
        "with\\backslash",
        "has.dot",
        "has space",
        "-leading-dash",
        "a" * 65,
    ],
)
def test_serial_rejects_anything_unusable_as_a_directory_name(bad: str) -> None:
    with pytest.raises(RobotProfileError, match="not a usable serial"):
        Serial(bad)


def test_serial_traversal_cannot_reach_outside_the_store(tmp_path: Path) -> None:
    """The serial becomes a path segment, so this is a containment test, not style."""
    store = RobotProfileStore(tmp_path / "home")
    with pytest.raises(RobotProfileError):
        store.save(RobotProfile(serial=Serial("../escape"), ))
    assert not (tmp_path / "escape").exists()


# --- RobotProfile -------------------------------------------------------------
def test_display_name_prefers_the_chosen_name() -> None:
    assert make(name="Upstairs").display_name == "Upstairs"


def test_display_name_falls_back_to_the_serial() -> None:
    assert make().display_name == "LR4C123456"


# --- save / load --------------------------------------------------------------
def test_save_then_load_round_trips(store: RobotProfileStore) -> None:
    original = make(name="Upstairs")
    store.save(original)
    assert store.load("LR4C123456") == original


# --- format version and migration ---------------------------------------------
def _stored(store: RobotProfileStore, serial: str = "LR4C123456") -> Path:
    return store.robots_dir / serial / "profile.json"


def test_load_accepts_a_differently_cased_serial(store: RobotProfileStore) -> None:
    store.save(make())
    assert store.load("lr4c123456").serial.value == "LR4C123456"


def test_save_preserves_serial_verification(store: RobotProfileStore) -> None:
    store.save(RobotProfile(serial=Serial("LR4C123456", verified=True), ))
    assert store.load("LR4C123456").serial.verified is True


def test_load_is_helpful_when_the_robot_is_unknown(store: RobotProfileStore) -> None:
    with pytest.raises(RobotProfileError, match="run `whiskerless provision` first"):
        store.load("LR4C999999")


def test_load_rejects_a_json_document_that_is_not_an_object(store: RobotProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(RobotProfileError, match="not a JSON object"):
        store.load("LR4C123456")


def test_defaults_apply_when_optional_keys_are_absent(store: RobotProfileStore) -> None:
    directory = store.robots_dir / "LR4C123456"
    directory.mkdir(parents=True)
    (directory / "profile.json").write_text(json.dumps({"host": "h"}), encoding="utf-8")
    loaded = store.load("LR4C123456")
    assert loaded.name == ""


def test_the_directory_name_wins_over_a_hand_edited_serial(store: RobotProfileStore) -> None:
    store.save(make())
    path = store.robots_dir / "LR4C123456" / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["serial"] = "LR4C000000"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load("LR4C123456").serial.value == "LR4C123456"


def test_saving_twice_replaces_rather_than_appends(store: RobotProfileStore) -> None:
    store.save(make())
    store.save(make(name="Renamed"))
    assert store.load("LR4C123456").name == "Renamed"
    assert len(store.list_robot_profiles()) == 1


# --- permissions --------------------------------------------------------------
def test_stored_files_are_owner_only(store: RobotProfileStore) -> None:
    """These hold broker credentials in the clear."""
    store.save(make())
    directory = store.robots_dir / "LR4C123456"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for name in ("profile.json",):
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600


def test_the_store_directories_themselves_are_owner_only(store: RobotProfileStore) -> None:
    """A listable robots/ would advertise every serial in the house."""
    store.save(make())
    for directory in (store.root, store.robots_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_no_temporary_files_survive_a_save(store: RobotProfileStore) -> None:
    store.save(make())
    leftovers = [p.name for p in (store.robots_dir / "LR4C123456").iterdir()]
    assert sorted(leftovers) == ["profile.json"]


# --- listing ------------------------------------------------------------------
def test_listing_an_empty_store_is_empty_not_an_error(store: RobotProfileStore) -> None:
    assert store.list_robot_profiles() == ()


def test_listing_is_sorted_by_serial(store: RobotProfileStore) -> None:
    store.save(make("LR4C999999"))
    store.save(make("LR4C111111"))
    assert [p.serial.value for p in store.list_robot_profiles()] == ["LR4C111111", "LR4C999999"]


def test_one_corrupt_profile_does_not_hide_the_others(store: RobotProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    (store.robots_dir / "LR4C999999" / "profile.json").write_text("{bad", encoding="utf-8")
    assert [p.serial.value for p in store.list_robot_profiles()] == ["LR4C111111"]


def test_listing_ignores_stray_files_and_dot_directories(store: RobotProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "README").write_text("hi", encoding="utf-8")
    (store.robots_dir / ".hidden").mkdir()
    assert [p.serial.value for p in store.list_robot_profiles()] == ["LR4C123456"]


# --- resolve ------------------------------------------------------------------
def test_resolve_returns_the_named_robot(store: RobotProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    assert store.resolve("LR4C999999").serial.value == "LR4C999999"


def test_resolve_returns_the_only_robot_when_there_is_one(store: RobotProfileStore) -> None:
    store.save(make())
    assert store.resolve().serial.value == "LR4C123456"


def test_resolve_says_to_provision_when_nothing_is_stored(store: RobotProfileStore) -> None:
    with pytest.raises(RobotProfileError, match="no robots are set up"):
        store.resolve()


def test_resolve_lists_the_candidates_when_ambiguous(store: RobotProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    with pytest.raises(RobotProfileError, match="LR4C111111, LR4C999999"):
        store.resolve()


def test_resolve_prefers_the_default_over_ambiguity(store: RobotProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    store.set_default("LR4C999999")
    assert store.resolve().serial.value == "LR4C999999"


def test_an_explicit_robot_still_beats_the_default(store: RobotProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    store.set_default("LR4C999999")
    assert store.resolve("LR4C111111").serial.value == "LR4C111111"


# --- default marker -----------------------------------------------------------
def test_there_is_no_default_until_one_is_set(store: RobotProfileStore) -> None:
    assert store.get_default() is None


def test_set_default_rejects_an_unknown_robot(store: RobotProfileStore) -> None:
    with pytest.raises(RobotProfileError, match="no saved profile"):
        store.set_default("LR4C999999")


def test_a_blank_default_marker_reads_as_unset(store: RobotProfileStore) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "default").write_text("  \n", encoding="utf-8")
    assert store.get_default() is None


def test_an_unreadable_default_marker_reads_as_unset(store: RobotProfileStore) -> None:
    (store.root / "default").mkdir(parents=True)  # a directory, not a file
    assert store.get_default() is None


# --- forget -------------------------------------------------------------------
def test_forget_removes_the_profile(store: RobotProfileStore) -> None:
    store.save(make())
    store.forget("LR4C123456")
    assert store.list_robot_profiles() == ()
    assert not (store.robots_dir / "LR4C123456").exists()


def test_forget_clears_a_default_pointing_at_it(store: RobotProfileStore) -> None:
    store.save(make())
    store.set_default("LR4C123456")
    store.forget("LR4C123456")
    assert store.get_default() is None


def test_forget_leaves_another_robots_default_alone(store: RobotProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    store.set_default("LR4C111111")
    store.forget("LR4C999999")
    assert store.get_default() == "LR4C111111"


def test_forget_rejects_an_unknown_robot(store: RobotProfileStore) -> None:
    with pytest.raises(RobotProfileError, match="no saved profile"):
        store.forget("LR4C999999")


def test_forget_keeps_a_directory_holding_files_it_did_not_write(store: RobotProfileStore) -> None:
    store.save(make())
    stray = store.robots_dir / "LR4C123456" / "notes.txt"
    stray.write_text("mine", encoding="utf-8")
    store.forget("LR4C123456")
    assert stray.exists()


# --- from_env -----------------------------------------------------------------
def test_from_env_falls_back_to_a_visible_directory_in_home(tmp_path: Path) -> None:
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.root == tmp_path / "whiskerless"


def test_from_env_uses_the_real_home_when_the_variable_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert RobotProfileStore.from_env({}).root == tmp_path / "whiskerless"


def test_from_env_reads_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "from-environ"))
    assert RobotProfileStore.from_env().root == tmp_path / "from-environ"


# --- restored: store behaviour unrelated to the broker move --------------------
def test_load_reports_corrupt_json(store: RobotProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RobotProfileError, match="could not read the profile"):
        store.load("LR4C123456")




def test_load_reports_an_unreadable_profile(store: RobotProfileStore) -> None:
    directory = store.robots_dir / "LR4C123456"
    (directory / "profile.json").mkdir(parents=True)
    with pytest.raises(RobotProfileError, match="could not read the profile"):
        store.load("LR4C123456")




def test_a_skipped_profile_is_reported_as_damaged(store: RobotProfileStore) -> None:
    """An entry a user cannot see is one they can never repair or forget."""
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    (store.robots_dir / "LR4C999999" / "profile.json").write_text("{bad", encoding="utf-8")
    ((name, why),) = store.damaged()
    assert name == "LR4C999999"
    assert "could not read" in why




def test_a_healthy_store_reports_no_damage(store: RobotProfileStore) -> None:
    store.save(make())
    assert store.damaged() == ()




def test_an_empty_store_reports_no_damage(store: RobotProfileStore) -> None:
    assert store.damaged() == ()




def test_from_env_honours_the_override(tmp_path: Path) -> None:
    store = RobotProfileStore.from_env({HOME_ENV: str(tmp_path / "elsewhere")})
    assert store.root == tmp_path / "elsewhere"




def test_from_env_expands_a_tilde_in_the_override(tmp_path: Path) -> None:
    store = RobotProfileStore.from_env({HOME_ENV: "~/custom", "HOME": str(tmp_path)})
    assert store.root == tmp_path / "custom"




def test_from_env_accepts_a_bare_tilde_override(tmp_path: Path) -> None:
    store = RobotProfileStore.from_env({HOME_ENV: "~", "HOME": str(tmp_path)})
    assert store.root == tmp_path




# --- the one broker -----------------------------------------------------------
def test_a_broker_round_trips(store: RobotProfileStore) -> None:
    store.save_broker(Broker(host="192.0.2.10"))
    assert store.load_broker().host == "192.0.2.10"


def test_a_broker_is_a_host_and_how_this_store_authenticates(store: RobotProfileStore) -> None:
    """Nothing else. A port or a hostname-verification switch would be a way to
    point the CLI where the robot cannot follow: the port is a compile-time
    constant in the firmware and hostname verification is what the robot does."""
    store.save_broker(Broker(host="192.0.2.10"))
    assert json.loads(store.broker_path.read_text(encoding="utf-8")) == {
        "host": "192.0.2.10",
        "auth": "mutual",
    }
    settings = store.load_broker().settings()
    assert (settings.port, settings.verify_hostname) == (8883, True)


def test_a_machine_with_no_broker_says_how_to_get_one(store: RobotProfileStore) -> None:
    with pytest.raises(RobotProfileError, match="run `whiskerless provision`"):
        store.load_broker()


@pytest.mark.parametrize("body", ["[]", "null", '"a string"'])
def test_broker_json_that_is_not_an_object_is_damage(store: RobotProfileStore, body: str) -> None:
    """Valid JSON of the wrong shape would otherwise raise AttributeError and
    bypass the CLI's one-line damaged-configuration handling."""
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text(body, encoding="utf-8")
    with pytest.raises(RobotProfileError, match="not a JSON object"):
        store.load_broker()


def test_a_broker_file_that_is_not_json_is_damage(store: RobotProfileStore) -> None:
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RobotProfileError, match="could not read"):
        store.load_broker()


@pytest.mark.parametrize("host", ["", 42, None])
def test_a_broker_without_a_usable_host_is_damage(store: RobotProfileStore, host: object) -> None:
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text(json.dumps({"host": host}), encoding="utf-8")
    with pytest.raises(RobotProfileError, match="no broker host"):
        store.load_broker()


def test_a_store_written_before_the_port_was_dropped_still_opens(store: RobotProfileStore) -> None:
    """Refusing to open a store over a key that no longer means anything would
    strand the one thing in it that cannot be regenerated — the CA key."""
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text(
        json.dumps({"host": "192.0.2.10", "port": 1884, "verify_hostname": False}),
        encoding="utf-8",
    )
    settings = store.load_broker().settings()
    assert (settings.host, settings.port, settings.verify_hostname) == ("192.0.2.10", 8883, True)


def test_reopening_such_a_store_rewrites_it_host_only(store: RobotProfileStore) -> None:
    store.broker_path.parent.mkdir(parents=True, exist_ok=True)
    store.broker_path.write_text(
        json.dumps({"host": "192.0.2.10", "port": 1884}), encoding="utf-8"
    )
    store.save_broker(store.load_broker())
    assert json.loads(store.broker_path.read_text(encoding="utf-8")) == {
        "host": "192.0.2.10",
        "auth": "mutual",
    }, "a store predating the field is a store whose release always signed"


def test_settings_carry_the_ca_and_this_machines_identity(store: RobotProfileStore) -> None:
    """One broker, one CA, one client certificate — none of it per-robot."""
    from whiskerless import pki

    store.save_broker(Broker(host="192.0.2.10"))
    store.save_ca(pki.generate_ca())
    store.client_identity()
    settings = store.settings(client_id="tool")
    assert settings.host == "192.0.2.10"
    assert settings.ca_cert_data == store.ca_path.read_text()
    assert settings.client_cert_data and settings.client_key_data
    assert settings.client_id == "tool", "never defaulted to a serial the robot is using"


def test_settings_without_a_ca_or_identity_still_describe_the_broker(
    store: RobotProfileStore,
) -> None:
    """The anonymous-listener setup: no CA key, no client certificate, still works."""
    store.save_broker(Broker(host="192.0.2.10"))
    settings = store.settings()
    assert settings.host == "192.0.2.10"
    assert settings.ca_cert_data is None
    assert settings.client_cert_data is None


def test_this_machines_identity_is_minted_from_the_ca_once(store: RobotProfileStore) -> None:
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    assert not store.has_client()
    first = store.client_identity()
    assert store.has_client()
    assert store.client_identity().cert_pem == first.cert_pem


def test_a_hidden_legacy_store_is_moved_rather_than_copied(tmp_path: Path) -> None:
    """Two directories that both look like the store is where somebody edits the
    wrong one."""
    from whiskerless.robot_profiles import DEFAULT_SUBDIR, LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR
    RobotProfileStore(legacy).save(make(serial="LR4C111111"))
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.root == tmp_path / DEFAULT_SUBDIR
    assert store.migration.from_legacy
    assert store.migration.moved_to == store.root
    assert [p.serial.value for p in store.list_robot_profiles()] == ["LR4C111111"]
    assert not legacy.exists(), "the old directory is gone, not duplicated"


def test_a_migration_that_cannot_move_the_old_store_refuses_to_carry_on(
    tmp_path: Path,
) -> None:
    """Carrying on would start a second, empty store while the real one stays
    hidden — every robot would look forgotten, and a second CA would be made
    beside the one they already trust."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    RobotProfileStore(tmp_path / LEGACY_SUBDIR).save(make(serial="LR4C111111"))
    with (
        patch.object(Path, "rename", side_effect=PermissionError(13, "denied")),
        pytest.raises(RobotProfileError, match="could not move"),
    ):
        RobotProfileStore.from_env({"HOME": str(tmp_path)})


def test_a_layout_from_the_future_is_refused(store: RobotProfileStore) -> None:
    """Never rewrite data we cannot read: a newer build may have reshaped
    something, and a best-effort read would drop it and save the remains back."""
    from whiskerless.robot_profiles import LAYOUT_VERSION

    store.save(make())
    (store.root / ".layout").write_text(f"{LAYOUT_VERSION + 1}\n")
    with pytest.raises(RobotProfileError, match="newer whiskerless"):
        store.check_layout()


def test_a_pre_layout_store_keeps_its_broker_and_its_ca(tmp_path: Path) -> None:
    """The upgrade that would otherwise strand every robot: before layout 1 the
    broker and CA lived on each robot, and ignoring them makes the machine look
    like it has neither — so provisioning would offer a NEW authority, and
    accepting it leaves every robot trusting a certificate the broker no longer
    presents."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR
    robot = legacy / "robots" / "LR4C654321"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(json.dumps({
        "serial": "LR4C654321", "host": "192.0.2.10", "port": 8883,
        "verify_hostname": True, "wifi_ssid": "MyIoT",
    }))
    (robot / "ca.pem").write_text(CA)

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    broker = store.load_broker()
    assert broker.host == "192.0.2.10"
    assert store.has_ca_cert(), "the certificate the robots already trust"
    assert store.ca_path.read_text() == CA
    assert not store.has_ca(), "no key came with it, so nothing can be issued here"
    assert store.load("LR4C654321").wifi_ssid == "MyIoT"


def test_a_root_ca_from_an_even_older_layout_is_adopted(tmp_path: Path) -> None:
    """A stray ca.crt at the root predates the ca/ directory."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR
    (legacy / "robots" / "LR4C654321").mkdir(parents=True)
    (legacy / "robots" / "LR4C654321" / "profile.json").write_text(
        json.dumps({"serial": "LR4C654321", "host": "192.0.2.10"})
    )
    (legacy / "ca.crt").write_text(CA)
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.ca_path.read_text() == CA


def test_the_migration_runs_once(tmp_path: Path) -> None:
    """Stamped afterwards, so a later hand-edit of broker.json is not undone by
    the next command re-reading a robot's stale copy."""
    from whiskerless.robot_profiles import LAYOUT_VERSION, LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR
    (legacy / "robots" / "LR4C654321").mkdir(parents=True)
    (legacy / "robots" / "LR4C654321" / "profile.json").write_text(
        json.dumps({"serial": "LR4C654321", "host": "192.0.2.10"})
    )
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.layout_version() == LAYOUT_VERSION
    store.save_broker(Broker(host="10.0.0.1"))
    assert RobotProfileStore.from_env({"HOME": str(tmp_path)}).load_broker().host == "10.0.0.1"


def test_a_pre_layout_store_with_no_robots_migrates_quietly(tmp_path: Path) -> None:
    """An empty legacy directory has nothing to hoist and must not fail trying."""
    from whiskerless.robot_profiles import LAYOUT_VERSION, LEGACY_SUBDIR

    (tmp_path / LEGACY_SUBDIR / "robots").mkdir(parents=True)
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.layout_version() == LAYOUT_VERSION
    assert not store.has_broker()


def test_a_pre_layout_profile_that_will_not_parse_loses_only_the_broker(
    tmp_path: Path,
) -> None:
    """A corrupt profile must not take the whole migration down — the CA beside
    it is still the certificate every robot trusts."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    robot = tmp_path / LEGACY_SUBDIR / "robots" / "LR4C654321"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text("{not json")
    (robot / "ca.pem").write_text(CA)
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert not store.has_broker(), "nothing usable to hoist"
    assert store.ca_path.read_text() == CA, "but the CA came across"


def test_the_default_robot_is_the_one_whose_broker_is_hoisted(tmp_path: Path) -> None:
    """With several robots, the one marked default is the machine's real broker."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR
    for serial, host in (("LR4C111111", "10.0.0.1"), ("LR4C222222", "10.0.0.2")):
        d = legacy / "robots" / serial
        d.mkdir(parents=True)
        (d / "profile.json").write_text(json.dumps({"serial": serial, "host": host}))
    (legacy / "default").write_text("LR4C222222\n")
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.load_broker().host == "10.0.0.2"
    assert store.migration.broker == "10.0.0.2"
    assert store.migration.discarded_brokers == ("10.0.0.1",)


def test_the_layout_is_not_stamped_if_the_migration_fails(tmp_path: Path) -> None:
    """A marker written mid-migration would make the next run skip the unfinished
    work forever — leaving the CA behind, so `setup` generates a replacement that
    every existing robot refuses."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    robot = tmp_path / LEGACY_SUBDIR / "robots" / "LR4C654321"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(json.dumps({"serial": "LR4C654321", "host": "192.0.2.10"}))
    (robot / "ca.pem").write_text(CA)

    attempted, legacy = RobotProfileStore._unopened_from_env({"HOME": str(tmp_path)})
    with (
        patch.object(RobotProfileStore, "save_ca_cert_only", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        attempted._open(legacy)

    # Nothing stamped, so the next run tries again rather than skipping forever.
    store = RobotProfileStore(tmp_path / "whiskerless")
    assert attempted.migration.from_legacy, "the move happened even though the upgrade did not finish"
    assert attempted.migration.moved_to == store.root
    assert store.layout_version() == 0
    assert RobotProfileStore.from_env({"HOME": str(tmp_path)}).ca_path.read_text() == CA


def test_a_legacy_profile_of_the_wrong_shape_does_not_break_every_command(
    tmp_path: Path,
) -> None:
    """Migration runs from from_env(), so anything raising here takes the whole
    CLI down — including `robots`, which is how you would diagnose it."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    robot = tmp_path / LEGACY_SUBDIR / "robots" / "LR4C654321"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text("[]")
    (robot / "ca.pem").write_text(CA)
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert not store.has_broker()
    assert store.ca_path.read_text() == CA, "the CA still came across"


def test_a_legacy_profile_with_an_unusable_port_still_hoists(tmp_path: Path) -> None:
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    robot = tmp_path / LEGACY_SUBDIR / "robots" / "LR4C654321"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(
        json.dumps({"serial": "LR4C654321", "host": "192.0.2.10", "port": "eight"})
    )
    # The port it carried was never usable and is no longer read at all; what has
    # to survive the hoist is the host, because the CA travels with it.
    assert RobotProfileStore.from_env({"HOME": str(tmp_path)}).load_broker().host == "192.0.2.10"


def test_migration_takes_the_hoisted_values_out_of_the_robot_profiles(tmp_path: Path) -> None:
    """Hoisting alone leaves the old settings sitting in every robot's file.

    `host`, `port`, `verify_hostname` and `username` stopped being read in 0.2.0.
    Leaving them is not merely untidy: they are what somebody edits when the
    broker moves, and then wonders why nothing changed.
    """
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    robot = tmp_path / LEGACY_SUBDIR / "robots" / "LR4C123456"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(json.dumps({
        "serial": "LR4C123456", "host": "192.0.2.10", "port": 1884,
        "verify_hostname": False, "username": "mqtt-user", "wifi_ssid": "MyIoT",
        "name": "Upstairs", "litter_full_mm": 60,
    }))
    (robot / "ca.pem").write_text(CA)

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    written = json.loads((store.root / "robots" / "LR4C123456" / "profile.json").read_text())

    assert set(written) == {
        "serial", "serial_verified", "name", "wifi_ssid",
        "litter_full_mm", "litter_empty_mm", "cert_serial",
    }, written
    assert written["name"] == "Upstairs", "what is still meaningful survives"
    assert written["wifi_ssid"] == "MyIoT"
    assert written["litter_full_mm"] == 60
    # The broker was hoisted to the store, so it is not lost — just not here.
    assert store.load_broker().host == "192.0.2.10"
    assert not (store.root / "robots" / "LR4C123456" / "ca.pem").exists()
    assert store.has_ca_cert(), "the anchor moved to the store rather than being dropped"


def test_the_only_trust_anchor_survives_when_it_is_not_on_the_default_robot(
    tmp_path: Path,
) -> None:
    """The anchor can sit under ANY robot, and the cleanup removes them all.

    A robot added after the CA stopped being written per-robot has none, so
    looking only at the chosen profile finds nothing — and then the tidy-up
    deletes the copy that was the store's only trust anchor. Robots already
    running would keep working, but `provision` would then offer a NEW authority,
    and accepting it strands every one of them.
    """
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    for serial in ("LR4C111111", "LR4C222222"):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": "192.0.2.10"})
        )
    # Only the SECOND robot carries it; the first sorts earlier and is chosen.
    (legacy / "LR4C222222" / "ca.pem").write_text(CA)

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.has_ca_cert(), "the store lost its only trust anchor"
    assert store.ca_path.read_text().strip() == CA.strip()



def test_a_broker_on_a_non_default_robot_is_not_dropped(tmp_path: Path) -> None:
    """The chosen profile can be unreadable while another holds the address.

    Hoisting nothing and then stripping `host` from the readable one destroys the
    only broker address there was — and unlike the CA, nothing else has a copy.
    """
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    (legacy / "LR4C111111").mkdir(parents=True)
    (legacy / "LR4C111111" / "profile.json").write_text("{not json at all")
    (legacy / "LR4C222222").mkdir(parents=True)
    (legacy / "LR4C222222" / "profile.json").write_text(
        json.dumps({"serial": "LR4C222222", "host": "192.0.2.10"})
    )

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.load_broker().host == "192.0.2.10"


def test_a_divergent_trust_anchor_is_left_where_it_is(tmp_path: Path) -> None:
    """One store keeps one CA, and `save()` removes the per-robot copies.

    A robot whose anchor differs belongs to a different broker, so tidying its
    profile would destroy the only copy of that CA. Its dead fields stay — a
    trust anchor is worth more than tidiness, and the notice names the broker it
    goes with.
    """
    from whiskerless import pki
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    theirs = pki.generate_ca("theirs").cert_pem
    other = pki.generate_ca("the other broker").cert_pem
    for serial, host, anchor in (
        ("LR4C111111", "192.0.2.10", theirs),
        ("LR4C222222", "198.51.100.20", other),
    ):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": host})
        )
        (legacy / serial / "ca.pem").write_text(anchor)

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.ca_path.read_text().strip() == theirs.strip()
    kept = store.root / "robots" / "LR4C222222" / "ca.pem"
    assert kept.is_file(), "the other broker's anchor was destroyed"
    assert kept.read_text().strip() == other.strip()
    # The robot on the kept broker is still tidied.
    assert not (store.root / "robots" / "LR4C111111" / "ca.pem").exists()


def _explode_on(name: str, parent: str):
    """Make one specific file unreadable, deterministically.

    Patched rather than chmod'd: CI containers run as root, where the permission
    would simply be ignored and the branch never taken.
    """
    real_read = Path.read_text

    def _read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == name and self.parent.name == parent:
            raise OSError("unreadable")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    return _read


def test_an_unreadable_anchor_is_skipped_when_another_robot_has_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad file must not take every command down when the same anchor is
    readable elsewhere — this runs from `from_env()`."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    for serial in ("LR4C111111", "LR4C222222"):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": "192.0.2.10"})
        )
        (legacy / serial / "ca.pem").write_text(CA)

    monkeypatch.setattr(Path, "read_text", _explode_on("ca.pem", "LR4C111111"))
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.has_ca_cert(), "the readable copy should have been used"


def test_no_readable_anchor_leaves_the_migration_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carrying on would stamp the layout, so the next run skips the migration
    forever — and `setup` then offers a replacement authority that every robot
    trusting the preserved one refuses. Better to stop and say so."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    robot = tmp_path / LEGACY_SUBDIR / "robots" / "LR4C123456"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(json.dumps({"serial": "LR4C123456", "host": "192.0.2.10"}))
    (robot / "ca.pem").write_text(CA)

    monkeypatch.setattr(Path, "read_text", _explode_on("ca.pem", "LR4C123456"))
    with pytest.raises(RobotProfileError, match="could be read"):
        RobotProfileStore.from_env({"HOME": str(tmp_path)})

    monkeypatch.undo()
    # Not stamped, so a later run with the permissions fixed still migrates.
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.has_ca_cert()


def test_the_hoisted_ca_belongs_to_the_hoisted_broker(tmp_path: Path) -> None:
    """The broker address comes from the DEFAULT robot, so its anchor must too.

    Taking the address from one profile and the certificate from whichever sorts
    first pairs broker B with CA A: every handshake fails, and `setup` then asks
    for the key of an authority that is not the one in use.
    """
    from whiskerless import pki
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    first_ca = pki.generate_ca("first by name").cert_pem
    default_ca = pki.generate_ca("the default robot's").cert_pem
    for serial, host, anchor in (
        ("LR4C111111", "192.0.2.10", first_ca),
        ("LR4C222222", "198.51.100.20", default_ca),
    ):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": host})
        )
        (legacy / serial / "ca.pem").write_text(anchor)
    # The default is the SECOND directory, so directory order is the wrong answer.
    (tmp_path / LEGACY_SUBDIR / "default").write_text("LR4C222222")

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.load_broker().host == "198.51.100.20"
    assert store.ca_path.read_text().strip() == default_ca.strip(), "broker and CA disagree"


def test_a_robot_on_another_broker_keeps_the_address_that_says_so(tmp_path: Path) -> None:
    """One host survives in the store. A robot belonging to the other broker keeps
    its profile untouched, because that profile is the only remaining record of
    which address it belongs to — and splitting it into its own store needs it."""
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    for serial, host in (("LR4C111111", "192.0.2.10"), ("LR4C222222", "198.51.100.20")):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": host, "username": "dead"})
        )

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    kept = json.loads((store.root / "robots" / "LR4C111111" / "profile.json").read_text())
    other = json.loads((store.root / "robots" / "LR4C222222" / "profile.json").read_text())
    assert "host" not in kept, "the robot on the kept broker is tidied"
    assert other["host"] == "198.51.100.20", "the other robot's address was destroyed"


def test_a_divergent_anchor_on_the_same_broker_is_also_left_alone(tmp_path: Path) -> None:
    """Two robots naming the same broker but different authorities.

    The host check does not separate them, so the anchor comparison has to: one
    store keeps one CA, and `save()` removes the per-robot copies, which would
    destroy the only copy of the other one.
    """
    from whiskerless import pki
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    theirs = pki.generate_ca("theirs").cert_pem
    other = pki.generate_ca("another authority").cert_pem
    for serial, anchor in (("LR4C111111", theirs), ("LR4C222222", other)):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": "192.0.2.10"})
        )
        (legacy / serial / "ca.pem").write_text(anchor)

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.ca_path.read_text().strip() == theirs.strip()
    kept = store.root / "robots" / "LR4C222222" / "ca.pem"
    assert kept.is_file() and kept.read_text().strip() == other.strip()


def test_an_unreadable_anchor_during_cleanup_skips_that_robot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparison deciding whether to tidy a robot has to read its anchor.

    Unreadable means unprovable, and `save()` would delete the file — so the safe
    answer is to leave that robot exactly as it is.
    """
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    for serial in ("LR4C111111", "LR4C222222"):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": "192.0.2.10", "username": "dead"})
        )
        (legacy / serial / "ca.pem").write_text(CA)

    real_read = Path.read_text
    hoisted = {"done": False}

    def _read(self: Path, *args: object, **kwargs: object) -> str:
        # Readable while the anchor is hoisted, unreadable for the cleanup pass.
        if self.name == "ca.pem" and self.parent.name == "LR4C222222" and hoisted["done"]:
            raise OSError("unreadable")
        if self.name == "ca.pem":
            hoisted["done"] = True
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _read)
    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    monkeypatch.undo()
    left = json.loads((store.root / "robots" / "LR4C222222" / "profile.json").read_text())
    assert left["username"] == "dead", "an unprovable robot was tidied anyway"


def test_saving_a_divergent_robot_keeps_the_anchor_the_migration_preserved(
    tmp_path: Path,
) -> None:
    """The migration leaves a robot whose CA is not the store's exactly where it
    is. Nothing preserves that if the next `save()` — a rename, a calibration —
    deletes the file anyway; the protection has to survive being used."""
    from whiskerless import pki
    from whiskerless.robot_profiles import LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR / "robots"
    theirs = pki.generate_ca("theirs").cert_pem
    other = pki.generate_ca("another authority").cert_pem
    for serial, anchor in (("LR4C111111", theirs), ("LR4C222222", other)):
        (legacy / serial).mkdir(parents=True)
        (legacy / serial / "profile.json").write_text(
            json.dumps({"serial": serial, "host": "192.0.2.10"})
        )
        (legacy / serial / "ca.pem").write_text(anchor)

    store = RobotProfileStore.from_env({"HOME": str(tmp_path)})
    divergent = store.load("LR4C222222")
    store.save(replace(divergent, name="Upstairs"))
    kept = store.root / "robots" / "LR4C222222" / "ca.pem"
    assert kept.is_file(), "the only copy of that authority was deleted by a rename"
    assert kept.read_text().strip() == other.strip()

    # A robot on the store's own authority still loses its leftover copy.
    store.save(store.load("LR4C111111"))
    assert not (store.root / "robots" / "LR4C111111" / "ca.pem").exists()
    kept_profile = json.loads((kept.parent / "profile.json").read_text())
    assert kept_profile["host"] == "192.0.2.10", (
        "the anchor survived but nothing records which broker it belongs to"
    )
    assert "host" not in json.loads(
        (store.root / "robots" / "LR4C111111" / "profile.json").read_text()
    )


def test_a_hoist_that_fails_is_not_announced_as_an_upgrade(tmp_path: Path) -> None:
    """The layout stays at 0 and the next run tries again. Saying "upgraded" over
    that sends somebody looking for changes their store has not got.

    Uses a hand-placed store, where nothing is renamed: a store that MOVED has
    something true to report whatever the hoist then does.
    """
    robot = tmp_path / "elsewhere" / "robots" / "LR4C123456"
    robot.mkdir(parents=True)
    (robot / "profile.json").write_text(
        json.dumps({"serial": "LR4C123456", "host": "192.0.2.10"})
    )
    (robot / "ca.pem").write_text(CA)

    real_read = Path.read_text

    def _read(self: Path, *args: object, **kwargs: object) -> str:
        # Not chmod(0): CI runs as root, which reads a mode-000 file happily.
        if self.name == "ca.pem":
            raise OSError("unreadable")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    attempted, legacy = RobotProfileStore._unopened_from_env(
        {HOME_ENV: str(tmp_path / "elsewhere")}
    )
    with (
        patch.object(Path, "read_text", _read),
        pytest.raises(RobotProfileError, match="could be read"),
    ):
        attempted._open(legacy)
    assert not attempted.migration.from_legacy, "an upgrade that did not finish"
    assert RobotProfileStore(tmp_path / "elsewhere").layout_version() == 0, "marked done anyway"


def test_an_unreadable_leftover_anchor_is_kept_rather_than_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unreadable cannot be proven to be a copy of the store's own CA, and
    unlinking is the branch that has to be proven — nothing puts the file back."""
    from whiskerless import pki

    store = RobotProfileStore(tmp_path / "store")
    store.save_ca(pki.generate_ca("ours"))
    store.save(RobotProfile(serial=Serial("LR4C123456")))
    stray = store.root / "robots" / "LR4C123456" / "ca.pem"
    stray.write_text(store.ca_path.read_text())

    real_read = Path.read_text

    def _read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "ca.pem":
            raise OSError("unreadable")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _read)
    store.save(RobotProfile(serial=Serial("LR4C123456"), name="Upstairs"))
    monkeypatch.undo()
    assert stray.is_file(), "a file that could not be read was deleted anyway"


def test_a_stray_anchor_survives_a_store_that_has_no_ca_of_its_own(tmp_path: Path) -> None:
    """Nothing to compare against means nothing is provably a leftover — and here
    the stray IS the only trust anchor the store has."""
    store = RobotProfileStore(tmp_path / "store")
    directory = store.root / "robots" / "LR4C123456"
    directory.mkdir(parents=True)
    stray = directory / "ca.pem"
    stray.write_text(CA)

    store.save(RobotProfile(serial=Serial("LR4C123456")))
    assert stray.is_file(), "the store's only trust anchor was deleted"
    # No profile.json existed to carry an address from, and an empty `host` reads
    # as a broker cleared on purpose.
    assert "host" not in json.loads((directory / "profile.json").read_text())


# --- how this store authenticates ------------------------------------------


def test_an_unknown_auth_mode_is_refused_rather_than_defaulted(store: RobotProfileStore) -> None:
    """Reading it as 'mutual' would hand a robot an identity in a setup that
    asked for none — the silent downgrade the stored field exists to prevent."""
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text(json.dumps({"host": "192.0.2.10", "auth": "whatever"}))
    with pytest.raises(RobotProfileError, match="does not know"):
        store.load_broker()


@pytest.mark.parametrize("mode", list(AuthMode))
def test_every_mode_survives_a_write_and_a_read(store: RobotProfileStore, mode: AuthMode) -> None:
    store.save_broker(Broker(host="192.0.2.10", auth=mode))
    assert store.load_broker().auth is mode


def test_mutual_without_a_signing_key_is_an_error_not_a_downgrade(store: RobotProfileStore) -> None:
    from whiskerless import pki

    store.save_ca_cert_only(pki.generate_ca().cert_pem)
    store.save_broker(Broker(host="192.0.2.10", auth=AuthMode.MUTUAL))
    with pytest.raises(RobotProfileError, match="says auth is 'mutual'"):
        store.assert_usable()


@pytest.mark.parametrize("mode", [AuthMode.SUPPLIED, AuthMode.ANONYMOUS])
def test_the_other_modes_still_need_the_trust_anchor(
    store: RobotProfileStore, mode: AuthMode
) -> None:
    """The mode changes who issues the robot's identity, not whether there is an
    authority behind the broker's certificate."""
    store.save_broker(Broker(host="192.0.2.10", auth=mode))
    with pytest.raises(RobotProfileError, match="still needs the CA certificate"):
        store.assert_usable()


def test_connecting_does_not_need_a_key_it_will_never_use(store: RobotProfileStore) -> None:
    """A store whose CA key has gone missing still talks to its broker with the
    identity it holds. Failing `state` over a key that only matters at the next
    provision would be a guard firing at the wrong moment."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    store.client_identity()
    store.save_broker(Broker(host="192.0.2.10"))
    store.ca_key_path.unlink()
    assert store.settings().client_cert_data, "the stored identity was not presented"


def test_an_anonymous_store_presents_no_identity_of_its_own(store: RobotProfileStore) -> None:
    """The CLI connects the way the robots do. Presenting a certificate on a
    listener that accepts anonymous clients would make the CLI the one client on
    it held to a different standard."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    store.client_identity()
    store.save_broker(Broker(host="192.0.2.10", auth=AuthMode.ANONYMOUS))
    settings = store.settings()
    assert settings.ca_cert_data, "the broker still has to be verified"
    assert settings.client_cert_data is None and settings.client_key_data is None


# --- what each robot presents ----------------------------------------------


def test_a_robots_identity_is_kept_and_reused(store: RobotProfileStore) -> None:
    """A robot re-provisioned — a new WiFi password is enough — stays the same
    client to the broker, so ACLs and log lines keyed to it keep pointing at it."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    first = store.robot_identity("LR4C123456")
    assert store.robot_identity("LR4C123456").cert_pem == first.cert_pem
    assert pki.certificate_common_name(first.cert_pem) == "LR4C123456"
    assert (store.robot_client_dir("LR4C123456") / "client.key").is_file()


def test_a_robots_identity_can_be_replaced_without_losing_its_profile(
    store: RobotProfileStore,
) -> None:
    """The escape hatch a cached key needs: replacing one believed compromised
    must not cost the measurements on the profile beside it."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    store.save(RobotProfile(serial=Serial("LR4C123456"), litter_full_mm=90))
    first = store.robot_identity("LR4C123456")
    second = store.robot_identity("LR4C123456", reissue=True)
    assert second.cert_pem != first.cert_pem
    assert store.load("LR4C123456").litter_full_mm == 90


def test_replacing_the_authority_drops_the_identities_it_signed(store: RobotProfileStore) -> None:
    """Left behind, `robot_identity()` hands back a certificate the retired CA
    signed — reported as current, refused by the broker."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    store.save(RobotProfile(serial=Serial("LR4C123456"), cert_serial="ab12"))
    store.robot_identity("LR4C123456")
    store.forget_issued_certificates()
    assert not store.has_robot_identity("LR4C123456")
    assert store.load("LR4C123456").cert_serial is None


def test_a_supplied_identity_is_stored_where_an_issued_one_would_be(
    store: RobotProfileStore,
) -> None:
    """One slot either way: the store keeps what it cannot recreate and caches
    what it can, and nothing downstream has to know which it is holding."""
    from whiskerless import pki

    ca = pki.generate_ca()
    store.save_ca_cert_only(ca.cert_pem)
    theirs = pki.issue_client(ca, "LR4C123456")
    store.save_robot_identity("LR4C123456", theirs)
    assert store.load_robot_identity("LR4C123456").cert_pem == theirs.cert_pem
    assert store.has_robot_identity("LR4C123456")


def test_a_robots_identity_survives_a_profile_save(store: RobotProfileStore) -> None:
    """`save()` rewrites the directory the identity lives in."""
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    store.robot_identity("LR4C123456")
    store.save(RobotProfile(serial=Serial("LR4C123456"), name="Upstairs"))
    assert store.has_robot_identity("LR4C123456")


# --- layout marker: same shape as dreame-valetudo's, and rc-era stores still read -----------
def test_the_layout_marker_records_the_version_that_can_read_it(tmp_path: Path) -> None:
    """A build meeting a FUTURE layout cannot know which release understands it — so the store
    carries that fact. Matches dreame-valetudo's marker."""
    store = robot_profiles_module.RobotProfileStore(tmp_path / "store")
    store._ensure_root()

    # `.layout.json`, not `.layout`: the marker itself stays a bare integer so builds that parse
    # it with `int()` — every one that has shipped — keep working against the same store.
    marker = json.loads((tmp_path / "store" / ".layout.json").read_text())
    assert marker["layout_version"] == str(robot_profiles_module.LAYOUT_VERSION)
    assert marker["min_tool_version"] == robot_profiles_module._LAYOUT_SINCE[robot_profiles_module.LAYOUT_VERSION]
    assert marker["tool_version"]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"layout_version": "1"}', 1),
        ("1\n", 1),           # the form the 0.2.0 release candidates wrote
        ("not-a-layout", 0),
        ("[1]", 0),
    ],
)
def test_every_marker_form_reports_the_right_layout(tmp_path: Path, content: str, expected: int) -> None:
    """A bare `1` is valid JSON but not a mapping. Reading it as "pre-versioning" would re-run the
    layout-1 migration over a store that is already layout 1."""
    root = tmp_path / "store"
    root.mkdir()
    (root / ".layout").write_text(content)

    assert robot_profiles_module.RobotProfileStore(root).layout_version() == expected


def test_refusing_a_newer_layout_names_the_version_that_can_read_it(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    (root / ".layout").write_text(json.dumps({"layout_version": "9", "min_tool_version": "0.9.0"}))

    with pytest.raises(RobotProfileError, match=r"whiskerless >= 0\.9\.0"):
        robot_profiles_module.RobotProfileStore(root).check_layout()


def test_two_processes_cannot_mutate_the_store_at_once(tmp_path: Path) -> None:
    """The CLI and the Home Assistant coordinator write the same store BY DESIGN.

    Atomic replacement stops a torn file; it does not stop one process's read-modify-write from
    landing on top of the other's. Two real processes, because that is the only thing an flock
    actually constrains — threads in one interpreter would prove nothing.
    """
    root = tmp_path / "store"
    robot_profiles_module.RobotProfileStore(root)._ensure_root()
    log = tmp_path / "order"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import sys, time, pathlib\n"
        "from whiskerless.robot_profiles import RobotProfileStore\n"
        "store = RobotProfileStore(pathlib.Path(sys.argv[1]))\n"
        "log = pathlib.Path(sys.argv[3])\n"
        "with store._exclusive():\n"
        "    log.open('a').write(f'{sys.argv[2]}-in\\n')\n"
        "    time.sleep(0.4)\n"
        "    log.open('a').write(f'{sys.argv[2]}-out\\n')\n"
    )
    running = [
        subprocess.Popen([sys.executable, str(worker), str(root), name, str(log)])
        for name in ("A", "B")
    ]
    for process in running:
        assert process.wait(timeout=30) == 0

    order = log.read_text().split()
    assert len(order) == 4
    # Whoever won, they did not interleave: the first writer's -out precedes the second's -in.
    assert order[0].endswith("-in") and order[1].endswith("-out")
    assert order[0][0] == order[1][0], f"writers interleaved: {order}"


def test_a_name_shared_by_two_robots_resolves_to_neither(tmp_path: Path) -> None:
    """Nothing stops two robots being called "Bathroom" — neither provisioning nor `rename` checks.
    Returning the first serial-sorted match meant `forget Bathroom` removed one robot while
    printing the name of the robot the user meant."""
    store = RobotProfileStore(tmp_path)
    store.save(RobotProfile(serial=Serial("LR4C111111"), name="Bathroom"))
    store.save(RobotProfile(serial=Serial("LR4C222222"), name="Bathroom"))
    with pytest.raises(RobotProfileError) as caught:
        store.resolve("Bathroom")
    assert "more than one robot" in str(caught.value)
    assert "LR4C111111" in str(caught.value)
    assert "LR4C222222" in str(caught.value)


def test_a_name_held_by_exactly_one_robot_still_resolves(tmp_path: Path) -> None:
    store = RobotProfileStore(tmp_path)
    store.save(RobotProfile(serial=Serial("LR4C111111"), name="Bathroom"))
    store.save(RobotProfile(serial=Serial("LR4C222222"), name="Upstairs"))
    assert store.resolve("Bathroom").serial.value == "LR4C111111"


def test_a_damaged_profile_is_not_answered_by_another_robots_name(tmp_path: Path) -> None:
    """`load()` raising for an existing-but-unreadable profile used to fall through to the name
    search — so a healthy robot whose display name happened to equal the requested serial answered
    for it, and a command aimed at one physical robot reached another."""
    store = RobotProfileStore(tmp_path)
    store.save(RobotProfile(serial=Serial("LR4C111111")))
    store.save(RobotProfile(serial=Serial("LR4C222222"), name="LR4C111111"))
    damaged = store.robots_dir / "LR4C111111" / "profile.json"
    damaged.write_text("{not json")
    with pytest.raises(RobotProfileError):
        store.resolve("LR4C111111")


def test_the_lock_is_held_across_the_read_as_well_as_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`save()` alone serialises only the WRITE. Two commands that each read the profile first
    could both read the old object and save different replacements, and the second silently
    reverted the first — both reporting success.

    Proven by showing another holder cannot acquire the lock while the transform runs, which is
    the property that makes the interleaving impossible. A second process cannot be spawned here,
    and re-entering from this one would simply deadlock against our own lock.
    """
    store = RobotProfileStore(tmp_path)
    store.save(RobotProfile(serial=Serial("LR4C111111")))
    monkeypatch.setattr(robot_profiles_module, "_LOCK_TIMEOUT_SECONDS", 0.1)
    observed: list[str] = []

    def _transform(current: RobotProfile) -> RobotProfile:
        try:
            with RobotProfileStore(tmp_path)._exclusive():
                observed.append("acquired")
        except RobotProfileError:
            observed.append("refused")
        return replace(current, name="Upstairs")

    store.update("LR4C111111", _transform)
    assert observed == ["refused"], "another writer got in between the read and the write"
    assert RobotProfileStore(tmp_path).load("LR4C111111").name == "Upstairs"


def test_the_layout_marker_stays_readable_by_older_builds(tmp_path: Path) -> None:
    """Every build that has shipped parses `.layout` with `int()`. Writing JSON there made an
    older duplicate install read the layout as 0, re-run the layout-1 migration over a layout-1
    store, and repeat its migration warning on every command."""
    store = RobotProfileStore(tmp_path / "s")
    store.save(RobotProfile(serial=Serial("LR4C123456")))
    raw = (store.root / ".layout").read_text(encoding="utf-8").strip()
    assert int(raw) == 1, "an older build parses this with int() and must still succeed"
    assert store.layout_version() == 1
    assert (store.root / ".layout.json").is_file(), "the richer facts live beside it"


def test_a_json_layout_marker_is_rewritten_for_older_builds(tmp_path: Path) -> None:
    """A build shipped briefly that wrote the whole record into `.layout` itself. This build reads
    that fine, which is the problem: without rewriting it, an older duplicate install goes on
    parsing the layout as 0 and re-running the migration on every command."""
    root = tmp_path / "store"
    store = RobotProfileStore(root)
    store.save(RobotProfile(serial=Serial("LR4C123456")))
    (root / ".layout").write_text(
        json.dumps({"layout_version": "1", "min_tool_version": "0.2.0"}) + "\n", encoding="utf-8"
    )
    (root / ".layout.json").unlink(missing_ok=True)

    RobotProfileStore.from_env({HOME_ENV: str(root)})

    assert int((root / ".layout").read_text(encoding="utf-8").strip()) == 1
    assert (root / ".layout.json").is_file(), "the metadata moved beside it rather than being lost"


def test_a_newer_json_marker_is_left_alone(tmp_path: Path) -> None:
    """Only OUR version is normalised. A marker from a future layout is something this build has
    already refused to read, and rewriting it would be exactly the damage that refusal prevents."""
    root = tmp_path / "store"
    RobotProfileStore(root).save(RobotProfile(serial=Serial("LR4C123456")))
    (root / ".layout").write_text(json.dumps({"layout_version": "99"}) + "\n", encoding="utf-8")
    with pytest.raises(RobotProfileError):
        RobotProfileStore.from_env({HOME_ENV: str(root)})
    assert (root / ".layout").read_text(encoding="utf-8").strip().startswith("{")
