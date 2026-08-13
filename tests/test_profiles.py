"""Tests for the per-machine robot profile store."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from whiskerless.exceptions import ProfileError
from whiskerless.mqtt import DEFAULT_TLS_PORT
from whiskerless.profiles import (
    HOME_ENV,
    ProfileStore,
    RobotProfile,
    Serial,
    SharedSetup,
    merge_overrides,
)

CA = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "home")


def make(serial: str = "LR4C123456", **kwargs: object) -> RobotProfile:
    defaults: dict[str, object] = {"host": "192.168.1.10", "ca_pem": CA}
    defaults.update(kwargs)
    return RobotProfile(serial=Serial(serial), **defaults)  # type: ignore[arg-type]


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
        store.save(RobotProfile(serial=Serial("../escape"), host="h"))
    assert not (tmp_path / "escape").exists()


# --- RobotProfile -------------------------------------------------------------
def test_display_name_prefers_the_chosen_name() -> None:
    assert make(name="Upstairs").display_name == "Upstairs"


def test_display_name_falls_back_to_the_serial() -> None:
    assert make().display_name == "LR4C123456"


def test_settings_pass_the_ca_as_data_not_a_path() -> None:
    settings = make().settings()
    assert settings.ca_cert_data == CA
    assert settings.ca_cert_path is None


def test_settings_never_default_the_client_id_to_the_serial() -> None:
    """A client claiming the robot's id kicks the robot off its own connection."""
    assert make().settings().client_id is None
    assert make().settings(client_id="whiskerless-cli").client_id == "whiskerless-cli"


def test_settings_carry_credentials_and_hostname_policy() -> None:
    settings = make(username="u", password="p", verify_hostname=False).settings()
    assert (settings.username, settings.password) == ("u", "p")
    assert settings.verify_hostname is False


# --- save / load --------------------------------------------------------------
def test_save_then_load_round_trips(store: ProfileStore) -> None:
    original = make(name="Upstairs", port=1883, username="u")
    store.save(original)
    assert store.load("LR4C123456") == original


def test_a_password_is_never_written_to_disk(store: ProfileStore) -> None:
    """0600 plaintext is not "stored securely" however it is described."""
    store.save(make(username="u", password="hunter2"))
    on_disk = (store.robots_dir / "LR4C123456").rglob("*")
    assert not any("hunter2" in p.read_text(encoding="utf-8") for p in on_disk if p.is_file())


def test_a_password_does_not_survive_a_reload(store: ProfileStore) -> None:
    store.save(make(password="hunter2"))
    assert store.load("LR4C123456").password is None


def test_load_accepts_a_differently_cased_serial(store: ProfileStore) -> None:
    store.save(make())
    assert store.load("lr4c123456").serial.value == "LR4C123456"


def test_save_preserves_serial_verification(store: ProfileStore) -> None:
    store.save(RobotProfile(serial=Serial("LR4C123456", verified=True), host="h"))
    assert store.load("LR4C123456").serial.verified is True


def test_load_is_helpful_when_the_robot_is_unknown(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="run `whiskerless provision` first"):
        store.load("LR4C999999")


def test_load_reports_corrupt_json(store: ProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError, match="could not read the profile"):
        store.load("LR4C123456")


def test_load_rejects_a_json_document_that_is_not_an_object(store: ProfileStore) -> None:
    store.save(make())
    (store.robots_dir / "LR4C123456" / "profile.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ProfileError, match="not a JSON object"):
        store.load("LR4C123456")


@pytest.mark.parametrize("host", [None, "", 42])
def test_load_rejects_a_profile_without_a_usable_host(store: ProfileStore, host: object) -> None:
    store.save(make())
    path = store.robots_dir / "LR4C123456" / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["host"] = host
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProfileError, match="no broker host"):
        store.load("LR4C123456")


def test_load_reports_an_unreadable_ca(store: ProfileStore) -> None:
    store.save(make())
    ca_path = store.robots_dir / "LR4C123456" / "ca.pem"
    ca_path.unlink()
    ca_path.mkdir()  # a directory where the CA should be
    with pytest.raises(ProfileError, match="could not read the stored CA"):
        store.load("LR4C123456")


