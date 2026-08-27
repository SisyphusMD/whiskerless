"""`whiskerless backup` and `whiskerless restore` from the outside.

The archive format is pinned in tests/test_backup.py. What matters here is the
judgement around it: never write a signing key in the clear by accident, and
never replace a working setup without saying which robots it would strand.
"""

from __future__ import annotations

import asyncio
import errno
import os
import stat
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from whiskerless import backup, pki
from whiskerless.cli import _write_bytes_private, main
from whiskerless.robot_profiles import Broker, RobotProfile, RobotProfileStore, Serial

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
def store() -> RobotProfileStore:
    """A machine that has been through `setup` and provisioned one robot."""
    store = RobotProfileStore.from_env()
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
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Enough to know you grabbed the right file, without opening it."""
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    out = capsys.readouterr().out
    assert "test CA" in out
    assert "192.0.2.10:8883" in out
    assert "LR4C123456" in out


def test_a_backup_round_trips_the_whole_store(store: RobotProfileStore, tmp_path: Path) -> None:
    path = tmp_path / "b.tar.gz"
    assert run("backup", str(path), "--no-password") == 0
    files = backup.read(backup.load(path)).files
    assert files["ca/ca.key"].decode() == CA.key_pem
    assert "client/client.key" in files
    assert "broker/server.key" in files


def test_an_unencrypted_backup_says_what_is_in_the_clear(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    assert "Not encrypted" in capsys.readouterr().out


def test_a_backup_file_is_not_readable_by_anyone_else(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    path = tmp_path / "b.tar.gz"
    run("backup", str(path), "--no-password")
    assert path.stat().st_mode & 0o777 == 0o600


def test_overwriting_a_looser_existing_file_tightens_it(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """O_CREAT's mode applies only when the file is created, so an existing
    world-readable file would otherwise keep its permissions."""
    path = tmp_path / "b.tar.gz"
    path.write_text("stale")
    path.chmod(0o644)
    assert run("backup", str(path), "--no-password", "--force") == 0
    assert path.stat().st_mode & 0o777 == 0o600


def test_a_directory_is_taken_as_where_to_put_it(store: RobotProfileStore, tmp_path: Path) -> None:
    assert run("backup", str(tmp_path), "--no-password") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz"))


def test_no_destination_writes_into_the_current_directory(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run("backup", "--no-password") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz"))


def test_an_encrypted_backup_is_named_for_what_it_is(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.tar.gz` that `tar` cannot open is a lie about the file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    assert run("backup") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz.enc"))


def test_a_backup_carries_when_it_was_made_in_its_name(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Modification time does not survive the journey a backup is *for* — copied
    to a stick, synced through cloud storage, pulled out of a snapshot, every
    file arrives stamped with whenever that copy happened. The name is the only
    part that still says when it was made."""
    assert run("backup", str(tmp_path), "--no-password") == 0
    name = next(iter(tmp_path.glob("whiskerless-backup-*"))).name
    stamp = name.removeprefix("whiskerless-backup-").removesuffix(".tar.gz")
    assert datetime.strptime(stamp, "%Y%m%d-%H%M%S")


