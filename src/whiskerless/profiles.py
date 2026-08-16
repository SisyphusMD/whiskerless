"""Per-machine memory of the robots this host has provisioned.

Provisioning is the moment every connection detail is known — the serial, the
broker, the CA — so it is the moment to write them down. Without that, each
later command re-asks for all three, and a tool whose audience is standing next
to a litter box with a laptop makes them retype a path they already typed once.

The CA is stored by **contents**, not by path. A path can be moved, deleted, or
typed with a ``~`` the shell never sees; the bytes cannot. :class:`MqttSettings`
already prefers ``ca_cert_data`` over ``ca_cert_path``, so a stored profile
needs no special handling downstream.

Layout under ``~/.whiskerless`` (override with ``WHISKERLESS_HOME``)::

    robots/<serial>/profile.json   0600 — format version, broker, optional login
    robots/<serial>/ca.pem         0600 — the CA that signed the broker
    default                        0600 — serial used when none is given

**No secret is ever written here.** Passwords live in the OS keychain
(:mod:`whiskerless.secrets`) or nowhere; the robot's factory certificate and
private key are neither read nor written by whiskerless at all. Files are still
0600 and directories 0700, because a broker address and username are worth
keeping to yourself.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .exceptions import ProfileError
from .mqtt import DEFAULT_TLS_PORT, MqttSettings

HOME_ENV = "WHISKERLESS_HOME"
DEFAULT_SUBDIR = ".whiskerless"

_PROFILE_FILE = "profile.json"
_CA_FILE = "ca.pem"
_DEFAULT_FILE = "default"

#: Format version of ``profile.json``. Bump it ONLY together with an entry in
#: :data:`_MIGRATIONS` that reshapes the previous version into this one.
#:
#: It exists because the alternative is guessing. A file with no version can be
#: read wrongly in silence — a renamed field reads as absent, and absent has a
#: default, so a robot loses its calibration or its port and nothing says so.
#: Stamping the shape turns that into a question with an answer.
PROFILE_VERSION = 1

#: How to get from one stored version to the next: ``{from_version: upgrade}``.
#: Each function takes the raw mapping at ``from_version`` and returns it at
#: ``from_version + 1``, so a profile several versions old is walked forward one
#: step at a time and no migration ever needs to know the whole history.
#:
#: Empty today, and correctly so: version 1 is the first shape there is. The
#: machinery ships ahead of its first user because the moment it is needed is the
#: moment a format has ALREADY changed, and by then the profiles in the field
#: were written by something that could not stamp them.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _migrated(raw: dict[str, Any], serial: str) -> dict[str, Any]:
    """Walk a stored profile forward to :data:`PROFILE_VERSION`.

    A profile written before versioning existed has no ``version`` key and is
    read as 1 — which is exactly what it is, since nothing about the shape
    changed when the stamp was added.

    A profile from the FUTURE is refused rather than read optimistically. An
    unknown field is invisible to this reader, so a best-effort load quietly
    discards whatever the newer version added and then saves the truncated result
    back over it — the one failure mode that destroys data while appearing to
    work.
    """
    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ProfileError(
            f"the profile for {serial} has an unusable format version ({version!r})"
        )
    if version > PROFILE_VERSION:
        raise ProfileError(
            f"the profile for {serial} was written by a newer whiskerless "
            f"(format {version}; this one reads {PROFILE_VERSION}) — upgrade whiskerless, "
            f"or move that robot's folder aside and re-run `whiskerless adopt`"
        )
    while version < PROFILE_VERSION:
        upgrade = _MIGRATIONS.get(version)
        if upgrade is None:
            raise ProfileError(
                f"the profile for {serial} is format {version} and there is no way to "
                f"read it forward — re-run `whiskerless adopt` for this robot"
            )
        raw = upgrade(dict(raw))
        version += 1
    return raw

# A stored distance beyond this is damage, not a measurement — the robot is
# knee-high. Kept deliberately loose: this rejects the absurd, and the device
# module's own band is what judges a reading worth keeping.
_MAX_DISTANCE_MM = 10_000

# Deliberately narrower than any real serial: this string becomes a directory
# name, so anything that could escape the store (separators, dots, control
# characters) is rejected rather than sanitised. Silently rewriting a serial
# would file a robot under a name the user never typed.
_SERIAL_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{2,63}\Z")


@dataclass(frozen=True, slots=True)
class Serial:
    """A robot's serial, and whether the robot confirmed it or a person typed it.

    The distinction is not cosmetic. A typed serial becomes the MQTT client-id
    and both topic segments, so a typo produces a robot that provisions cleanly
    and then never appears on the broker — no error, nothing to see. Recording
    how the value was obtained lets a later run say which it is holding.
    """

    value: str
    verified: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", self.value.strip().upper())
        if not _SERIAL_RE.match(self.value):
            raise ProfileError(
                f"{self.value!r} is not a usable serial — expected letters, digits, "
                "'-' or '_' (3-64 characters), e.g. LR4C123456"
            )


@dataclass(frozen=True, slots=True)
class RobotProfile:
    """Everything needed to reach one robot's broker, minus what it can derive."""

    serial: Serial
    host: str
    port: int = DEFAULT_TLS_PORT
    name: str = ""
    username: str | None = None
    # Held in memory to reach the broker, never written HERE. A 0600 file beside
    # the config is not "stored securely" however it is described — it follows
    # people into backups and dotfile sync without ever looking like a secret.
    # The keychain is the one place that genuinely is different; see secrets.py.
    password: str | None = None
    verify_hostname: bool = True
    ca_pem: str | None = None
    # Not needed to reach the broker — kept so a second robot can be offered the
    # same network without the user hunting for it. The passphrase is
    # deliberately absent: a home WiFi secret is a bigger thing to leave on disk
    # than a broker login, and it is only ever needed during provisioning.
    wifi_ssid: str = ""
    # What a person measured, with the globe in front of them: the ToF distance
    # at a full fill and (optionally) with the globe empty. Deliberately not the
    # learned scale — a one-shot CLI sees single documents and cannot learn one,
    # and "this is what full looks like" is a claim only a human can make.
    litter_full_mm: int | None = None
    litter_empty_mm: int | None = None

    @property
    def display_name(self) -> str:
        """What to show a human — their chosen name, else the serial itself."""
        return self.name or self.serial.value

    def settings(self, *, client_id: str | None = None) -> MqttSettings:
        """The transport settings for this robot.

        ``client_id`` is deliberately not defaulted to the serial: the robot is
        already connected as the serial, and a second client claiming that id
        kicks the robot off its own broker connection.
        """
        return MqttSettings(
            host=self.host,
            port=self.port,
            ca_cert_data=self.ca_pem,
            verify_hostname=self.verify_hostname,
            username=self.username,
            password=self.password,
            client_id=client_id,
        )


