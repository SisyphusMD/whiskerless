"""Tests for the per-machine robot profile store."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from whiskerless.exceptions import ProfileError
from whiskerless.profiles import (
    HOME_ENV,
    Broker,
    ProfileStore,
    RobotProfile,
    Serial,
)

CA = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "home")


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
    with pytest.raises(ProfileError, match="not a usable serial"):
        Serial(bad)


def test_serial_traversal_cannot_reach_outside_the_store(tmp_path: Path) -> None:
    """The serial becomes a path segment, so this is a containment test, not style."""
    store = ProfileStore(tmp_path / "home")
    with pytest.raises(ProfileError):
        store.save(RobotProfile(serial=Serial("../escape"), ))
    assert not (tmp_path / "escape").exists()


# --- RobotProfile -------------------------------------------------------------
def test_display_name_prefers_the_chosen_name() -> None:
    assert make(name="Upstairs").display_name == "Upstairs"


def test_display_name_falls_back_to_the_serial() -> None:
    assert make().display_name == "LR4C123456"


# --- save / load --------------------------------------------------------------
def test_save_then_load_round_trips(store: ProfileStore) -> None:
    original = make(name="Upstairs")
    store.save(original)
    assert store.load("LR4C123456") == original


# --- format version and migration ---------------------------------------------
def _stored(store: ProfileStore, serial: str = "LR4C123456") -> Path:
    return store.robots_dir / serial / "profile.json"


def test_load_accepts_a_differently_cased_serial(store: ProfileStore) -> None:
    store.save(make())
    assert store.load("lr4c123456").serial.value == "LR4C123456"


def test_save_preserves_serial_verification(store: ProfileStore) -> None:
    store.save(RobotProfile(serial=Serial("LR4C123456", verified=True), ))
    assert store.load("LR4C123456").serial.verified is True


def test_load_is_helpful_when_the_robot_is_unknown(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="run `whiskerless provision` first"):
        store.load("LR4C999999")


def test_load_rejects_a_json_document_that_is_not_an_object(store: ProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ProfileError, match="not a JSON object"):
        store.load("LR4C123456")


def test_defaults_apply_when_optional_keys_are_absent(store: ProfileStore) -> None:
    directory = store.robots_dir / "LR4C123456"
    directory.mkdir(parents=True)
    (directory / "profile.json").write_text(json.dumps({"host": "h"}), encoding="utf-8")
    loaded = store.load("LR4C123456")
    assert loaded.name == ""


def test_the_directory_name_wins_over_a_hand_edited_serial(store: ProfileStore) -> None:
    store.save(make())
    path = store.robots_dir / "LR4C123456" / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["serial"] = "LR4C000000"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load("LR4C123456").serial.value == "LR4C123456"


def test_saving_twice_replaces_rather_than_appends(store: ProfileStore) -> None:
    store.save(make())
    store.save(make(name="Renamed"))
    assert store.load("LR4C123456").name == "Renamed"
    assert len(store.list_profiles()) == 1


# --- permissions --------------------------------------------------------------
def test_stored_files_are_owner_only(store: ProfileStore) -> None:
    """These hold broker credentials in the clear."""
    store.save(make())
    directory = store.robots_dir / "LR4C123456"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for name in ("profile.json",):
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600


def test_the_store_directories_themselves_are_owner_only(store: ProfileStore) -> None:
    """A listable robots/ would advertise every serial in the house."""
    store.save(make())
    for directory in (store.root, store.robots_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_no_temporary_files_survive_a_save(store: ProfileStore) -> None:
    store.save(make())
    leftovers = [p.name for p in (store.robots_dir / "LR4C123456").iterdir()]
    assert sorted(leftovers) == ["profile.json"]


# --- listing ------------------------------------------------------------------
def test_listing_an_empty_store_is_empty_not_an_error(store: ProfileStore) -> None:
    assert store.list_profiles() == ()


def test_listing_is_sorted_by_serial(store: ProfileStore) -> None:
    store.save(make("LR4C999999"))
    store.save(make("LR4C111111"))
    assert [p.serial.value for p in store.list_profiles()] == ["LR4C111111", "LR4C999999"]


def test_one_corrupt_profile_does_not_hide_the_others(store: ProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    (store.robots_dir / "LR4C999999" / "profile.json").write_text("{bad", encoding="utf-8")
    assert [p.serial.value for p in store.list_profiles()] == ["LR4C111111"]


def test_listing_ignores_stray_files_and_dot_directories(store: ProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "README").write_text("hi", encoding="utf-8")
    (store.robots_dir / ".hidden").mkdir()
    assert [p.serial.value for p in store.list_profiles()] == ["LR4C123456"]


# --- resolve ------------------------------------------------------------------
def test_resolve_returns_the_named_robot(store: ProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    assert store.resolve("LR4C999999").serial.value == "LR4C999999"


def test_resolve_returns_the_only_robot_when_there_is_one(store: ProfileStore) -> None:
    store.save(make())
    assert store.resolve().serial.value == "LR4C123456"


def test_resolve_says_to_provision_when_nothing_is_stored(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="no robots are set up"):
        store.resolve()


def test_resolve_lists_the_candidates_when_ambiguous(store: ProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    with pytest.raises(ProfileError, match="LR4C111111, LR4C999999"):
        store.resolve()


def test_resolve_prefers_the_default_over_ambiguity(store: ProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    store.set_default("LR4C999999")
    assert store.resolve().serial.value == "LR4C999999"


def test_an_explicit_robot_still_beats_the_default(store: ProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    store.set_default("LR4C999999")
    assert store.resolve("LR4C111111").serial.value == "LR4C111111"


# --- default marker -----------------------------------------------------------
def test_there_is_no_default_until_one_is_set(store: ProfileStore) -> None:
    assert store.get_default() is None


def test_set_default_rejects_an_unknown_robot(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="no saved profile"):
        store.set_default("LR4C999999")


def test_a_blank_default_marker_reads_as_unset(store: ProfileStore) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "default").write_text("  \n", encoding="utf-8")
    assert store.get_default() is None


def test_an_unreadable_default_marker_reads_as_unset(store: ProfileStore) -> None:
    (store.root / "default").mkdir(parents=True)  # a directory, not a file
    assert store.get_default() is None


# --- forget -------------------------------------------------------------------
def test_forget_removes_the_profile(store: ProfileStore) -> None:
    store.save(make())
    store.forget("LR4C123456")
    assert store.list_profiles() == ()
    assert not (store.robots_dir / "LR4C123456").exists()


def test_forget_clears_a_default_pointing_at_it(store: ProfileStore) -> None:
    store.save(make())
    store.set_default("LR4C123456")
    store.forget("LR4C123456")
    assert store.get_default() is None


def test_forget_leaves_another_robots_default_alone(store: ProfileStore) -> None:
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    store.set_default("LR4C111111")
    store.forget("LR4C999999")
    assert store.get_default() == "LR4C111111"


def test_forget_rejects_an_unknown_robot(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="no saved profile"):
        store.forget("LR4C999999")


def test_forget_keeps_a_directory_holding_files_it_did_not_write(store: ProfileStore) -> None:
    store.save(make())
    stray = store.robots_dir / "LR4C123456" / "notes.txt"
    stray.write_text("mine", encoding="utf-8")
    store.forget("LR4C123456")
    assert stray.exists()


# --- from_env -----------------------------------------------------------------
def test_from_env_falls_back_to_a_visible_directory_in_home(tmp_path: Path) -> None:
    store = ProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.root == tmp_path / "whiskerless"


def test_from_env_uses_the_real_home_when_the_variable_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert ProfileStore.from_env({}).root == tmp_path / "whiskerless"


def test_from_env_reads_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "from-environ"))
    assert ProfileStore.from_env().root == tmp_path / "from-environ"


# --- restored: store behaviour unrelated to the broker move --------------------
def test_load_reports_corrupt_json(store: ProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError, match="could not read the profile"):
        store.load("LR4C123456")




def test_load_reports_an_unreadable_profile(store: ProfileStore) -> None:
    directory = store.robots_dir / "LR4C123456"
    (directory / "profile.json").mkdir(parents=True)
    with pytest.raises(ProfileError, match="could not read the profile"):
        store.load("LR4C123456")




def test_a_skipped_profile_is_reported_as_damaged(store: ProfileStore) -> None:
    """An entry a user cannot see is one they can never repair or forget."""
    store.save(make("LR4C111111"))
    store.save(make("LR4C999999"))
    (store.robots_dir / "LR4C999999" / "profile.json").write_text("{bad", encoding="utf-8")
    ((name, why),) = store.damaged()
    assert name == "LR4C999999"
    assert "could not read" in why




def test_a_healthy_store_reports_no_damage(store: ProfileStore) -> None:
    store.save(make())
    assert store.damaged() == ()




def test_an_empty_store_reports_no_damage(store: ProfileStore) -> None:
    assert store.damaged() == ()




def test_from_env_honours_the_override(tmp_path: Path) -> None:
    store = ProfileStore.from_env({HOME_ENV: str(tmp_path / "elsewhere")})
    assert store.root == tmp_path / "elsewhere"




def test_from_env_expands_a_tilde_in_the_override(tmp_path: Path) -> None:
    store = ProfileStore.from_env({HOME_ENV: "~/custom", "HOME": str(tmp_path)})
    assert store.root == tmp_path / "custom"




def test_from_env_accepts_a_bare_tilde_override(tmp_path: Path) -> None:
    store = ProfileStore.from_env({HOME_ENV: "~", "HOME": str(tmp_path)})
    assert store.root == tmp_path




# --- the one broker -----------------------------------------------------------
def test_a_broker_round_trips(store: ProfileStore) -> None:
    store.save_broker(Broker(host="192.0.2.10", port=1884, verify_hostname=False))
    saved = store.load_broker()
    assert (saved.host, saved.port, saved.verify_hostname) == ("192.0.2.10", 1884, False)


def test_a_machine_with_no_broker_says_how_to_get_one(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="run `whiskerless provision`"):
        store.load_broker()


@pytest.mark.parametrize("body", ["[]", "null", '"a string"'])
def test_broker_json_that_is_not_an_object_is_damage(store: ProfileStore, body: str) -> None:
    """Valid JSON of the wrong shape would otherwise raise AttributeError and
    bypass the CLI's one-line damaged-configuration handling."""
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text(body, encoding="utf-8")
    with pytest.raises(ProfileError, match="not a JSON object"):
        store.load_broker()


