"""The archive format, and everything that must not survive contact with it.

A backup is opened once, years later, on a bad day. Two properties matter more
than anything else here: what goes in comes back out byte for byte, and an
archive from somewhere untrustworthy cannot write outside the directory it is
restored into.
"""

from __future__ import annotations

import base64
import io
import json
import tarfile
from pathlib import Path

import pytest

from whiskerless import backup
from whiskerless.exceptions import WhiskerlessError


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A store shaped like a real one, with a robot and a CA in it."""
    root = tmp_path / "whiskerless"
    (root / "ca").mkdir(parents=True)
    (root / "robots" / "LR4C123456").mkdir(parents=True)
    (root / ".layout").write_text("1\n")
    (root / "broker.json").write_text('{"host": "192.0.2.10", "port": 8883}')
    (root / "ca" / "ca.crt").write_text("-----BEGIN CERTIFICATE-----\nx\n")
    (root / "ca" / "ca.key").write_text("-----BEGIN RSA PRIVATE KEY-----\ny\n")
    (root / "robots" / "LR4C123456" / "profile.json").write_text('{"serial": "LR4C123456"}')
    return root


def _tar(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


# --- the round trip -----------------------------------------------------------
def test_everything_that_went_in_comes_back_out(store: Path, tmp_path: Path) -> None:
    archive = backup.read(backup.create(store))
    archive.write_into(tmp_path / "restored")
    for original in store.rglob("*"):
        if original.is_file():
            copy = tmp_path / "restored" / original.relative_to(store)
            assert copy.read_bytes() == original.read_bytes()


def test_a_password_round_trips_too(store: Path) -> None:
    sealed = backup.create(store, password="hunter2")
    assert backup.is_encrypted(sealed)
    assert backup.read(sealed, password="hunter2").broker() == "192.0.2.10"


def test_a_plain_archive_is_an_ordinary_tarball(store: Path) -> None:
    """It will be opened by `tar` one day, on a machine with no whiskerless."""
    with tarfile.open(fileobj=io.BytesIO(backup.create(store))) as tar:
        names = tar.getnames()
    # Every member under one directory, so extracting by hand does not scatter
    # `.layout`, `ca/` and `robots/` into whatever directory somebody is in.
    assert all(name.startswith("whiskerless/") for name in names)
    assert "whiskerless/ca/ca.key" in names


def test_the_archive_carries_no_account_name(store: Path) -> None:
    """These get handed around; the operator's login is nobody else's business."""
    with tarfile.open(fileobj=io.BytesIO(backup.create(store))) as tar:
        assert {(m.uname, m.gname, m.uid) for m in tar.getmembers()} == {("", "", 0)}


def test_restoring_leaves_nothing_group_readable(store: Path, tmp_path: Path) -> None:
    """One of these files signs certificates. Whatever modes the archive picked up
    on its travels are not the ones it gets back."""
    root = tmp_path / "restored"
    backup.read(backup.create(store)).write_into(root)
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "ca").stat().st_mode & 0o777 == 0o700
    assert (root / "ca" / "ca.key").stat().st_mode & 0o777 == 0o600


def test_restoring_over_a_looser_existing_file_tightens_it(store: Path, tmp_path: Path) -> None:
    root = tmp_path / "restored"
    (root / "ca").mkdir(parents=True)
    (root / "ca" / "ca.key").write_text("old")
    (root / "ca" / "ca.key").chmod(0o644)
    backup.read(backup.create(store)).write_into(root)
    assert (root / "ca" / "ca.key").stat().st_mode & 0o777 == 0o600


def test_a_symlink_in_the_store_is_skipped_not_followed(store: Path, tmp_path: Path) -> None:
    """A link out of the store would pull an arbitrary file into an archive that
    gets handed around."""
    secret = tmp_path / "id_rsa"
    secret.write_text("not yours")
    (store / "sneaky").symlink_to(secret)
    assert "sneaky" not in backup.read(backup.create(store)).files


# --- what a backup can say about itself ---------------------------------------
def test_a_backup_names_its_broker_ca_and_robots(store: Path) -> None:
    archive = backup.read(backup.create(store))
    assert archive.layout_version() == 1
    assert archive.robots() == ("LR4C123456",)
    assert archive.ca_cert_pem() is not None


@pytest.mark.parametrize("layout", ["", "not a number", "\x00\xff"])
def test_an_unreadable_layout_marker_reads_as_pre_versioning(store: Path, layout: str) -> None:
    """Layout 0 means "migrate it forward", which is the right answer for a
    marker somebody mangled as well as for one that predates markers."""
    (store / ".layout").write_text(layout)
    assert backup.read(backup.create(store)).layout_version() == 0


def test_a_missing_layout_marker_reads_as_pre_versioning(store: Path) -> None:
    (store / ".layout").unlink()
    assert backup.read(backup.create(store)).layout_version() == 0


@pytest.mark.parametrize("broker", ['{"port": 1}', "not json", "[]", '{"host": ""}'])
def test_an_unreadable_broker_reads_as_none(store: Path, broker: str) -> None:
    (store / "broker.json").write_text(broker)
    assert backup.read(backup.create(store)).broker() is None


def test_a_backup_from_before_the_port_was_dropped_still_shows_its_broker(store: Path) -> None:
    """The old field is not merely stale, it was load-bearing for the wrong
    answer: an unusable port made `int()` raise and hid a perfectly good host, so
    a restore preview showed no broker at all."""
    (store / "broker.json").write_text('{"host": "192.0.2.10", "port": "?"}')
    assert backup.read(backup.create(store)).broker() == "192.0.2.10"


def test_a_missing_broker_reads_as_none(store: Path) -> None:
    (store / "broker.json").unlink()
    assert backup.read(backup.create(store)).broker() is None


def test_a_file_that_is_not_text_reads_as_none(store: Path) -> None:
    (store / "broker.json").write_bytes(b"\xff\xfe\x00")
    assert backup.read(backup.create(store)).text("broker.json") is None


def test_a_default_name_says_whether_it_is_encrypted() -> None:
    assert backup.default_name(encrypted=False).endswith(".tar.gz")
    assert backup.default_name(encrypted=True).endswith(".tar.gz.enc")


# --- nothing to back up -------------------------------------------------------
def test_backing_up_a_store_that_does_not_exist_says_so(tmp_path: Path) -> None:
    with pytest.raises(WhiskerlessError, match="does not exist"):
        backup.create(tmp_path / "nowhere")


def test_backing_up_an_empty_store_says_so(tmp_path: Path) -> None:
    """An archive of nothing looks exactly like a successful backup until the day
    it is needed."""
    (tmp_path / "empty" / "ca").mkdir(parents=True)
    with pytest.raises(WhiskerlessError, match="is empty"):
        backup.create(tmp_path / "empty")


# --- encryption ---------------------------------------------------------------
def test_the_wrong_password_is_refused(store: Path) -> None:
    with pytest.raises(WhiskerlessError, match="wrong password, or the file is damaged"):
        backup.read(backup.create(store, password="right"), password="wrong")


def test_an_encrypted_backup_without_a_password_says_so(store: Path) -> None:
    with pytest.raises(WhiskerlessError, match="encrypted"):
        backup.read(backup.create(store, password="x"))


def test_editing_the_header_breaks_the_seal(store: Path) -> None:
    """The header is the AEAD's associated data, so its stated parameters are
    the parameters that were used — they cannot be swapped for weaker ones."""
    sealed = backup.create(store, password="x")
    line, _, rest = sealed[len(backup.MAGIC) :].partition(b"\n")
    meta = json.loads(line)
    meta["n"] = 1 << 10
    tampered = backup.MAGIC + json.dumps(meta, sort_keys=True).encode() + b"\n" + rest
    with pytest.raises(WhiskerlessError, match="could not decrypt"):
        backup.read(tampered, password="x")


def test_a_header_with_no_end_says_truncated(store: Path) -> None:
    with pytest.raises(WhiskerlessError, match="truncated"):
        backup.read(backup.MAGIC + b'{"cipher": "AES-256-GCM"', password="x")


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ({"cipher": "rot13", "kdf": "scrypt"}, "does not know how to read"),
        ({"cipher": "AES-256-GCM", "kdf": "md5"}, "does not know how to read"),
        ({"cipher": "AES-256-GCM", "kdf": "scrypt"}, "header is damaged"),  # no salt
        (
            {"cipher": "AES-256-GCM", "kdf": "scrypt", "salt": "!!", "nonce": "AA==",
             "n": 16384, "r": 8, "p": 1},
            "header is damaged",
        ),
        (
            {"cipher": "AES-256-GCM", "kdf": "scrypt", "salt": "AAAA", "nonce": "AA==",
             "n": 3, "r": 8, "p": 1},
            "unusable key-derivation settings",
        ),
    ],
)
def test_a_damaged_header_is_explained_not_traced(meta: dict[str, object], expected: str) -> None:
    """Everything here is a one-line message. A raw ValueError out of the crypto
    layer would come out as a traceback for a file somebody merely mistyped."""
    raw = backup.MAGIC + json.dumps(meta).encode() + b"\nciphertext"
    with pytest.raises(WhiskerlessError, match=expected):
        backup.read(raw, password="x")


def test_a_nonce_of_the_wrong_length_is_a_message_not_a_traceback(store: Path) -> None:
    """The other shape of "this file is damaged": a short nonce is valid base64
    and derives a key quite happily, then raises ValueError inside the cipher
    rather than failing the tag — and ValueError is not something `main()`
    turns into one line."""
    sealed = backup.create(store, password="x")
    line, _, rest = sealed[len(backup.MAGIC) :].partition(b"\n")
    meta = json.loads(line)
    meta["nonce"] = base64.b64encode(b"tooshort").decode()
    damaged = backup.MAGIC + json.dumps(meta, sort_keys=True).encode() + b"\n" + rest
    with pytest.raises(WhiskerlessError, match="could not decrypt"):
        backup.read(damaged, password="x")


def test_a_header_that_is_not_an_object_is_explained() -> None:
    raw = backup.MAGIC + b"[1, 2, 3]\nciphertext"
    with pytest.raises(WhiskerlessError, match="header is damaged"):
        backup.read(raw, password="x")


# --- hostile archives ---------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    [
        "whiskerless/../../.ssh/authorized_keys",
        "../escape",
        "/etc/passwd",
        "whiskerless/..",
        "windows\\path",
        "C:/drive",
        "whiskerless",  # the prefix alone names no file
    ],
)
def test_a_member_that_points_outside_the_store_is_refused(name: str) -> None:
    """Tar path traversal is ancient and still works. Names are checked rather
    than sanitised: one that needs cleaning was not written by whiskerless."""
    with pytest.raises(WhiskerlessError, match=r"not a usable name|points outside|names no file"):
        backup.read(_tar({name: b"x"}))


def test_a_member_with_a_null_byte_is_refused() -> None:
    """Checked directly: a plain tar header field is NUL-terminated, so tarfile
    truncates one there and never hands it over. The GNU long-name extension
    reads the name from a data block instead, and this guard is what stands
    between that path and a filename the rest of the code cannot reason about."""
    with pytest.raises(WhiskerlessError, match="not a usable name"):
        backup._safe_name("whiskerless/a\x00b")


def test_a_member_that_is_not_a_regular_file_is_refused() -> None:
    """A symlink member is the classic way an archive writes outside the
    directory it was extracted into."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("whiskerless/ca/ca.key")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(WhiskerlessError, match="not a regular file"):
        backup.read(buffer.getvalue())


