"""`whiskerless backup` and `whiskerless restore` from the outside.

The archive format is pinned in tests/test_backup.py. What matters here is the
judgement around it: never write a signing key in the clear by accident, and
never replace a working setup without saying which robots it would strand.
"""

from __future__ import annotations

import asyncio
import tarfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from whiskerless import backup, pki
from whiskerless.cli import main
from whiskerless.profiles import Broker, ProfileStore, RobotProfile, Serial

CA = pki.generate_ca("test CA")
OTHER_CA = pki.generate_ca("someone else's CA")


@pytest.fixture(scope="module")
def _cli_loop() -> Any:
    """See tests/test_cli.py — `main` must not close the session's current loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _own_loop(_cli_loop: Any) -> Any:
    with patch("whiskerless.cli.asyncio.run", _cli_loop.run_until_complete):
        yield


@pytest.fixture(autouse=True)
def _no_tty() -> Any:
    """Default to unattended. A test that wants the prompts asks for them."""
    with patch("sys.stdin.isatty", return_value=False):
        yield


@pytest.fixture
def store() -> ProfileStore:
    """A machine that has been through `setup` and provisioned one robot."""
    store = ProfileStore.from_env()
    store.save_broker(Broker(host="192.0.2.10"))
    store.save_ca(CA)
    store.save_client(pki.issue_client(CA, "whiskerless-test"))
    store.save_broker_certs(pki.issue_server(CA, "192.0.2.10"))
    store.save(RobotProfile(serial=Serial("LR4C123456"), name="Upstairs"))
    return store


def run(*argv: str) -> int:
    return main(list(argv))


# --- backing up ---------------------------------------------------------------
def test_a_backup_names_what_is_in_it(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Enough to know you grabbed the right file, without opening it."""
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    out = capsys.readouterr().out
    assert "test CA" in out
    assert "192.0.2.10:8883" in out
    assert "LR4C123456" in out


def test_a_backup_round_trips_the_whole_store(store: ProfileStore, tmp_path: Path) -> None:
    path = tmp_path / "b.tar.gz"
    assert run("backup", str(path), "--no-password") == 0
    files = backup.read(backup.load(path)).files
    assert files["ca/ca.key"].decode() == CA.key_pem
    assert "client/client.key" in files
    assert "broker/server.key" in files