def test_a_broker_file_that_is_not_json_is_damage(store: ProfileStore) -> None:
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError, match="could not read"):
        store.load_broker()


@pytest.mark.parametrize("host", ["", 42, None])
def test_a_broker_without_a_usable_host_is_damage(store: ProfileStore, host: object) -> None:
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text(json.dumps({"host": host}), encoding="utf-8")
    with pytest.raises(ProfileError, match="no broker host"):
        store.load_broker()


def test_a_hand_edited_port_is_damage_not_a_crash(store: ProfileStore) -> None:
    """Every caller speaks ProfileError; a bare ValueError here took them all down."""
    store.save_broker(Broker(host="192.0.2.10"))
    store.broker_path.write_text(
        json.dumps({"host": "192.0.2.10", "port": "eight-thousand"}), encoding="utf-8"
    )
    with pytest.raises(ProfileError, match="unusable port"):
        store.load_broker()


def test_settings_carry_the_ca_and_this_machines_identity(store: ProfileStore) -> None:
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
    store: ProfileStore,
) -> None:
    """The anonymous-listener setup: no CA key, no client certificate, still works."""
    store.save_broker(Broker(host="192.0.2.10"))
    settings = store.settings()
    assert settings.host == "192.0.2.10"
    assert settings.ca_cert_data is None
    assert settings.client_cert_data is None