def test_a_second_backup_never_clobbers_the_first(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Before and after a change is the obvious reason to back up twice, and the
    earlier file may be the one from before the store was damaged."""
    assert run("backup", str(tmp_path), "--no-password") == 0
    first = next(iter(tmp_path.glob("whiskerless-backup-*.tar.gz")))
    original = first.read_bytes()

    assert run("backup", str(tmp_path), "--no-password") == 0
    assert first.read_bytes() == original
    assert len(list(tmp_path.glob("whiskerless-backup-*.tar.gz"))) == 2


def test_two_backups_inside_one_second_are_numbered(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """A scripted loop can manage that; a person cannot. The timestamp does the
    work and the counter only covers the tie."""
    with patch("whiskerless.backup.datetime") as clock:
        clock.now.return_value.strftime.return_value = "20260816-204915"
        assert run("backup", str(tmp_path), "--no-password") == 0
        assert run("backup", str(tmp_path), "--no-password") == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "whiskerless-backup-20260816-204915-2.tar.gz",
        "whiskerless-backup-20260816-204915.tar.gz",
    ]


def test_a_name_is_claimed_by_creating_it_not_by_looking(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """Two backups into one folder could otherwise both see the same candidate
    free, and the second would discard the first — the loss the numbering is
    there to prevent."""
    taken: list[Path] = []
    real = os.open

    def racy(path: Any, flags: int, *rest: Any) -> Any:
        # Whoever else is backing up wins the first name, once.
        if flags & os.O_EXCL and not taken:
            taken.append(Path(path))
            Path(path).write_bytes(b"the other run got here first")
            raise FileExistsError(17, "File exists")
        return real(path, flags, *rest)

    with patch("whiskerless.cli.os.open", racy):
        assert run("backup", str(tmp_path), "--no-password") == 0
    assert taken[0].read_bytes() == b"the other run got here first"
    assert len(list(tmp_path.glob("whiskerless-backup-*"))) == 2


def test_a_folder_with_no_free_name_is_explained_not_looped(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("whiskerless.cli.os.open", side_effect=FileExistsError(17, "File exists")):
        assert run("backup", str(tmp_path), "--no-password") == 1
    assert "could not find a free filename" in capsys.readouterr().err


def test_a_failed_write_removes_the_placeholder_it_reserved(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """The claim is a real, empty file — leaving it behind would look like a
    backup and restore as nothing."""
    with patch("whiskerless.cli.os.replace", side_effect=OSError(28, "No space left")):
        assert run("backup", str(tmp_path), "--no-password") == 1
    assert not list(tmp_path.glob("whiskerless-backup-*"))


def test_the_numbering_keeps_the_encrypted_suffix(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    with patch("whiskerless.backup.datetime") as clock:
        clock.now.return_value.strftime.return_value = "20260816-204915"
        assert run("backup", str(tmp_path)) == 0
        assert run("backup", str(tmp_path)) == 0
    assert any(path.name.endswith("-2.tar.gz.enc") for path in tmp_path.iterdir())


def test_an_existing_file_is_not_overwritten_by_accident(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "b.tar.gz"
    path.write_text("something else")
    assert run("backup", str(path), "--no-password") == 1
    assert "--force" in capsys.readouterr().err
    assert path.read_text() == "something else"


def test_force_overwrites(store: RobotProfileStore, tmp_path: Path) -> None:
    path = tmp_path / "b.tar.gz"
    path.write_text("something else")
    assert run("backup", str(path), "--no-password", "--force") == 0
    assert tarfile.is_tarfile(path)


def test_an_unwritable_destination_is_explained_not_traced(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure is injected rather than staged with directory permissions:
    root ignores a mode of 0o500 and writes anyway, so a permissions-based
    version of this passes for a developer and fails on any CI runner that
    builds as root — which is most of them, including this project's."""
    with patch(
        "whiskerless.cli._write_bytes_private", side_effect=OSError(13, "Permission denied")
    ):
        assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 1
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
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one decision that must never be made by default. A cron job that
    writes a signing key unencrypted should have had to say so."""
    assert run("backup", str(tmp_path / "b.tar.gz")) == 1
    error = capsys.readouterr().err
    assert "WHISKERLESS_BACKUP_PASSWORD" in error
    assert "--no-password" in error
    assert not (tmp_path / "b.tar.gz").exists()


def test_a_password_can_come_from_the_environment(store: RobotProfileStore, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    path = tmp_path / "b.enc"
    assert run("backup", str(path)) == 0
    assert backup.is_encrypted(path.read_bytes())


def test_a_typed_password_is_asked_for_twice(store: RobotProfileStore, tmp_path: Path) -> None:
    path = tmp_path / "b.enc"
    with patch("sys.stdin.isatty", return_value=True), patch(
        "whiskerless.cli._ask_secret", side_effect=["one", "two", "three", "three"]
    ):
        assert run("backup", str(path)) == 0
    assert backup.read(backup.load(path), password="three").broker() is not None


def test_pressing_enter_at_the_password_prompt_writes_a_plain_archive(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "b.tar.gz"
    with patch("sys.stdin.isatty", return_value=True), patch(
        "whiskerless.cli._ask_secret", return_value=""
    ):
        assert run("backup", str(path)) == 0
    assert "Not encrypted" in capsys.readouterr().out


def test_an_encrypted_backup_warns_that_the_password_is_the_backup(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    assert run("backup", str(tmp_path / "b.enc")) == 0
    assert "Nothing can recover that password" in capsys.readouterr().out


# --- being asked where -----------------------------------------------------------
def test_where_to_put_it_is_asked_rather_than_assumed(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of a backup is that it ends up somewhere else, and silently
    dropping it wherever the terminal was sitting is how it lands on the same
    disk as the thing it insures."""
    monkeypatch.chdir(tmp_path)
    elsewhere = tmp_path / "Documents"
    elsewhere.mkdir()
    with patch("sys.stdin.isatty", return_value=True), patch(
        "builtins.input", return_value=str(elsewhere)
    ), patch("whiskerless.cli._ask_secret", return_value=""):
        assert run("backup") == 0
    assert list(elsewhere.glob("whiskerless-backup-*.tar.gz"))


def test_pressing_enter_takes_the_directory_you_are_standing_in(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("sys.stdin.isatty", return_value=True), patch(
        "builtins.input", return_value=""
    ), patch("whiskerless.cli._ask_secret", return_value=""):
        assert run("backup") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz"))


def test_a_destination_that_cannot_exist_is_caught_at_the_prompt(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Re-asked, not fatal — and caught before a passphrase is typed twice for a
    file that was never going to be written."""
    monkeypatch.chdir(tmp_path)
    with patch("sys.stdin.isatty", return_value=True), patch(
        "builtins.input", side_effect=[str(tmp_path / "nope" / "b.tar.gz"), str(tmp_path)]
    ), patch("whiskerless.cli._ask_secret", return_value="") as secret:
        assert run("backup") == 0
    assert "there is no directory" in capsys.readouterr().err
    assert secret.call_count == 1


def test_the_destination_prompt_takes_a_filename_too(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Where should it go" is answered with a full name as often as a folder."""
    monkeypatch.chdir(tmp_path)
    with patch("sys.stdin.isatty", return_value=True), patch(
        "builtins.input", return_value=str(tmp_path / "before-the-rotation.tar.gz")
    ), patch("whiskerless.cli._ask_secret", return_value=""):
        assert run("backup") == 0
    assert (tmp_path / "before-the-rotation.tar.gz").is_file()


def test_a_deleted_working_directory_does_not_break_the_restore_prompt(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing what is nearby is a convenience; failing to reach it must not
    stop somebody typing the path they already know."""
    archive = _backup_file(store, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch(
        "whiskerless.cli.Path.cwd", side_effect=OSError("no such directory")
    ), patch("builtins.input", return_value=str(archive)):
        assert run("restore") == 0
    assert RobotProfileStore.from_env().load_ca().cert_pem == CA.cert_pem


def test_which_backup_to_restore_is_offered_not_retyped(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """You just copied one onto a fresh machine; retyping a filename with a
    timestamp in it is not the interaction that moment deserves.

    Newest first, ordered by the NAME. On a machine somebody is restoring onto,
    every file was copied there at once, so modification time would put them in
    no order at all — the timestamp in the name is the one that travelled."""
    older = _backup_file(store, tmp_path / "whiskerless-backup-20260101-090000.tar.gz")
    newer = tmp_path / "whiskerless-backup-20260816-204915.tar.gz"
    newer.write_bytes(older.read_bytes())
    os.utime(newer, (0, 0))  # oldest on disk, newest by name
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="1"):
        assert run("restore") == 0
    out = capsys.readouterr().out
    assert out.index(newer.name) < out.index(older.name)
    assert str(newer) in out
    assert RobotProfileStore.from_env().load_ca().cert_pem == CA.cert_pem


def test_the_listing_reads_the_counter_as_a_number_not_as_text(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plain alphabetical order gets both halves wrong: `-2` sorts before `-10`,
    and the unsuffixed name of a pair sorts AFTER its `-2` sibling because `.`
    follows `-` in ASCII. Either way the oldest backup made in that second would
    be offered as number 1, and restoring the wrong one strands robots."""
    for name in (
        "whiskerless-backup-20260816-204915.tar.gz",
        "whiskerless-backup-20260816-204915-2.tar.gz",
        "whiskerless-backup-20260816-204915-10.tar.gz",
    ):
        _backup_file(store, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="1"):
        assert run("restore") == 0
    listed = [line for line in capsys.readouterr().out.splitlines() if "whiskerless-backup-" in line]
    assert [line.split()[1] for line in listed[:3]] == [
        "whiskerless-backup-20260816-204915-10.tar.gz",
        "whiskerless-backup-20260816-204915-2.tar.gz",
        "whiskerless-backup-20260816-204915.tar.gz",
    ]


def test_a_renamed_backup_is_listed_last_rather_than_guessed_at(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _backup_file(store, tmp_path / "whiskerless-backup-before-the-rotation.tar.gz")
    _backup_file(store, tmp_path / "whiskerless-backup-20260101-090000.tar.gz")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="1"):
        assert run("restore") == 0
    out = capsys.readouterr().out
    assert out.index("20260101-090000") < out.index("before-the-rotation")


def test_the_restore_prompt_still_takes_a_path(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The listing only covers files whiskerless named, in one directory."""
    archive = _backup_file(store, tmp_path / "somewhere-else.bak")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch(
        "builtins.input", return_value=str(archive)
    ):
        assert run("restore") == 0
    assert RobotProfileStore.from_env().load_ca().cert_pem == CA.cert_pem


def test_a_mistyped_path_at_the_restore_prompt_is_re_asked(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _backup_file(store, tmp_path / "b.bak")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch(
        "builtins.input", side_effect=[str(tmp_path / "typo.bak"), str(archive)]
    ):
        assert run("restore") == 0
    assert "typo.bak" in capsys.readouterr().err


def test_restore_with_no_path_and_nobody_to_ask_says_which(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It used to be argparse's exit-2 "the following arguments are required"."""
    assert run("restore") == 1
    assert "which backup?" in capsys.readouterr().err


def test_an_unattended_backup_still_writes_where_it_stands(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prompt must never be the thing that breaks a scripted run."""
    monkeypatch.chdir(tmp_path)
    assert run("backup", "--no-password") == 0
    assert list(tmp_path.glob("whiskerless-backup-*.tar.gz"))


# --- restoring ------------------------------------------------------------------
def _backup_file(store: RobotProfileStore, path: Path, password: str | None = None) -> Path:
    path.write_bytes(backup.create(store.root, password=password))
    return path


def test_restoring_onto_a_fresh_machine(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _backup_file(store, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    restored = RobotProfileStore.from_env()
    assert restored.load_ca().cert_pem == CA.cert_pem
    assert restored.load_broker().host == "192.0.2.10"
    assert restored.load("LR4C123456").name == "Upstairs"
    assert "LR4C123456" in capsys.readouterr().out


def test_restoring_points_at_the_files_the_broker_still_needs(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    source = RobotProfileStore(tmp_path / "source")
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
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca(CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    stamped = tmp_path / "stamped-home"
    stamped.mkdir()
    monkeypatch.setenv("WHISKERLESS_HOME", str(stamped))
    RobotProfileStore.from_env()
    assert (stamped / ".layout").is_file()

    assert run("restore", str(archive)) == 0
    assert RobotProfileStore.from_env().load_ca().cert_pem == CA.cert_pem
    assert not list(tmp_path.glob("stamped-home.replaced-*"))


def test_an_encrypted_backup_restores_with_its_password(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _backup_file(store, tmp_path / "b.enc", password="hunter2")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    monkeypatch.setenv("WHISKERLESS_BACKUP_PASSWORD", "hunter2")
    assert run("restore", str(archive)) == 0
    assert RobotProfileStore.from_env().load_ca().cert_pem == CA.cert_pem


def test_an_encrypted_backup_prompts_for_its_password(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _backup_file(store, tmp_path / "b.enc", password="hunter2")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    with patch("sys.stdin.isatty", return_value=True), patch(
        "whiskerless.cli._ask_secret", return_value="hunter2"
    ):
        assert run("restore", str(archive)) == 0


def test_an_encrypted_backup_with_nobody_to_ask_says_so(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _backup_file(store, tmp_path / "b.enc", password="hunter2")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 1
    assert "WHISKERLESS_BACKUP_PASSWORD" in capsys.readouterr().err


def test_a_backup_from_a_newer_whiskerless_is_refused(
    store: RobotProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    source = RobotProfileStore(tmp_path / "source")
    source.save_broker(Broker(host="192.0.2.10"))
    source.save_ca(CA)
    (source.root / ".layout").unlink()
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    assert RobotProfileStore.from_env().layout_version() == 1


# --- restoring over something ---------------------------------------------------
def test_restoring_over_a_different_ca_names_the_robots_it_would_strand(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The consequential case. Each of those robots is a walk with a laptop."""
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    assert run("restore", str(archive)) == 1
    error = capsys.readouterr().err
    assert "DIFFERENT" in error
    assert "LR4C123456" in error
    assert store.load_ca().cert_pem == CA.cert_pem


def test_restoring_the_same_ca_says_nothing_would_be_stranded(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = _backup_file(store, tmp_path / "b.tar.gz")
    assert run("restore", str(archive)) == 1
    assert "no robot would be stranded" in capsys.readouterr().err


def test_restoring_over_a_store_with_no_ca_says_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca(CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    half = RobotProfileStore.from_env()
    half.save_broker(Broker(host="192.0.2.99"))
    assert run("restore", str(archive)) == 1
    assert "no certificate authority of its own" in capsys.readouterr().err


def test_force_moves_the_old_setup_aside_rather_than_deleting_it(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What is displaced may be the only copy of a key that robots still trust."""
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    source.save_broker(Broker(host="192.0.2.99"))
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    assert run("restore", str(archive), "--force") == 0

    displaced = sorted(store.root.parent.glob(f"{store.root.name}.replaced-*"))
    assert len(displaced) == 1
    assert (displaced[0] / "ca" / "ca.key").read_text() == CA.key_pem
    assert RobotProfileStore.from_env().load_ca().cert_pem == OTHER_CA.cert_pem
    assert str(displaced[0]) in capsys.readouterr().out


def test_a_second_restore_in_the_same_second_does_not_collide(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """The move-aside name is timestamped to the second, and two restores a
    moment apart must not have the first one clobber the second."""
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    with patch("whiskerless.cli.datetime") as clock:
        clock.now.return_value.strftime.return_value = "20260101-000000"
        assert run("restore", str(archive), "--force") == 0
        assert run("restore", str(archive), "--force") == 0
    assert len(sorted(store.root.parent.glob(f"{store.root.name}.replaced-*"))) == 2


def test_restoring_a_file_that_is_not_a_backup_is_explained_not_traced(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    junk = tmp_path / "holiday.jpg"
    junk.write_bytes(b"\xff\xd8\xff\xe0not a tarball")
    assert run("restore", str(junk)) == 1
    assert "not a readable whiskerless backup" in capsys.readouterr().err


# --- not losing things ----------------------------------------------------------
def test_a_store_with_only_the_ca_key_left_can_still_be_rescued(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """A half-deleted store is exactly when the one unregenerable file has to
    still be reachable — everything else in here can be rebuilt."""
    for stray in store.root.rglob("*"):
        if stray.is_file() and stray != store.ca_key_path:
            stray.unlink()
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    assert backup.read(backup.load(tmp_path / "b.tar.gz")).files["ca/ca.key"].decode() == CA.key_pem


def test_a_ca_that_cannot_sign_is_called_out(
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The container's own checks prove the file opened, not that what came out
    of it works. A truncated key is copied faithfully and reported as a success."""
    store.ca_key_path.write_text(CA.key_pem[:200])
    assert run("backup", str(tmp_path / "b.tar.gz"), "--no-password") == 0
    assert "cannot sign anything" in capsys.readouterr().err


def test_a_mismatched_pair_in_a_backup_is_called_out_on_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca(pki.KeyPair(cert_pem=CA.cert_pem, key_pem=OTHER_CA.key_pem))
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    assert "cannot sign anything" in capsys.readouterr().err


def test_a_failed_write_does_not_destroy_the_backup_it_was_replacing(
    store: RobotProfileStore, tmp_path: Path
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
    store: RobotProfileStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unpacking takes as long as it takes and can run out of disk halfway."""
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca(OTHER_CA)
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    with patch.object(backup.Archive, "write_into", side_effect=OSError(28, "No space left")):
        assert run("restore", str(archive), "--force") == 1
    assert store.load_ca().cert_pem == CA.cert_pem
    assert "could not restore" in capsys.readouterr().err


def test_a_failed_swap_puts_the_displaced_setup_straight_back(
    store: RobotProfileStore, tmp_path: Path
) -> None:
    """The window between moving the old store away and the new one in is two
    renames wide, and this is what happens if the second one loses."""
    source = RobotProfileStore(tmp_path / "source")
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
    store: RobotProfileStore, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
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
    source = RobotProfileStore(tmp_path / "source")
    source.save_ca_cert_only("-----BEGIN CERTIFICATE-----\nnot really\n")
    archive = _backup_file(source, tmp_path / "b.tar.gz")
    monkeypatch.setenv("WHISKERLESS_HOME", str(tmp_path / "fresh"))
    assert run("restore", str(archive)) == 0
    assert "unreadable" in capsys.readouterr().out


def test_a_backup_survives_a_filesystem_that_cannot_fsync_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Some network and FUSE-backed destinations reject a directory fsync. The archive is already
    committed by then, so raising made the caller delete it — turning "cannot promise durability"
    into "backups here always fail"."""

    real = os.fsync

    def _refuse(fd: int) -> None:
        """Refuse only the DIRECTORY fsync — the file's own flush must still be real, or the test
        would pass for a write that never reached the disk at all."""
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.ENOTSUP, "not supported")
        real(fd)

    monkeypatch.setattr(os, "fsync", _refuse)
    target = tmp_path / "out" / "backup.wbk"
    _write_bytes_private(target, b"payload")
    assert target.read_bytes() == b"payload"


def test_a_real_fsync_failure_is_still_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the "this filesystem cannot do that" errnos are tolerated; an EIO means the write is
    genuinely in doubt and must not be reported as a finished backup."""

    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(errno.EIO, "io")))
    with pytest.raises(OSError):
        _write_bytes_private(tmp_path / "b.wbk", b"payload")


def test_a_write_only_destination_still_keeps_the_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drop-box directory may allow write and execute but not read, and opening it O_RDONLY for
    the durability fsync raises EACCES — after the archive has already been committed."""

    real_open = os.open

    def _refuse_dir(path, flags, *args, **kwargs):
        if Path(path).is_dir():
            raise OSError(errno.EACCES, "permission denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", _refuse_dir)
    target = tmp_path / "drop" / "backup.wbk"
    target.parent.mkdir(parents=True)
    _write_bytes_private(target, b"payload")
    assert target.read_bytes() == b"payload"