@dataclass(frozen=True, slots=True)
class SharedSetup:
    """What every robot already set up here agrees on.

    A household usually points all of its robots at one broker behind one CA, so
    a new robot can be offered those without anyone naming a particular robot —
    which would be arbitrary with three of them and misleading with one, since
    none of this is per-robot.

    A field is ``None`` when the robots disagree, and only then does the caller
    have to fall back on naming where a value came from.
    """

    host: str | None = None
    ca_pem: str | None = None
    wifi_ssid: str | None = None
    username: str | None = None

    @classmethod
    def from_profiles(cls, profiles: Sequence[RobotProfile]) -> SharedSetup:
        def agreed(values: Iterable[str | None]) -> str | None:
            # Robots that have no value recorded do not count as disagreement —
            # a profile saved before a field existed should not veto the offer.
            present = {value for value in values if value}
            return present.pop() if len(present) == 1 else None

        return cls(
            host=agreed(profile.host for profile in profiles),
            ca_pem=agreed(profile.ca_pem for profile in profiles),
            wifi_ssid=agreed(profile.wifi_ssid for profile in profiles),
            username=agreed(profile.username for profile in profiles),
        )


def _home(environ: Mapping[str, str]) -> Path:
    home = environ.get("HOME")
    return Path(home) if home else Path.home()


def _expand(path: str, environ: Mapping[str, str]) -> Path:
    """Expand a leading ``~`` against ``environ`` rather than the process.

    ``Path.expanduser`` always consults ``os.environ``, so it would quietly
    ignore a HOME handed to :meth:`ProfileStore.from_env` — the one thing an
    injected environment exists to control. ``~user`` is rare enough to hand
    back to the stdlib, which needs the password database for it anyway.
    """
    if path == "~":
        return _home(environ)
    if path.startswith("~/"):
        return _home(environ) / path[2:]
    return Path(path).expanduser()


