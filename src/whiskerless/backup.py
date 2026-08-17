"""Copying this machine's whiskerless store off it, and putting it back.

``~/whiskerless`` holds one thing that cannot be regenerated: the private key
that signs certificates for your robots. Losing it does not stop robots that
already work — it costs you the ability to add or re-provision one without
walking to every robot you own with a laptop. That is a real cost, it lands
years after the machine died, and "copy this folder somewhere" is advice people
follow exactly as often as it is convenient.

So: one file, one command, and a restore that puts it back byte for byte.

**Optionally encrypted, never by accident.** The archive contains a signing key
in the clear, and a backup's whole job is to be somewhere else — a USB stick,
a NAS, cloud storage. Encryption is offered at the prompt and the format is
documented below so it never depends on this program still existing:

    WHISKERLESS-BACKUP-1\\n
    {"cipher": "AES-256-GCM", "kdf": "scrypt", "n": …, "r": 8, "p": 1,
     "salt": <base64>, "nonce": <base64>}\\n
    <AES-256-GCM ciphertext of the .tar.gz, tag appended>

The header line is the AEAD's associated data, so its parameters cannot be
altered without the decryption failing. Twenty lines of Python and this
paragraph are enough to recover the archive without whiskerless.

Unencrypted, it is an ordinary ``.tar.gz`` that ``tar`` can read forever, which
is worth a great deal in something you open once, under stress, on a machine
that may not have whiskerless on it yet.
"""

from __future__ import annotations

import base64
import io
import json
import os
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .exceptions import WhiskerlessError

#: First line of an encrypted archive. Version is in the magic rather than the
#: header so a future format change is legible in ``head -c 32`` and cannot be
#: mistaken for a corrupt header of this one.
MAGIC = b"WHISKERLESS-BACKUP-1\n"

#: Ceiling on both the file read and the total uncompressed size. A real store is
#: a few kilobytes; this exists so a hostile or truncated archive cannot expand
#: into memory unbounded.
MAX_BYTES = 64 * 1024 * 1024

# Every member is written under this, so `tar xzf` lands one directory rather
# than scattering `.layout`, `ca/`, `robots/` and friends into whatever
# directory somebody happened to be standing in.
_PREFIX = "whiskerless"

# scrypt at n=2**14, r=8 needs 16 MiB. Deliberately under 2**15: that lands on
# 32 MiB exactly, which is also OpenSSL's default `maxmem`, and being precisely
# at a limit is how you get a KDF that works here and fails on somebody else's
# build. The margin costs one halving of an already-adequate work factor.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 1 << 14, 8, 1
_KEY_BYTES, _SALT_BYTES, _NONCE_BYTES = 32, 16, 12