def test_load_reports_an_unreadable_profile(store: ProfileStore) -> None:
    directory = store.robots_dir / "LR4C123456"
    (directory / "profile.json").mkdir(parents=True)
    with pytest.raises(ProfileError, match="could not read the profile"):
        store.load("LR4C123456")


def test_a_profile_saved_without_a_ca_loads_with_none(store: ProfileStore) -> None:
    store.save(RobotProfile(serial=Serial("LR4C123456"), host="h"))
    assert store.load("LR4C123456").ca_pem is None


def test_a_blank_username_loads_as_none(store: ProfileStore) -> None:
    store.save(make(username=""))
    assert store.load("LR4C123456").username is None


def test_defaults_apply_when_optional_keys_are_absent(store: ProfileStore) -> None:
    directory = store.robots_dir / "LR4C123456"
    directory.mkdir(parents=True)
    (directory / "profile.json").write_text(json.dumps({"host": "h"}), encoding="utf-8")
    loaded = store.load("LR4C123456")
    assert loaded.port == DEFAULT_TLS_PORT
    assert loaded.verify_hostname is True
    assert loaded.name == ""


def test_the_directory_name_wins_over_a_hand_edited_serial(store: ProfileStore) -> None:
    store.save(make())
    path = store.robots_dir / "LR4C123456" / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["serial"] = "LR4C000000"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load("LR4C123456").serial.value == "LR4C123456"


def test_saving_twice_replaces_rather_than_appends(store: ProfileStore) -> None:
    store.save(make(host="192.168.1.10"))
    store.save(make(host="10.0.0.5"))
    assert store.load("LR4C123456").host == "10.0.0.5"
    assert len(store.list_profiles()) == 1


# --- permissions --------------------------------------------------------------
def test_stored_files_are_owner_only(store: ProfileStore) -> None:
    """These hold broker credentials in the clear."""
    store.save(make(password="hunter2"))
    directory = store.robots_dir / "LR4C123456"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for name in ("profile.json", "ca.pem"):
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600


def test_the_store_directories_themselves_are_owner_only(store: ProfileStore) -> None:
    """A listable robots/ would advertise every serial in the house."""
    store.save(make())
    for directory in (store.root, store.robots_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_a_failed_overwrite_leaves_the_old_profile_intact(store: ProfileStore) -> None:
    """The point of write-then-rename: a crash mid-save must not eat the old file."""
    store.save(make(host="192.168.1.10"))

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr("whiskerless.profiles.os.replace", refuse)
        with pytest.raises(OSError):
            store.save(make(host="10.0.0.5"))
    assert store.load("LR4C123456").host == "192.168.1.10"
    leftovers = [p.name for p in (store.robots_dir / "LR4C123456").iterdir()]
    assert sorted(leftovers) == ["ca.pem", "profile.json"]


def test_no_temporary_files_survive_a_save(store: ProfileStore) -> None:
    store.save(make())
    leftovers = [p.name for p in (store.robots_dir / "LR4C123456").iterdir()]
    assert sorted(leftovers) == ["ca.pem", "profile.json"]


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


def test_an_unusable_port_is_damage_not_a_crash(store: ProfileStore) -> None:
    """A hand-edited port used to raise a bare ValueError past every caller
    that speaks ProfileError, taking `robots`, `forget` and bare invocations
    down with it — the exact commands that exist to recover from damage."""
    store.save(make())
    path = store.robots_dir / "LR4C123456" / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["port"] = "not-a-port"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProfileError, match="unusable port"):
        store.load("LR4C123456")
    ((name, why),) = store.damaged()
    assert name == "LR4C123456" and "unusable port" in why


def test_saving_without_a_ca_removes_the_stale_one(store: ProfileStore) -> None:
    """An overwrite with no CA must not leave the old one for load() to
    resurrect — the connection would keep trusting a broker CA the profile no
    longer claims."""
    store.save(make())
    store.save(RobotProfile(serial=Serial("LR4C123456"), host="10.0.0.5"))
    assert store.load("LR4C123456").ca_pem is None
    assert not (store.robots_dir / "LR4C123456" / "ca.pem").exists()


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
def test_from_env_honours_the_override(tmp_path: Path) -> None:
    store = ProfileStore.from_env({HOME_ENV: str(tmp_path / "elsewhere")})
    assert store.root == tmp_path / "elsewhere"