def _write_private(path: Path, text: str) -> None:
    """Replace ``path`` atomically, owner-readable only, durable on return.

    ``mkstemp`` creates at 0600, so the content is never briefly world-readable —
    it matters because these files hold broker credentials. The directory is
    fsynced as well as the file so the rename itself survives a power loss;
    otherwise a machine can come back with a profile that references a CA that
    was never linked into place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            # Windows has no fchmod (and no POSIX mode bits to set) — a Windows
            # home directory is already private to its user, and the store holds
            # no secrets, so skipping is the whole accommodation it needs.
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)  # noqa: PTH105 - os-level rename for durability
        if os.name == "posix":
            # Windows cannot open a directory for fsync; the file itself is
            # still flushed above, and the worst a power loss can cost there is
            # a reconstructible convenience file.
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temp_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class ProfileStore:
    """The on-disk set of robots this machine has provisioned."""

    root: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ProfileStore:
        environ: Mapping[str, str] = os.environ if env is None else env
        override = environ.get(HOME_ENV)
        if override:
            return cls(_expand(override, environ))
        return cls(_home(environ) / DEFAULT_SUBDIR)

    @property
    def robots_dir(self) -> Path:
        return self.root / "robots"

    def _dir(self, serial: Serial) -> Path:
        return self.robots_dir / serial.value

    def save(self, profile: RobotProfile) -> None:
        directory = self._dir(profile.serial)
        # Created explicitly rather than left to mkdir(parents=True), which
        # would give the root and robots/ umask permissions — and a listable
        # robots/ advertises every serial in the house.
        for ancestor in (self.root, self.robots_dir):
            ancestor.mkdir(exist_ok=True)
            ancestor.chmod(0o700)
        payload = {
            # First key on purpose: a human opening this file to fix something
            # should meet the format stamp before the values it governs.
            "version": PROFILE_VERSION,
            "serial": profile.serial.value,
            "serial_verified": profile.serial.verified,
            "host": profile.host,
            "port": profile.port,
            "name": profile.name,
            "username": profile.username,
            "verify_hostname": profile.verify_hostname,
            "wifi_ssid": profile.wifi_ssid,
            "litter_full_mm": profile.litter_full_mm,
            "litter_empty_mm": profile.litter_empty_mm,
        }
        _write_private(directory / _PROFILE_FILE, json.dumps(payload, indent=2) + "\n")
        if profile.ca_pem is not None:
            _write_private(directory / _CA_FILE, profile.ca_pem)
        else:
            # An overwrite without a CA must not leave the old one behind for
            # load() to silently resurrect against a broker it no longer matches.
            (directory / _CA_FILE).unlink(missing_ok=True)

    def load(self, serial: str) -> RobotProfile:
        parsed = Serial(serial)
        path = self._dir(parsed) / _PROFILE_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProfileError(
                f"no saved profile for {parsed.value} — run `whiskerless provision` first, "
                "or pass --host explicitly"
            ) from None
        except (OSError, ValueError) as exc:
            raise ProfileError(f"could not read the profile for {parsed.value}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ProfileError(f"the profile for {parsed.value} is not a JSON object")
        raw = _migrated(raw, parsed.value)

        ca_path = self._dir(parsed) / _CA_FILE
        try:
            ca_pem: str | None = ca_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            ca_pem = None
        except OSError as exc:
            raise ProfileError(f"could not read the stored CA for {parsed.value}: {exc}") from exc

        host = raw.get("host")
        if not isinstance(host, str) or not host:
            raise ProfileError(f"the profile for {parsed.value} has no broker host")
        try:
            port = int(raw.get("port", DEFAULT_TLS_PORT))
        except (TypeError, ValueError) as exc:
            # A hand-edited port must surface as damage — list_profiles, damaged
            # and forget all speak ProfileError, and a bare ValueError here took
            # every one of them down with it.
            raise ProfileError(f"the profile for {parsed.value} has an unusable port") from exc
        return RobotProfile(
            # The directory name is the identity — it is what `load` and `resolve`
            # key on. The serial inside the JSON is there to be readable, and a
            # hand-edited mismatch must not make a robot answer to two names.
            serial=Serial(parsed.value, bool(raw.get("serial_verified"))),
            host=host,
            port=port,
            name=str(raw.get("name") or ""),
            username=_optional_str(raw.get("username")),
            verify_hostname=bool(raw.get("verify_hostname", True)),
            ca_pem=ca_pem,
            wifi_ssid=str(raw.get("wifi_ssid") or ""),
            # Hand-edited garbage here loses the calibration, not the robot:
            # an unreachable profile is a far worse outcome than an unanchored
            # percentage, which the next `calibrate` press restores.
            litter_full_mm=_optional_int(raw.get("litter_full_mm")),
            litter_empty_mm=_optional_int(raw.get("litter_empty_mm")),
        )

    def list_profiles(self) -> tuple[RobotProfile, ...]:
        """Every readable profile, sorted by serial.

        A directory that fails to parse is skipped rather than fatal: one
        corrupt profile must not make the other robots unreachable. The skipped
        ones are reported by :meth:`damaged` — an entry a user cannot see is
        one they can never repair or forget.
        """
        if not self.robots_dir.is_dir():
            return ()
        found = []
        for entry in self._entries():
            try:
                found.append(self.load(entry.name))
            except ProfileError:
                continue
        return tuple(found)

    def damaged(self) -> tuple[tuple[str, str], ...]:
        """The robot directories that no longer load, each with the reason."""
        broken = []
        for entry in self._entries():
            try:
                self.load(entry.name)
            except ProfileError as exc:
                broken.append((entry.name, str(exc)))
        return tuple(broken)

    def _entries(self) -> list[Path]:
        if not self.robots_dir.is_dir():
            return []
        return [
            entry
            for entry in sorted(self.robots_dir.iterdir())
            if entry.is_dir() and not entry.name.startswith(".")
        ]

    def resolve(self, serial: str | None = None) -> RobotProfile:
        """The profile to act on: the named one, the default, or the only one."""
        if serial:
            return self.load(serial)
        default = self.get_default()
        if default:
            return self.load(default)
        known = self.list_profiles()
        if len(known) == 1:
            return known[0]
        if not known:
            raise ProfileError(
                "no robots are set up on this machine — run `whiskerless provision` first"
            )
        names = ", ".join(profile.serial.value for profile in known)
        raise ProfileError(
            f"several robots are set up ({names}) — pick one with --serial, "
            "or choose a default with `whiskerless use <serial>`"
        )

    def get_default(self) -> str | None:
        try:
            value = (self.root / _DEFAULT_FILE).read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return None
        return value or None

    def set_default(self, serial: str) -> None:
        parsed = Serial(serial)
        if not (self._dir(parsed) / _PROFILE_FILE).is_file():
            raise ProfileError(f"no saved profile for {parsed.value}")
        _write_private(self.root / _DEFAULT_FILE, parsed.value + "\n")

    def forget(self, serial: str) -> None:
        """Remove a robot's stored profile. The robot itself is untouched."""
        parsed = Serial(serial)
        directory = self._dir(parsed)
        if not directory.is_dir():
            raise ProfileError(f"no saved profile for {parsed.value}")
        for name in (_PROFILE_FILE, _CA_FILE):
            (directory / name).unlink(missing_ok=True)
        # A non-empty directory means something the store never wrote is still in
        # there; leaving it is safer than recursively deleting a path a user may
        # have put their own files in.
        with contextlib.suppress(OSError):
            directory.rmdir()
        if self.get_default() == parsed.value:
            (self.root / _DEFAULT_FILE).unlink(missing_ok=True)