def test_an_unencrypted_backup_says_what_is_in_the_clear(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    assert "Not encrypted" in capsys.readouterr().out


def test_a_backup_file_is_not_readable_by_anyone_else(
    store: ProfileStore, tmp_path: Path
) -> None:
    path = tmp_path / "b.tar.gz"
    run("backup", str(path), "--no-password")
    assert path.stat().st_mode & 0o777 == 0o600


def test_overwriting_a_looser_existing_file_tightens_it(
    store: ProfileStore, tmp_path: Path
) -> None:
    """O_CREAT's mode applies only when the file is created, so an existing
    world-readable file would otherwise keep its permissions."""
    path = tmp_path / "b.tar.gz"
    path.write_text("stale")
    path.chmod(0o644)
    assert run("backup", str(path), "--no-password", "--force") == 0
    assert path.stat().st_mode & 0o777 == 0o600


def test_a_directory_is_taken_as_where_to_put_it(store: ProfileStore, tmp_path: Path) -> None:
    assert run("backup", str(tmp_path), "--no-password") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz"))


def test_no_destination_writes_into_the_current_directory(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run("backup", "--no-password") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz"))


def test_an_encrypted_backup_is_named_for_what_it_is(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.tar.gz` that `tar` cannot open is a lie about the file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    assert run("backup") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz.enc"))


def test_an_existing_file_is_not_overwritten_by_accident(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "b.tar.gz"
    path.write_text("something else")
    assert run("backup", str(path), "--no-password") == 1
    assert "--force" in capsys.readouterr().err
    assert path.read_text() == "something else"


def test_force_overwrites(store: ProfileStore, tmp_path: Path) -> None:
    path = tmp_path / "b.tar.gz"
    path.write_text("something else")
    assert run("backup", str(path), "--no-password", "--force") == 0
    assert tarfile.is_tarfile(path)


def test_an_unwritable_destination_is_explained_not_traced(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    assert run("backup", str(locked / "b.tar.gz"), "--no-password") == 1
    assert "could not write" in capsys.readouterr().err


def test_backing_up_a_machine_with_nothing_set_up_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Judged on the contents, not on the directory: running any command stamps a
    layout marker into an empty store, and archiving that alone would report a
    successful backup of nothing."""
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 1
    assert "nothing to back up" in capsys.readouterr().err
    assert not (tmp_path / "b.tar.gz").exists()


def test_a_machine_with_nothing_set_up_is_not_asked_for_a_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It has nothing to encrypt, so the prompt would be a question about a file
    that is never going to be written."""
    assert run("backup", str(tmp_path / "b.tar.gz")) == 1
    assert "nothing to back up" in capsys.readouterr().err


# --- the password ---------------------------------------------------------------
def test_an_unattended_run_will_not_quietly_write_a_key_in_the_clear(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one decision that must never be made by default. A cron job that
    writes a signing key unencrypted should have had to say so."""
    assert run("backup", str(tmp_path / "b.tar.gz")) == 1
    error = capsys.readouterr().err
    assert "WHISKERLESS_BACKUP_PASSWORD" in error
    assert "--no-password" in error
    assert not (tmp_path / "b.tar.gz").exists()


def test_a_password_can_come_from_the_environment(store: ProfileStore, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    path = tmp_path / "b.enc"
    assert run("backup", str(path)) == 0
    assert backup.is_encrypted(path.read_bytes())


def test_a_typed_password_is_asked_for_twice(store: ProfileStore, tmp_path: Path) -> None:
    path = tmp_path / "b.enc"
    with patch("sys.stdin.isatty", return_value=True), patch(
        "whiskerless.cli._ask_secret", side_effect=["one", "two", "three", "three"]
    ):
        assert run("backup", str(path)) == 0
    assert backup.read(backup.load(path), password="three").broker() is not None


def test_pressing_enter_at_the_password_prompt_writes_a_plain_archive(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "b.tar.gz"
    with patch("sys.stdin.isatty", return_value=True), patch(
        "whiskerless.cli._ask_secret", return_value=""
    ):
        assert run("backup", str(path)) == 0
    assert "Not encrypted" in capsys.readouterr().out


def test_an_encrypted_backup_warns_that_the_password_is_the_backup(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    assert run("backup", str(tmp_path / "b.enc")) == 0
    assert "Nothing can recover that password" in capsys.readouterr().out


# --- restoring ------------------------------------------------------------------
def _backup_file(store: ProfileStore, path: Path, password: str | None = None) -> Path:
    path.write_bytes(backup.create(store.root, password=password))
    return path


def test_restoring_onto_a_fresh_machine(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _backup_file(store, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    restored = ProfileStore.from_env()
    assert restored.load_ca().cert_pem == CA.cert_pem
    assert restored.load_broker().host == "192.0.2.10"
    assert restored.load("LR4C123456").name == "Upstairs"
    assert "LR4C123456" in capsys.readouterr().out


def test_restoring_points_at_the_files_the_broker_still_needs(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A restored machine is not a working broker — the server certificate has
    to be installed there too, and this is the moment somebody will forget."""
    archive = _backup_file(store, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    run("restore", str(archive))
    assert "cafile" in capsys.readouterr().out


def test_a_backup_without_broker_certificates_points_at_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Somebody who brought their own CA never generated one here, and naming
    files that do not exist sends them hunting for something that never was."""
    source = ProfileStore(tmp_path / "source")
    source.save_broker(Broker(host="192.0.2.10"))
    source.save_ca_cert_only(CA.cert_pem)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    out = capsys.readouterr().out
    assert "cafile" not in out
    assert "certificate only, cannot issue" in out


def test_a_layout_marker_alone_is_not_a_setup_to_be_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running any command at all stamps that marker, so the ordinary state of a
    machine that has done nothing yet is a store directory with one file in it.
    Refusing to restore over that would send somebody hunting for the setup they
    are certain they never made — and it must leave no `.replaced-` litter."""
    source = ProfileStore(tmp_path / "source")
    source.save_ca(CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    stamped = tmp_path / "stamped-home"
    stamped.mkdir()
    monkeypatch.setenv("WHISKERLESS_HOME", str(stamped))
    ProfileStore.from_env()
    assert (stamped / ".layout").is_file()

    assert run("restore", str(archive)) == 0
    assert ProfileStore.from_env().load_ca().cert_pem == CA.cert_pem
    assert not list(tmp_path.glob("stamped-home.replaced-*"))


def test_an_encrypted_backup_restores_with_its_password(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _backup_file(store, tmp_path / "b.enc", password="hunter2")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    assert run("restore", str(archive)) == 0
    assert ProfileStore.from_env().load_ca().cert_pem == CA.cert_pem


def test_an_encrypted_backup_prompts_for_its_password(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _backup_file(store, tmp_path / "b.enc", password="hunter2")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch(
        "whiskerless.cli._ask_secret", return_value="hunter2"
    ):
        assert run("restore", str(archive)) == 0


def test_an_encrypted_backup_with_nobody_to_ask_says_so(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _backup_file(store, tmp_path / "b.enc", password="hunter2")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 1
    assert "WHISKERLESS_BACKUP_PASSWORD" in capsys.readouterr().err


def test_a_backup_from_a_newer_whiskerless_is_refused(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Restoring it would put files this build cannot read into the one place it
    reads on every command."""
    (store.root / ".layout").write_text("99\n")
    archive = _backup_file(store, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 1
    assert "upgrade whiskerless" in capsys.readouterr().err


def test_a_backup_from_before_layout_markers_is_migrated_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ProfileStore(tmp_path / "source")
    source.save_broker(Broker(host="192.0.2.10"))
    source.save_ca(CA)
    (source.root / ".layout").unlink()
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    assert ProfileStore.from_env().layout_version() == 1


# --- restoring over something ---------------------------------------------------
def test_restoring_over_a_different_ca_names_the_robots_it_would_strand(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The consequential case. Each of those robots is a walk with a laptop."""
    source = ProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    assert run("restore", str(archive)) == 1
    error = capsys.readouterr().err
    assert "DIFFERENT" in error
    assert "LR4C123456" in error
    assert store.load_ca().cert_pem == CA.cert_pem


def test_restoring_the_same_ca_says_nothing_would_be_stranded(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = _backup_file(store, tmp_path / "b.tar.gz")
    assert run("restore", str(archive)) == 1
    assert "no robot would be stranded" in capsys.readouterr().err


def test_restoring_over_a_store_with_no_ca_says_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = ProfileStore(tmp_path / "source")
    source.save_ca(CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    half = ProfileStore.from_env()
    half.save_broker(Broker(host="192.0.2.99"))
    assert run("restore", str(archive)) == 1
    assert "no certificate authority of its own" in capsys.readouterr().err


def test_force_moves_the_old_setup_aside_rather_than_deleting_it(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What is displaced may be the only copy of a key that robots still trust."""
    source = ProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    source.save_broker(Broker(host="192.0.2.99"))
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    assert run("restore", str(archive), "--force") == 0

    displaced = sorted(store.root.parent.glob(f"{store.root.name}.replaced-*"))
    assert len(displaced) == 1
    assert (displaced[0] / "ca" / "ca.key").read_text() == CA.key_pem
    assert ProfileStore.from_env().load_ca().cert_pem == OTHER_CA.cert_pem
    assert str(displaced[0]) in capsys.readouterr().out


def test_a_second_restore_in_the_same_second_does_not_collide(
    store: ProfileStore, tmp_path: Path
) -> None:
    """The move-aside name is timestamped to the second, and two restores a
    moment apart must not have the first one clobber the second."""
    source = ProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    with patch("whiskerless.cli.datetime") as clock:
        clock.now.return_value.strftime.return_value = "20260101-000000"
        assert run("restore", str(archive), "--force") == 0
        assert run("restore", str(archive), "--force") == 0
    assert len(sorted(store.root.parent.glob(f"{store.root.name}.replaced-*"))) == 2


def test_restoring_a_file_that_is_not_a_backup_is_explained_not_traced(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    junk = tmp_path / "holiday.jpg"
    junk.write_bytes(b"\xff\xd8\xff\xe0not a tarball")
    assert run("restore", str(junk)) == 1
    assert "not a readable whiskerless backup" in capsys.readouterr().err


# --- not losing things ----------------------------------------------------------
def test_a_store_with_only_the_ca_key_left_can_still_be_rescued(
    store: ProfileStore, tmp_path: Path
) -> None:
    """A half-deleted store is exactly when the one unregenerable file has to
    still be reachable — everything else in here can be rebuilt."""
    for stray in store.root.rglob("*"):
        if stray.is_file() and stray != store.ca_key_path:
            stray.unlink()
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    assert backup.read(backup.load(tmp_path / "b.tar.gz")).files["ca/ca.key"].decode() == CA.key_pem


def test_a_ca_that_cannot_sign_is_called_out(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The container's own checks prove the file opened, not that what came out
    of it works. A truncated key is copied faithfully and reported as a success."""
    store.ca_key_path.write_text(CA.key_pem[:200])
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    assert "cannot sign anything" in capsys.readouterr().err


def test_a_mismatched_pair_in_a_backup_is_called_out_on_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = ProfileStore(tmp_path / "source")
    source.save_ca(pki.KeyPair(cert_pem=CA.cert_pem, key_pem=OTHER_CA.key_pem))
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    assert "cannot sign anything" in capsys.readouterr().err


def test_a_failed_write_does_not_destroy_the_backup_it_was_replacing(
    store: ProfileStore, tmp_path: Path
) -> None:
    """--force targets what may be the only good backup on the machine. Writing
    in place would leave neither copy when the disk fills."""
    path = tmp_path / "b.tar.gz"
    good = backup.create(store.root)
    path.write_bytes(good)
    with patch("whiskerless.cli.os.replace", side_effect=OSError(28, "No space left on device")):
        assert run("backup", str(path), "--no-password", "--force") == 1
    assert path.read_bytes() == good
    assert not list(tmp_path.glob(".*.tmp"))


def test_a_failed_restore_leaves_the_existing_setup_alone(
    store: ProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unpacking takes as long as it takes and can run out of disk halfway."""
    source = ProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    with patch.object(backup.Archive, "write_into", side_effect=OSError(28, "No space left")):
        assert run("restore", str(archive), "--force") == 1
    assert store.load_ca().cert_pem == CA.cert_pem
    assert "could not restore" in capsys.readouterr().err


def test_a_failed_swap_puts_the_displaced_setup_straight_back(
    store: ProfileStore, tmp_path: Path
) -> None:
    """The window between moving the old store away and the new one in is two
    renames wide, and this is what happens if the second one loses."""
    source = ProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    real, seen = Path.rename, []

    def flaky(self: Path, target: Any) -> Any:
        seen.append(target)
        if len(seen) == 2:  # staged -> root, the moment the store does not exist
            raise OSError(28, "No space left on device")
        return real(self, target)

    with patch.object(Path, "rename", flaky):
        assert run("restore", str(archive), "--force") == 1
    assert store.load_ca().cert_pem == CA.cert_pem
    assert not list(store.root.parent.glob(f"{store.root.name}.replaced-*"))
    assert not list(store.root.parent.glob(f"{store.root.name}.incoming-*"))


def test_a_backup_will_not_be_written_inside_the_store_it_copies(
    store: ProfileStore, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each one would swallow the last, and running the command from inside the
    store is all it takes."""
    monkeypatch.chdir(store.root)
    assert run("backup", "--no-password") == 1
    assert "inside the store" in capsys.readouterr().err
    assert not list(store.root.glob("whiskerless-backup-*"))


def test_an_unreadable_ca_in_a_backup_is_reported_not_traced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A restore is not the moment to die on a summary line."""
    source = ProfileStore(tmp_path / "source")
    source.save_ca_cert_only("-----BEGIN CERTIFICATE-----\nnot really\n")
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    assert "unreadable" in capsys.readouterr().out