def default_name(*, encrypted: bool) -> str:
    """A timestamped filename to write when none was given.

    To the second, so the name carries its own ordering. Modification time does
    not survive the journey a backup is *for* — copied to a stick, synced
    through cloud storage, pulled out of a Time Machine snapshot, every file
    arrives stamped with whenever that copy happened. The name is the only part
    that still says when it was made, so it has to say it.

    Local time, not UTC: this is read by the person who made the backup, and a
    file stamped tomorrow because they ran it after dinner is a small, pointless
    confusion.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"whiskerless-backup-{stamp}.tar.gz" + (".enc" if encrypted else "")


def unused_name(directory: Path, *, encrypted: bool) -> Path:
    """A filename in ``directory`` that is not already taken.

    The timestamp does the work; the counter is only for two backups inside one
    second, which a scripted loop can manage and a person cannot. Neither
    refusing the second nor overwriting the first would be a good answer — the
    earlier file may be the one from *before* the store was damaged.
    """
    base = default_name(encrypted=encrypted)
    stem, _, extensions = base.partition(".")
    candidate = directory / base
    attempt = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{attempt}.{extensions}"
        attempt += 1
    return candidate


def is_encrypted(raw: bytes) -> bool:
    """Whether ``raw`` needs a password — read from the bytes, not the filename."""
    return raw.startswith(MAGIC)


@dataclass(frozen=True, slots=True)
class Archive:
    """The contents of a backup, held in memory.

    A store is kilobytes, so reading it whole costs nothing and buys the thing
    that matters: everything can be inspected — which CA, which robots — before
    a single byte is written over somebody's working setup.
    """

    files: Mapping[str, bytes]

    def text(self, name: str) -> str | None:
        data = self.files.get(name)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def layout_version(self) -> int:
        """The store layout this backup was written at. 0 means pre-versioning."""
        try:
            return int((self.text(".layout") or "").strip())
        except ValueError:
            return 0

    def ca_cert_pem(self) -> str | None:
        return self.text("ca/ca.crt")

    def broker(self) -> tuple[str, int] | None:
        raw = self.text("broker.json")
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
            return str(parsed["host"]), int(parsed.get("port", 8883))
        except (ValueError, TypeError, KeyError):
            return None

    def robots(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                name.split("/")[1]
                for name in self.files
                if name.startswith("robots/") and name.endswith("/profile.json")
            )
        )

    def write_into(self, root: Path) -> None:
        """Lay the archive down at ``root``, owner-only the whole way.

        Permissions come from here rather than from the tar: an archive that
        travelled through cloud storage, a Windows machine, or somebody's
        unpacking and repacking has whatever modes that journey gave it, and one
        of these files is a signing key.
        """
        root.parent.mkdir(parents=True, exist_ok=True)
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        for name, data in sorted(self.files.items()):
            parts = PurePosixPath(name).parts
            directory = root
            for part in parts[:-1]:
                directory = directory / part
                directory.mkdir(exist_ok=True)
                directory.chmod(0o700)
            target = directory / parts[-1]
            target.write_bytes(data)
            target.chmod(0o600)


def create(root: Path, *, password: str | None = None) -> bytes:
    """Pack the store at ``root`` into an archive, encrypting it if asked."""
    if not root.is_dir():
        raise WhiskerlessError(
            f"nothing to back up: {root} does not exist — run `whiskerless setup` first"
        )
    buffer = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(root.rglob("*")):
            # Symlinks are skipped rather than followed: a link out of the store
            # would pull an arbitrary file into an archive people hand around,
            # and nothing whiskerless writes is ever a link.
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            info = tarfile.TarInfo(name=f"{_PREFIX}/{path.relative_to(root).as_posix()}")
            info.size = len(data)
            info.mtime = int(path.stat().st_mtime)
            # Normalised: mode is re-applied on restore anyway, and a uid/uname
            # would put the operator's account name in a file they share.
            info.mode = 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
            count += 1
    if not count:
        raise WhiskerlessError(f"nothing to back up: {root} is empty")
    blob = buffer.getvalue()
    return _encrypt(blob, password) if password else blob


def load(path: Path) -> bytes:
    """Read a backup file, refusing one too large to be a store."""
    try:
        if path.stat().st_size > MAX_BYTES:
            raise WhiskerlessError(
                f"{path} is larger than {MAX_BYTES // (1024 * 1024)} MiB — that is not "
                f"a whiskerless backup"
            )
        return path.read_bytes()
    except OSError as exc:
        raise WhiskerlessError(f"could not read {path}: {exc.strerror or exc}") from exc


def read(raw: bytes, *, password: str | None = None) -> Archive:
    """Decrypt if needed, unpack, and validate every member name."""
    if is_encrypted(raw):
        if password is None:
            raise WhiskerlessError("this backup is encrypted — it needs the password it was made with")
        raw = _decrypt(raw, password)
    return Archive(files=_unpack(raw))


def _encrypt(blob: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(_SALT_BYTES), os.urandom(_NONCE_BYTES)
    header = (
        json.dumps(
            {
                "cipher": "AES-256-GCM",
                "kdf": "scrypt",
                "n": _SCRYPT_N,
                "r": _SCRYPT_R,
                "p": _SCRYPT_P,
                "salt": base64.b64encode(salt).decode(),
                "nonce": base64.b64encode(nonce).decode(),
            },
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    key = _derive(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    # The header is the associated data, so the parameters it states are the
    # parameters that were used — an edited salt or work factor fails the tag
    # rather than silently deriving a different key.
    return MAGIC + header + AESGCM(key).encrypt(nonce, blob, header)


def _decrypt(raw: bytes, password: str) -> bytes:
    line, separator, ciphertext = raw[len(MAGIC) :].partition(b"\n")
    if not separator:
        raise WhiskerlessError("this backup is truncated — its header has no end")
    try:
        meta = json.loads(line)
        if not isinstance(meta, dict):
            raise ValueError("header is not an object")
        if meta.get("cipher") != "AES-256-GCM" or meta.get("kdf") != "scrypt":
            raise WhiskerlessError(
                f"this backup uses {meta.get('cipher')!r} with {meta.get('kdf')!r}, which "
                f"this whiskerless does not know how to read"
            )
        salt = base64.b64decode(meta["salt"], validate=True)
        nonce = base64.b64decode(meta["nonce"], validate=True)
        key = _derive(password, salt, int(meta["n"]), int(meta["r"]), int(meta["p"]))
    except WhiskerlessError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise WhiskerlessError(f"this backup's header is damaged: {exc}") from exc
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, line + b"\n")
    except InvalidTag:
        # GCM cannot tell the two apart, and neither should the message — a
        # confident "wrong password" for a corrupted file sends somebody hunting
        # through a password manager for something that would not have worked.
        raise WhiskerlessError(
            "could not decrypt this backup — wrong password, or the file is damaged"
        ) from None


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    try:
        return Scrypt(salt=salt, length=_KEY_BYTES, n=n, r=r, p=p).derive(password.encode())
    except (ValueError, OverflowError, MemoryError) as exc:
        # Parameters come out of the file, so a hostile or corrupt header could
        # otherwise ask for a terabyte of scratch memory.
        raise WhiskerlessError(f"this backup asks for unusable key-derivation settings: {exc}") from exc


def _unpack(blob: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tar:
            for member in tar:
                if member.isdir():
                    continue
                if not member.isfile():
                    # Links, devices and fifos have no business here, and a
                    # symlink is the classic way an archive writes outside the
                    # directory it was extracted into.
                    raise WhiskerlessError(
                        f"{member.name!r} in this backup is not a regular file"
                    )
                total += member.size
                if total > MAX_BYTES:
                    raise WhiskerlessError(
                        f"this backup unpacks to more than {MAX_BYTES // (1024 * 1024)} MiB "
                        f"— that is not a whiskerless store"
                    )
                stream = tar.extractfile(member)
                if stream is not None:
                    files[_safe_name(member.name)] = stream.read()
    except tarfile.TarError as exc:
        raise WhiskerlessError(f"this is not a readable whiskerless backup: {exc}") from exc
    if not files:
        raise WhiskerlessError("this backup is empty")
    return files


def _safe_name(raw: str) -> str:
    """Validate an archive member's path and strip our one directory prefix.

    Path traversal in a tar is old and still works: a member named
    ``../../.ssh/authorized_keys`` writes there when extracted naively. Names are
    checked rather than sanitised, because a name that needs cleaning is not one
    whiskerless wrote, and quietly repairing it hides that.
    """
    if not raw or "\x00" in raw or "\\" in raw or ":" in raw:
        raise WhiskerlessError(f"{raw!r} in this backup is not a usable name")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise WhiskerlessError(f"{raw!r} in this backup points outside it")
    parts = path.parts
    if parts and parts[0] == _PREFIX:
        parts = parts[1:]
    if not parts:
        raise WhiskerlessError(f"{raw!r} in this backup names no file")
    return PurePosixPath(*parts).as_posix()