def _optional_int(value: object) -> int | None:
    # bool first: it is an int to Python, and `true` in a hand-edited profile
    # would otherwise become a 1 mm calibration.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = int(value)
    except (ValueError, OverflowError):
        # OverflowError: JSON accepts 1e400, which parses to infinity, and an
        # unusable calibration must cost the calibration — not every command
        # that has to read this profile first.
        return None
    # Bounded after coercion for the same reason: JSON also accepts a
    # thousand-digit integer, which converts happily here and then overflows
    # inside the first float division that touches it. Nothing about a litter
    # box is measured in kilometres.
    return number if 0 <= number <= _MAX_DISTANCE_MM else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def merge_overrides(
    profile: RobotProfile,
    *,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    verify_hostname: bool | None = None,
    ca_pem: str | None = None,
) -> RobotProfile:
    """Lay command-line flags over a stored profile; ``None`` means "not given".

    Spelled out rather than ``**kwargs`` so a typo is a type error instead of a
    silently ignored flag.
    """
    return replace(
        profile,
        host=profile.host if host is None else host,
        port=profile.port if port is None else port,
        username=profile.username if username is None else username,
        password=profile.password if password is None else password,
        verify_hostname=(
            profile.verify_hostname if verify_hostname is None else verify_hostname
        ),
        ca_pem=profile.ca_pem if ca_pem is None else ca_pem,
    )