def test_this_machines_identity_is_minted_from_the_ca_once(store: ProfileStore) -> None:
    from whiskerless import pki

    store.save_ca(pki.generate_ca())
    assert not store.has_client()
    first = store.client_identity()
    assert store.has_client()
    assert store.client_identity().cert_pem == first.cert_pem


def test_a_hidden_legacy_store_is_moved_rather_than_copied(tmp_path: Path) -> None:
    """Two directories that both look like the store is where somebody edits the
    wrong one."""
    from whiskerless.profiles import DEFAULT_SUBDIR, LEGACY_SUBDIR

    legacy = tmp_path / LEGACY_SUBDIR
    ProfileStore(legacy).save(make(serial="LR4C111111"))
    store = ProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.root == tmp_path / DEFAULT_SUBDIR
    assert [p.serial.value for p in store.list_profiles()] == ["LR4C111111"]
    assert not legacy.exists(), "the old directory is gone, not duplicated"


def test_a_migration_that_cannot_move_the_old_store_refuses_to_carry_on(
    tmp_path: Path,
) -> None:
    """Carrying on would start a second, empty store while the real one stays
    hidden — every robot would look forgotten, and a second CA would be made
    beside the one they already trust."""
    from whiskerless.profiles import LEGACY_SUBDIR

    ProfileStore(tmp_path / LEGACY_SUBDIR).save(make(serial="LR4C111111"))
    with (
        patch.object(Path, "rename", side_effect=PermissionError(13, "denied")),
        pytest.raises(ProfileError, match="could not move"),
    ):
        ProfileStore.from_env({"HOME": str(tmp_path)})


def test_a_layout_from_the_future_is_refused(store: ProfileStore) -> None:
    """Never rewrite data we cannot read: a newer build may have reshaped
    something, and a best-effort read would drop it and save the remains back."""
    from whiskerless.profiles import LAYOUT_VERSION

    store.save(make())
    (store.root / ".layout").write_text(f"{LAYOUT_VERSION + 1}\n")
    with pytest.raises(ProfileError, match="newer whiskerless"):
        store.check_layout()