def test_from_env_expands_a_tilde_in_the_override(tmp_path: Path) -> None:
    store = ProfileStore.from_env({HOME_ENV: "~/custom", "HOME": str(tmp_path)})
    assert store.root == tmp_path / "custom"


def test_from_env_accepts_a_bare_tilde_override(tmp_path: Path) -> None:
    store = ProfileStore.from_env({HOME_ENV: "~", "HOME": str(tmp_path)})
    assert store.root == tmp_path


def test_from_env_falls_back_to_a_dot_directory_in_home(tmp_path: Path) -> None:
    store = ProfileStore.from_env({"HOME": str(tmp_path)})
    assert store.root == tmp_path / ".whiskerless"


def test_from_env_uses_the_real_home_when_the_variable_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert ProfileStore.from_env({}).root == tmp_path / ".whiskerless"


def test_from_env_reads_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "from-environ"))
    assert ProfileStore.from_env().root == tmp_path / "from-environ"


# --- SharedSetup --------------------------------------------------------------
def test_nothing_saved_agrees_on_nothing() -> None:
    shared = SharedSetup.from_profiles([])
    assert (shared.host, shared.ca_pem, shared.wifi_ssid) == (None, None, None)


def test_a_lone_robot_agrees_with_itself() -> None:
    shared = SharedSetup.from_profiles([make(wifi_ssid="MyIoT")])
    assert shared.host == "192.168.1.10"
    assert shared.ca_pem == CA
    assert shared.wifi_ssid == "MyIoT"


def test_many_robots_on_one_broker_agree() -> None:
    profiles = [make(f"LR4C00000{n}", wifi_ssid="MyIoT") for n in range(1, 6)]
    shared = SharedSetup.from_profiles(profiles)
    assert shared.host == "192.168.1.10"
    assert shared.ca_pem == CA


def test_one_dissenter_is_enough_to_disagree() -> None:
    shared = SharedSetup.from_profiles([make("LR4C000001"), make("LR4C000002", host="10.0.0.9")])
    assert shared.host is None
    assert shared.ca_pem == CA  # they still share the CA


def test_fields_disagree_independently() -> None:
    shared = SharedSetup.from_profiles([
        make("LR4C000001", wifi_ssid="MyIoT"),
        make("LR4C000002", wifi_ssid="Guest"),
    ])
    assert shared.host == "192.168.1.10"
    assert shared.wifi_ssid is None


def test_a_missing_value_is_not_a_disagreement() -> None:
    """A profile saved before a field existed must not veto an otherwise clear answer."""
    shared = SharedSetup.from_profiles([
        make("LR4C000001", wifi_ssid="MyIoT"),
        make("LR4C000002", wifi_ssid=""),
    ])
    assert shared.wifi_ssid == "MyIoT"


def test_a_profile_without_a_ca_does_not_veto_the_shared_one() -> None:
    shared = SharedSetup.from_profiles([make("LR4C000001"), make("LR4C000002", ca_pem=None)])
    assert shared.ca_pem == CA


# --- merge_overrides ----------------------------------------------------------
def test_overrides_replace_only_what_was_given() -> None:
    merged = merge_overrides(make(name="Upstairs"), host="10.0.0.9")
    assert merged.host == "10.0.0.9"
    assert merged.name == "Upstairs"
    assert merged.ca_pem == CA


def test_no_overrides_leaves_the_profile_untouched() -> None:
    profile = make()
    assert merge_overrides(profile) == profile


def test_a_false_override_is_applied_not_treated_as_absent() -> None:
    """`verify_hostname=False` is a real choice; only None means "not given"."""
    assert merge_overrides(make(), verify_hostname=False).verify_hostname is False


def test_every_field_can_be_overridden() -> None:
    merged = merge_overrides(
        make(),
        host="h2",
        port=1883,
        username="u2",
        password="p2",
        verify_hostname=False,
        ca_pem="other",
    )
    assert (merged.host, merged.port, merged.username, merged.password) == (
        "h2",
        1883,
        "u2",
        "p2",
    )
    assert merged.verify_hostname is False
    assert merged.ca_pem == "other"