def test_directories_in_an_archive_are_ignored(store: Path, tmp_path: Path) -> None:
    """Ours carries none, but hand-made tarballs do — and the paths already
    imply every directory that has to exist."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        directory = tarfile.TarInfo("whiskerless/ca")
        directory.type = tarfile.DIRTYPE
        tar.addfile(directory)
        payload = b"pem"
        info = tarfile.TarInfo("whiskerless/ca/ca.crt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    archive = backup.read(buffer.getvalue())
    assert archive.files == {"ca/ca.crt": b"pem"}


def test_an_archive_that_unpacks_to_too_much_is_refused(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A compressed archive can expand without bound; this one is held to the
    size a real store actually is."""
    blob = backup.create(store)
    monkeypatch.setattr(backup, "MAX_BYTES", 8)
    with pytest.raises(WhiskerlessError, match="unpacks to more than"):
        backup.read(blob)


def test_something_that_is_not_an_archive_at_all_is_explained() -> None:
    with pytest.raises(WhiskerlessError, match="not a readable whiskerless backup"):
        backup.read(b"this is a text file")


def test_an_empty_archive_says_so() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz"):
        pass
    with pytest.raises(WhiskerlessError, match="is empty"):
        backup.read(buffer.getvalue())


def test_an_unprefixed_archive_still_reads(store: Path) -> None:
    """Only our own prefix is stripped, and only when it is exactly that — so a
    tarball somebody rebuilt by hand keeps every path it states."""
    assert backup.read(_tar({"broker.json": b"{}"})).files == {"broker.json": b"{}"}


# --- reading from disk --------------------------------------------------------
def test_reading_a_missing_file_is_explained_not_traced(tmp_path: Path) -> None:
    with pytest.raises(WhiskerlessError, match="could not read"):
        backup.load(tmp_path / "nope.tar.gz")


def test_a_file_too_large_to_be_a_backup_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "huge.tar.gz"
    path.write_bytes(b"x" * 4096)
    monkeypatch.setattr(backup, "MAX_BYTES", 8)
    with pytest.raises(WhiskerlessError, match="is larger than"):
        backup.load(path)


def test_a_backup_written_to_disk_reads_back(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "out.tar.gz"
    path.write_bytes(backup.create(store))
    assert backup.read(backup.load(path)).robots() == ("LR4C123456",)
