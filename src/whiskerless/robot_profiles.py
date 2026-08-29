"""Per-machine memory of the robots this host has provisioned.

Provisioning is the moment every connection detail is known — the serial, the
broker, the CA — so it is the moment to write them down. Without that, each
later command re-asks for all three, and a tool whose audience is standing next
to a litter box with a laptop makes them retype a path they already typed once.

Certificates are stored by **contents**, not by path. A path can be moved,
deleted, or typed with a ``~`` the shell never sees; the bytes cannot.
:class:`MqttSettings` already prefers ``ca_cert_data`` over ``ca_cert_path``, so
nothing downstream needs to care where a file came from.

Layout under ``~/whiskerless`` (override with ``WHISKERLESS_HOME``)::

    .layout                        structure version, separate from the release
    broker.json                    the ONE broker every robot here talks to
    ca/ca.crt  ca/ca.key           the authority; the key never leaves this machine
    client/                        this machine's identity to the broker
    broker/                        server.crt + server.key — copy to your broker
    robots/<serial>/profile.json   what a person named and measured
    robots/<serial>/client/        what that robot presents to the broker
    default                        serial used when none is given

Files are 0600 and directories 0700 throughout.

**Two kinds of secret live here, and for different reasons.** The CA private key
is archival — it must survive machine loss, and every tool on earth keeps CA keys
as files because you have to carry and archive them. Client keys (this machine's
and each robot's) are kept because one that was handed to us cannot be recreated,
and because a robot re-provisioned should stay the same client to the broker. The
WiFi passphrase is the one thing still asked for at the robot and forgotten.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Concatenate, ParamSpec, TypeVar, cast

try:  # POSIX only; Windows has no fcntl and the accommodation is documented on _exclusive().
    import fcntl

    _HAVE_FLOCK = True
except ImportError:  # pragma: no cover - exercised only on Windows
    _HAVE_FLOCK = False

from . import __version__, pki
from .exceptions import AmbiguousRobotError, RobotProfileError, WhiskerlessError
from .mqtt import DEFAULT_TLS_PORT, MqttSettings
from .pki import KeyPair

HOME_ENV = "WHISKERLESS_HOME"
#: Deliberately NOT hidden. This directory holds the CA private key, and the one
#: instruction that matters about it — back this up — is useless if the folder is
#: invisible in a file manager. Matches the sibling dreame-valetudo project.
DEFAULT_SUBDIR = "whiskerless"
#: Where a pre-1 layout lived. Migrated forward on first sight, never read in place.
LEGACY_SUBDIR = ".whiskerless"

#: On-disk STRUCTURE version, deliberately separate from the release version: a
#: stable build and a release candidate share a layout freely, and most releases
#: do not touch it. Bumped only by a real structural change, and every bump ships
#: with the migration that reaches it.
LAYOUT_VERSION = 1
_LAYOUT_FILE = ".layout"
#: Written beside the marker, never instead of it: `.layout` stays a bare integer so
#: every build that has shipped can still read it.
_LAYOUT_DETAIL_FILE = ".layout.json"
#: Serialises store mutations between processes. This store has two writers BY DESIGN — the CLI and
#: the Home Assistant coordinator, against the same `~/whiskerless` — and every mutation here is a
#: read-modify-write. Atomic replacement already stops a torn file; it does not stop the CLI's save
#: from landing on top of a profile the integration wrote a millisecond earlier. Ported from
#: dreame-valetudo, which locks its workspace for the same reason.
_LOCK_FILE = ".lock"
#: Long enough to outlast another writer's mutation, short enough that a stale lock cannot wedge a
#: command indefinitely. Waiting is right where refusing would be wrong: both writers are legitimate.
_LOCK_TIMEOUT_SECONDS = 5.0
#: Which whiskerless first wrote each layout. Recorded so a build that meets a layout from the
#: FUTURE can name the version to upgrade to — it cannot know that from its own constants, which is
#: the whole reason the number travels with the store. Ported from dreame-valetudo.
_LAYOUT_SINCE: dict[int, str] = {1: "0.2.0"}


def _tool_version() -> str:
    """This build's version. Imported inside the function to keep the package root out of this
    module's import graph."""

    return __version__


_PROFILE_FILE = "profile.json"
_CA_FILE = "ca.pem"
_DEFAULT_FILE = "default"
# One CA signs for every robot, the broker, and this machine, so it sits in its
# own directory rather than under any one robot. File names are the ones that get
# pasted into mosquitto.conf beside `cafile` / `certfile` / `keyfile`: names that
# survive the copy beat names that look tidy in a listing.
_CA_DIR, _CA_CERT, _CA_KEY = "ca", "ca.crt", "ca.key"
# This machine's own client identity. Kept, unlike a robot's — we are the one
# using it, on every command, and regenerating per run would both cost a keygen
# each time and make the broker's log a list of strangers.
_CLIENT_DIR, _CLIENT_CERT, _CLIENT_KEY = "client", "client.crt", "client.key"
# Artifacts for the user to install on their broker. whiskerless never reads
# these; they live here so "where did that file go" cannot happen, and they are
# freely regenerable from the CA.
_BROKER_DIR, _SERVER_CERT, _SERVER_KEY = "broker", "server.crt", "server.key"
#: Where this machine's one broker is recorded. Store-level, not per-robot: every
#: robot here talks to the same broker behind the same CA, and pretending
#: otherwise cost a whole apparatus for reconciling values that never differ. A
#: genuinely separate broker is a separate store — point WHISKERLESS_HOME at it.
_BROKER_FILE = "broker.json"

# A stored distance beyond this is damage, not a measurement — the robot is
# knee-high. Kept deliberately loose: this rejects the absurd, and the device
# module's own band is what judges a reading worth keeping.
_MAX_DISTANCE_MM = 10_000

# Deliberately narrower than any real serial: this string becomes a directory
# name, so anything that could escape the store (separators, dots, control
# characters) is rejected rather than sanitised. Silently rewriting a serial
# would file a robot under a name the user never typed.
_SERIAL_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{2,63}\Z")
#: What a Litter-Robot serial actually looks like, as printed on the robot. Deliberately NOT what
#: `Serial` accepts: that is a containment rule for a directory name and lets almost any word
#: through, so a mistyped display name ("Upstair" for "Upstairs") parsed as a perfectly valid
#: serial and the CLI published to a topic no robot subscribes to, reporting success.
_LOOKS_LIKE_A_ROBOT_SERIAL = re.compile(r"\ALR[34][A-Z][A-Za-z0-9]{4,}\Z", re.IGNORECASE)


def looks_like_a_robot_serial(value: str) -> bool:
    """Whether `value` has the shape of a serial printed on a robot."""
    return bool(_LOOKS_LIKE_A_ROBOT_SERIAL.match(value.strip()))


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
            raise RobotProfileError(
                f"{self.value!r} is not a usable serial — expected letters, digits, "
                "'-' or '_' (3-64 characters), e.g. LR4C123456"
            )


class AuthMode(StrEnum):
    """How this store proves who it is — to the broker, and on behalf of a robot.

    Stored rather than derived. Deriving it from what happens to be on disk is
    what made a store with no signing key silently mean "nobody authenticates":
    the same absence that means "I keep my key in cert-manager" also means "I lost
    it", and the two want opposite handling. Written down, they are the same
    question asked once, and every command afterwards either honours it or says
    plainly that the files no longer match it.
    """

    #: whiskerless holds the signing key and issues every identity itself.
    MUTUAL = "mutual"
    #: Identities are minted elsewhere and handed to whiskerless, which stores and
    #: presents them. The signing key never reaches this machine — a stricter
    #: arrangement than the default, not a weaker one.
    SUPPLIED = "supplied"
    #: Trust anchor only: robots keep the certificate they shipped with and the
    #: CLI presents none, so the broker's listener has to accept anonymous
    #: clients. What 0.1.3 did, and the one mode that has to be asked for.
    ANONYMOUS = "anonymous"


@dataclass(frozen=True, slots=True)
class Broker:
    """The one broker every robot in this store talks to.

    Host and nothing else. The robot's port is a compile-time constant in its
    firmware — provisioning has no field for one — so a CLI pointed anywhere else
    is pointed away from the robot it exists to talk to. Hostname verification is
    likewise not optional: the robot checks the broker's name against what it was
    provisioned with, and `setup` reissues the server certificate whenever that
    name changes, so a store whose CLI needed the check off would be a store whose
    robots could not connect at all.
    """

    host: str
    #: Defaulted, not optional: a store written before the field existed holds a
    #: signing key by the invariant of the release that wrote it, which is exactly
    #: what MUTUAL means. Nothing has to be guessed, and `assert_usable()` says so
    #: out loud if the files ever stop matching.
    auth: AuthMode = AuthMode.MUTUAL

    def settings(
        self,
        *,
        ca_pem: str | None = None,
        identity: KeyPair | None = None,
        client_id: str | None = None,
    ) -> MqttSettings:
        """Transport settings for this broker.

        ``client_id`` is deliberately not defaulted to any robot's serial: the
        robot is already connected as its serial, and a second client claiming
        that id kicks the robot off its own broker connection.
        """
        return MqttSettings(
            host=self.host,
            port=DEFAULT_TLS_PORT,
            ca_cert_data=ca_pem,
            verify_hostname=True,
            client_cert_data=identity.cert_pem if identity else None,
            client_key_data=identity.key_pem if identity else None,
            client_id=client_id,
        )


@dataclass(frozen=True, slots=True)
class RobotProfile:
    """Everything needed to reach one robot's broker, minus what it can derive."""

    serial: Serial
    name: str = ""
    # Not needed to reach the broker — kept so a second robot can be offered the
    # same network without the user hunting for it. The passphrase is never
    # stored anywhere: it is wanted once, while someone is standing at the robot,
    # and typing it then is what every device setup asks for anyway.
    wifi_ssid: str = ""
    # What a person measured, with the globe in front of them: the ToF distance
    # at a full fill and (optionally) with the globe empty. Deliberately not the
    # learned scale — a one-shot CLI sees single documents and cannot learn one,
    # and "this is what full looks like" is a claim only a human can make.
    litter_full_mm: int | None = None
    litter_empty_mm: int | None = None
    # The serial number of the client certificate last issued to this robot. Not
    # secret. Names the certificate CURRENTLY issued: a reissue overwrites it, so it is
    # the last one handed out rather than a history. Nothing reads this today; it exists
    # so a revocation list can be
    # built later by somebody who did not plan for one, which is the situation
    # everybody is in when they suddenly want one.
    cert_serial: str | None = None

    @property
    def display_name(self) -> str:
        """What to show a human — their chosen name, else the serial itself."""
        return self.name or self.serial.value


def _named_hosts(entries: list[Path]) -> list[str]:
    """Every broker address the pre-layout profiles name, in directory order.

    Unreadable profiles are skipped rather than fatal: this runs from
    `from_env()`, so raising here takes every command down.
    """
    found: list[str] = []
    for entry in entries:
        try:
            raw = json.loads((entry / _PROFILE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        host = raw.get("host") if isinstance(raw, dict) else None
        if isinstance(host, str) and host and host not in found:
            found.append(host)
    return found


def _home(environ: Mapping[str, str]) -> Path:
    home = environ.get("HOME")
    return Path(home) if home else Path.home()


def _expand(path: str, environ: Mapping[str, str]) -> Path:
    """Expand a leading ``~`` against ``environ`` rather than the process.

    ``Path.expanduser`` always consults ``os.environ``, so it would quietly
    ignore a HOME handed to :meth:`RobotProfileStore.from_env` — the one thing an
    injected environment exists to control. ``~user`` is rare enough to hand
    back to the stdlib, which needs the password database for it anyway.
    """
    if path == "~":
        return _home(environ)
    if path.startswith("~/"):
        return _home(environ) / path[2:]
    return Path(path).expanduser()


_P = ParamSpec("_P")
_R = TypeVar("_R")


def _locked(method: Callable[Concatenate[RobotProfileStore, _P], _R]) -> Callable[Concatenate[RobotProfileStore, _P], _R]:
    """Hold the store lock for one mutation.

    On the methods that read-modify-write, not on every write: an atomic replacement is already
    safe on its own, and taking the lock around a plain read would only invent contention.
    """

    @functools.wraps(method)
    def guarded(self: RobotProfileStore, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with self._exclusive():
            return method(self, *args, **kwargs)

    return cast("Callable[Concatenate[RobotProfileStore, _P], _R]", guarded)


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
            # Windows has no fchmod (and no POSIX mode bits to set). The store DOES hold
            # secrets — the CA private key and the client keys, per this module's docstring —
            # so this is a real accommodation resting on the Windows home directory already
            # being private to its user, not on there being nothing to protect.
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
class MigrationResult:
    """Facts learned while bringing one store forward to the current layout."""

    from_legacy: bool = False
    moved_to: Path | None = None
    broker: str | None = None
    discarded_brokers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RobotProfileStore:
    """The on-disk set of robots this machine has provisioned."""

    root: Path
    migration: MigrationResult = field(default_factory=MigrationResult, compare=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RobotProfileStore:
        store, legacy = cls._unopened_from_env(env)
        store._open(legacy)
        return store

    @classmethod
    def root_from_env(cls, env: Mapping[str, str] | None = None) -> Path:
        """Where the store lives, WITHOUT opening or validating it.

        For the callers that only need to name the directory — `uninstall` says what it will not
        touch. Opening there would refuse a store a newer version wrote, aborting the one command
        whose job is to clean up the older install that is asking.
        """
        return cls._unopened_from_env(env)[0].root

    @classmethod
    def _unopened_from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> tuple[RobotProfileStore, Path | None]:
        environ: Mapping[str, str] = os.environ if env is None else env
        override = environ.get(HOME_ENV)
        if override:
            return cls(_expand(override, environ)), None
        home = _home(environ)
        return cls(home / DEFAULT_SUBDIR), home / LEGACY_SUBDIR

    def _open(self, legacy: Path | None) -> None:
        if legacy is not None:
            self._migrate_legacy_home(legacy)
        self.check_layout()
        if self.root.is_dir() and self.layout_version() < LAYOUT_VERSION:
            object.__setattr__(self, "_migrating", True)
            try:
                self._migrate_to_layout_1()
            finally:
                object.__setattr__(self, "_migrating", False)
            self._ensure_root()  # stamps only now that every step has landed
        self._normalise_layout_marker()

    def _normalise_layout_marker(self) -> None:
        """Rewrite a JSON `.layout` back to the bare integer every build can parse.

        A build shipped briefly that wrote the whole record into `.layout` itself. This one reads
        that fine, which is the problem: without rewriting it, an older duplicate install goes on
        parsing the layout as 0, re-running the migration and rewriting every profile on every
        single command, and nothing here would ever have changed the file it chokes on.
        """
        marker = self.root / _LAYOUT_FILE
        try:
            text = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if not text.startswith("{"):
            return
        record = self._layout_marker()
        if record.get("layout_version") != str(LAYOUT_VERSION):
            return  # not ours to rewrite; check_layout() has already had its say
        with contextlib.suppress(OSError):
            _write_private(self.root / _LAYOUT_DETAIL_FILE, json.dumps(record, indent=2, sort_keys=True) + "\n")
            _write_private(marker, f"{LAYOUT_VERSION}\n")

    def _migrate_legacy_home(self, legacy: Path) -> None:
        """Move a pre-1 layout out of its hidden directory, once.

        Renamed rather than copied or symlinked: two directories that both look
        like the store is the state where somebody edits the wrong one. If the
        new location already exists the old one is left alone — a merge is not
        something to attempt silently around a private key.
        """
        if self.root.exists() or not legacy.is_dir():
            return
        try:
            legacy.rename(self.root)
            object.__setattr__(
                self,
                "migration",
                replace(self.migration, from_legacy=True, moved_to=self.root),
            )
        except OSError as exc:
            # Carrying on would start a second, empty store while the real one
            # stays hidden — every robot would look forgotten, and a second CA
            # would be generated beside the one they already trust.
            raise RobotProfileError(
                f"could not move {legacy} to {self.root}: {exc.strerror}. Move it "
                f"by hand, or set WHISKERLESS_HOME to point at it"
            ) from exc

    #: Set while hoisting a pre-1 store, so the writes it makes cannot stamp the
    #: layout before the whole migration has succeeded.
    _migrating: bool = field(default=False, compare=False, repr=False)

    def _migrate_to_layout_1(self) -> None:
        """Hoist a pre-1 store's per-robot broker and CA to where they now live.

        Before layout 1 every robot carried its own host, port and CA. Leaving
        them there would look like a machine with no broker and no authority — so
        `provision` would offer to generate a NEW CA, and accepting it would
        strand every robot already provisioned to trust the old one. Each rescue
        is a walk to a robot with a laptop, so this runs before anything asks.

        Reads the default robot's values, or the first if none is marked. They
        agreed with each other in practice; the old apparatus for reconciling
        them is exactly what this layout removed.
        """
        if not self.robots_dir.is_dir():
            return
        entries = [e for e in sorted(self.robots_dir.iterdir()) if e.is_dir()]
        if not entries:
            return
        default = self.get_default()
        chosen = next((e for e in entries if e.name == default), entries[0])

        if not self.has_broker():
            try:
                raw = json.loads((chosen / _PROFILE_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            # This runs from from_env(), so anything raising here takes EVERY
            # command down. A robot too damaged to read is one whose broker we
            # cannot hoist — not a reason to stop hoisting the CA below.
            if not isinstance(raw, dict):
                raw = {}
            hosts = _named_hosts(entries)
            # The chosen robot's address wins, but ANY robot's will do if that one
            # has none or cannot be read. Hoisting nothing while the cleanup below
            # strips `host` from the profiles would delete the only broker address
            # there was.
            host = raw.get("host")
            if not (isinstance(host, str) and host):
                host = next(iter(hosts), None)
            if isinstance(host, str) and host:
                self.save_broker(Broker(host=host))
                others = {found for found in hosts if found != host}
                object.__setattr__(
                    self,
                    "migration",
                    replace(
                        self.migration,
                        broker=host,
                        discarded_brokers=tuple(sorted(others)),
                    ),
                )

        if not self.has_ca_cert():
            # A stray ca.crt at the root predates the ca/ directory; a per-robot
            # ca.pem predates the store having one CA at all. Either is the
            # certificate these robots were provisioned to trust.
            #
            # EVERY robot is searched, not just the chosen one. The anchor can sit
            # under any of them — a robot added later may have none — and looking
            # at one while the cleanup below removes the rest is how a store's only
            # trust anchor gets destroyed. Losing it does not stop robots that
            # already run, but it makes `provision` offer a NEW authority, and
            # accepting that strands every robot that trusted the old one.
            # The chosen robot's anchor first: the broker address came from that
            # profile, and taking the CA from a different one pairs broker B with
            # CA A — every handshake then fails, and `setup` asks for the key of an
            # authority that is not the one in use.
            ordered = [self.root / _CA_CERT, chosen / _CA_FILE, *(e / _CA_FILE for e in entries)]
            candidates = [c for c in ordered if c.is_file()]
            for candidate in candidates:
                try:
                    pem = candidate.read_text(encoding="utf-8")
                except OSError:
                    # An unreadable SOURCE is skipped, not fatal: another robot may
                    # hold a readable copy of the same anchor. If NONE can be read
                    # the loop falls through to the check below.
                    continue
                # The WRITE is deliberately not guarded. Failing to store the
                # anchor while carrying on would stamp the layout, so the next run
                # skips the migration forever and `setup` offers a replacement
                # authority that every existing robot refuses.
                self.save_ca_cert_only(pem)
                break
            else:
                if candidates:
                    # Every copy there was is unreadable. Carrying on would let
                    # from_env() stamp the layout, so the next run skips the
                    # migration forever, `setup` offers a replacement authority,
                    # and every robot trusting the preserved one is stranded.
                    raise RobotProfileError(
                        f"none of {len(candidates)} certificate authority file(s) under "
                        f"{self.root} could be read, so the trust anchor your robots were "
                        "given has not been filed. Fix their permissions and run again — "
                        "the migration is deliberately not marked done"
                    )

        # Only once what the profiles carried is safely in the store. The cleanup
        # rewrites them without `host` and removes their `ca.pem`, so running it
        # over something that failed to hoist deletes the only copy there was.
        hoisted_broker = self.has_broker() or not _named_hosts(entries)
        hoisted_ca = self.has_ca_cert() or not any((e / _CA_FILE).is_file() for e in entries)
        if hoisted_broker and hoisted_ca:
            self._retire_pre_layout_leftovers(entries)

        # Last, so a hoist that raised — an unreadable CA, a full disk — is not
        # announced as an upgrade that happened. The layout stays at 0 and the
        # next run tries again; saying "upgraded" over that sends somebody looking
        # for changes their store has not got.
        #
        # Owed here rather than only where the directory is renamed: a store opened
        # through WHISKERLESS_HOME skips that rename and is hoisted by exactly this
        # method, so keying the notice on the move meant the one class of user who
        # placed their store deliberately heard nothing about credentials
        # disappearing.
        object.__setattr__(
            self,
            "migration",
            replace(self.migration, from_legacy=True),
        )

    def _retire_pre_layout_leftovers(self, entries: list[Path]) -> None:
        """Take the hoisted values back out of the files they came from.

        Hoisting alone leaves every robot's profile still carrying `host`,
        `port`, `verify_hostname` and `username` — all of which 0.2.0 stopped
        reading. They are inert, but they are also the settings somebody edits
        when the broker moves and then wonders why nothing changed.

        Rewriting through `save()` drops whatever is no longer a field, so this
        needs no list of dead keys to keep up to date, and `save()` also removes
        the per-robot `ca.pem` the store's CA has replaced.

        Runs from `from_env()`, so a failure here would take every command down
        over tidiness. Each robot is handled on its own and skipped if it cannot
        be read.
        """
        stored = self.ca_path.read_text(encoding="utf-8").strip() if self.has_ca_cert() else ""
        kept_broker = self.load_broker().host if self.has_broker() else None
        for entry in entries:
            try:
                raw = json.loads((entry / _PROFILE_FILE).read_text(encoding="utf-8"))
                named = raw.get("host") if isinstance(raw, dict) else None
            except (OSError, ValueError):
                named = None
            if isinstance(named, str) and named and named != kept_broker:
                # This robot's broker is not the one the store kept. Its profile is
                # the only remaining record of which address it belongs to, and the
                # advice is to split it into its own store — which needs that
                # address. Left intact, dead fields and all.
                continue
            legacy_ca = entry / _CA_FILE
            try:
                if legacy_ca.is_file() and legacy_ca.read_text(encoding="utf-8").strip() != stored:
                    # A DIFFERENT anchor. `save()` unlinks the per-robot copy, and
                    # the store keeps only one — so tidying this robot would destroy
                    # the trust anchor for whichever broker it belongs to. Left
                    # exactly where it is, dead fields and all, for whoever splits
                    # the store to find. The notice names the discarded broker.
                    continue
            except OSError:
                continue
            try:
                self.save(self.load(entry.name))
            except (RobotProfileError, OSError):
                continue

    def _layout_marker(self) -> dict[str, str]:
        """The marker as a mapping, whichever form it is in on disk.

        The 0.2.0 release candidates wrote a bare integer here. Reading both means a store written
        by one of them still reports its real layout instead of falling back to "pre-versioning"
        and re-running the layout-1 migration against a layout-1 store.
        """
        try:
            text = (self.root / _LAYOUT_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return {}
        detail: dict[str, str] = {}
        with contextlib.suppress(OSError, ValueError):
            beside = json.loads(
                (self.root / _LAYOUT_DETAIL_FILE).read_text(encoding="utf-8")
            )
            if isinstance(beside, dict):
                detail = {str(k): str(v) for k, v in beside.items()}
        try:
            loaded = json.loads(text)
        except ValueError:
            return {**detail, "layout_version": text}
        if isinstance(loaded, dict):
            # A store stamped by the build that briefly wrote JSON into `.layout` itself.
            return {**detail, **{str(k): str(v) for k, v in loaded.items()}}
        return {**detail, "layout_version": str(loaded)}


    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold an exclusive store lock for the duration of a mutation.

        Opened without truncating, so a refused acquisition never damages the file it is guarding.
        On Windows `fcntl` does not exist; the lock degrades to a no-op there rather than pretending,
        which is the same accommodation the mode bits get and is recorded for the same reason — the
        Home Assistant integration does not run on Windows, so the two-writer case cannot arise yet.
        """
        if not _HAVE_FLOCK:  # pragma: no cover - Windows accommodation
            yield
            return
        self._ensure_root()
        handle = os.fdopen(os.open(self.root / _LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600), "r+")
        try:
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RobotProfileError(
                            f"another whiskerless is writing to {self.root} and did not finish "
                            f"within {_LOCK_TIMEOUT_SECONDS:g}s — try again"
                        ) from None
                    time.sleep(0.05)
            yield
        finally:
            handle.close()

    def layout_version(self) -> int:
        """The structure version on disk. Absent marker means pre-versioning."""
        try:
            return int(self._layout_marker().get("layout_version", ""))
        except ValueError:
            return 0

    def check_layout(self) -> None:
        """Refuse a layout newer than this build understands.

        Never rewrite data we cannot read: a newer whiskerless may have moved or
        reshaped something, and a best-effort read would quietly drop whatever it
        added and then save the truncated result back.
        """
        if not self.root.is_dir():
            return
        found = self.layout_version()
        if found > LAYOUT_VERSION:
            # Name the version that can read it when the store says so. "Upgrade whiskerless" sends
            # someone to the releases page to guess; "upgrade to >= 0.3.0" does not.
            need = self._layout_marker().get("min_tool_version")
            upgrade = f"upgrade to whiskerless >= {need}" if need else "upgrade whiskerless"
            raise RobotProfileError(
                f"{self.root} was written by a newer whiskerless "
                f"(layout {found}; this build understands {LAYOUT_VERSION}) — {upgrade}"
                f", or point WHISKERLESS_HOME somewhere else"
            )

    @property
    def robots_dir(self) -> Path:
        return self.root / "robots"

    def _dir(self, serial: Serial) -> Path:
        return self.robots_dir / serial.value

    # --- the certificate authority ------------------------------------------
    @property
    def ca_path(self) -> Path:
        return self.root / _CA_DIR / _CA_CERT

    @property
    def ca_key_path(self) -> Path:
        return self.root / _CA_DIR / _CA_KEY

    @property
    def broker_dir(self) -> Path:
        return self.root / _BROKER_DIR

    def has_ca(self) -> bool:
        """Whether this machine can ISSUE — a certificate alone cannot sign."""
        return self.ca_path.is_file() and self.ca_key_path.is_file()

    def has_ca_cert(self) -> bool:
        """Whether a trust anchor is on file, with or without its key."""
        return self.ca_path.is_file()

    def load_ca(self) -> KeyPair:
        return pki.read_pair(self.ca_path, self.ca_key_path)

    def save_ca(self, ca: KeyPair) -> None:
        self._ensure_dir(_CA_DIR)
        _write_private(self.ca_path, ca.cert_pem)
        _write_private(self.ca_key_path, ca.key_pem)

    def save_ca_cert_only(self, cert_pem: str) -> None:
        """File a CA certificate with no key beside it.

        The state a 0.1.3 store arrives in, not one to build on purpose: the key
        lived elsewhere — an offline root, a secrets manager, somebody else's
        cluster — and the machine could tell a robot what to trust while issuing
        nothing. Since 0.2.0 every robot is issued a certificate, so `setup`
        resolves this on sight rather than leaving it. Kept because hoisting a
        migrated store has to be able to write exactly this, and so do the tests
        that cover what happens next.
        """
        self._ensure_dir(_CA_DIR)
        _write_private(self.ca_path, cert_pem)
        self.ca_key_path.unlink(missing_ok=True)

    # --- the one broker -----------------------------------------------------
    @property
    def broker_path(self) -> Path:
        return self.root / _BROKER_FILE

    def has_broker(self) -> bool:
        return self.broker_path.is_file()

    def load_broker(self) -> Broker:
        try:
            raw = json.loads(self.broker_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise RobotProfileError(
                "no broker is set up on this machine — run `whiskerless provision`"
            ) from None
        except (OSError, ValueError) as exc:
            raise RobotProfileError(f"could not read {self.broker_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise RobotProfileError(f"{self.broker_path} is not a JSON object")
        host = raw.get("host")
        if not isinstance(host, str) or not host:
            raise RobotProfileError(f"{self.broker_path} has no broker host")
        # A store written before these were dropped still carries `port` and
        # `verify_hostname`. They are ignored rather than rejected: the file is
        # rewritten without them on the next save, and refusing to open a store
        # over a key that no longer means anything would strand somebody's CA.
        raw_auth = raw.get("auth")
        try:
            auth = AuthMode(raw_auth) if raw_auth is not None else AuthMode.MUTUAL
        except ValueError:
            # Refused, not defaulted. A mode nobody recognises is somebody's
            # typo or a store from a newer build, and quietly reading it as
            # `mutual` would hand a robot an identity in a setup that asked for
            # none — the silent downgrade this field exists to prevent.
            raise RobotProfileError(
                f"{self.broker_path} names an authentication mode this build does "
                f"not know ({raw_auth!r}). Known modes: "
                f"{', '.join(m.value for m in AuthMode)}"
            ) from None
        return Broker(host=host, auth=auth)

    def save_broker(self, broker: Broker) -> None:
        self._ensure_root()
        _write_private(
            self.broker_path,
            json.dumps(
                {"host": broker.host, "auth": broker.auth.value},
                indent=2,
            )
            + "\n",
        )

    def settings(self, *, client_id: str | None = None) -> MqttSettings:
        """How to reach the broker, with whatever identity this machine has.

        Assembled here rather than on a profile because none of it is per-robot:
        one broker, one CA, one client certificate for this machine.
        """
        # NOT `assert_usable()`: connecting needs a certificate to present, not a
        # key to sign with. A store whose CA key has gone missing can still talk to
        # its broker perfectly well with the identity it already holds, and failing
        # `state` over a key that only matters at the next provision would be a
        # guard firing at the wrong moment.
        broker = self.load_broker()
        ca_pem = self.ca_path.read_text(encoding="utf-8") if self.has_ca_cert() else None
        # The CLI connects the way the robots do. In ANONYMOUS mode they present
        # a certificate this broker's listener cannot check, so it accepts
        # anonymous clients — and a CLI that presented one anyway would be the
        # single client on that listener held to a different standard, which is
        # exactly the split that makes a broker hard to reason about.
        if broker.auth is AuthMode.ANONYMOUS:
            identity = None
        elif self.has_client():
            identity = self.load_client()
            if broker.auth is AuthMode.SUPPLIED and not pki.is_current(identity.cert_pem):
                # Presenting it gets a TLS failure naming nothing, and nothing here
                # can mint a replacement — so this is the only place the reason can
                # be said. MUTUAL is left alone: `setup` reissues its own.
                raise RobotProfileError(
                    f"this machine's certificate in {self.root / _CLIENT_DIR} is not "
                    "valid at the moment — the broker will refuse it. Issue another "
                    "from your CA and file it with `whiskerless setup --client-cert "
                    "<file> --client-key <file>`"
                )
        elif broker.auth is AuthMode.SUPPLIED:
            # Falling through to None here would connect anonymously — and on a
            # listener that still allows that, succeed. The store would go on
            # saying `supplied` while nothing about it was, which is the exact
            # silence writing the mode down was meant to end. Nothing here can
            # mint a replacement either, so it has to be said.
            raise RobotProfileError(
                f"{self.broker_path} says auth is 'supplied', but this machine's "
                f"certificate is not in {self.root / _CLIENT_DIR}. Nothing here can "
                "issue another — supply it again with `whiskerless setup "
                "--client-cert <file> --client-key <file>`"
            )
        else:
            # MUTUAL, and re-creatable: `setup` mints one from the CA it holds.
            identity = None
        return broker.settings(ca_pem=ca_pem, identity=identity, client_id=client_id)

    def has_client(self) -> bool:
        client = self.root / _CLIENT_DIR
        return (client / _CLIENT_CERT).is_file() and (client / _CLIENT_KEY).is_file()

    def load_client(self) -> KeyPair:
        client = self.root / _CLIENT_DIR
        return pki.read_pair(client / _CLIENT_CERT, client / _CLIENT_KEY)

    def forget_client(self) -> None:
        """Drop this machine's identity, for the one case that invalidates it.

        Replacing the certificate authority does: the stored certificate was
        signed by the authority just retired, so a broker asking for one would
        refuse it — while everything here reported success. `client_identity()`
        only mints when none is on file, so the old one has to go first.
        """
        client = self.root / _CLIENT_DIR
        for name in (_CLIENT_CERT, _CLIENT_KEY):
            (client / name).unlink(missing_ok=True)

    def forget_issued_certificates(self) -> None:
        """Forget which certificate each robot was given, for a CA replacement.

        `cert_serial` names the certificate currently issued — a reissue replaces it — and it is what
        distinguishes a robot holding one of ours from a robot still on its
        factory certificate. Replacing the authority invalidates every one of them
        at once — so leaving the serials behind would report robots as current
        while the broker is about to refuse them.
        """
        # Every identity directory, not every readable profile: an aborted
        # provision or a half-removed robot leaves one behind that `list_robot_profiles()`
        # skips, and `robot_identity()` would later hand that stale certificate
        # back as a cache hit — signed by the authority just retired, and refused
        # by the broker the moment it is used.
        if self.robots_dir.is_dir():
            for entry in sorted(self.robots_dir.iterdir()):
                if entry.is_dir():
                    for name in (_CLIENT_CERT, _CLIENT_KEY):
                        (entry / _CLIENT_DIR / name).unlink(missing_ok=True)
        for profile in self.list_robot_profiles():
            if profile.cert_serial is not None:
                self.save(replace(profile, cert_serial=None))

    def save_client(self, pair: KeyPair) -> None:
        client = self._ensure_dir(_CLIENT_DIR)
        _write_private(client / _CLIENT_CERT, pair.cert_pem)
        _write_private(client / _CLIENT_KEY, pair.key_pem)

    def save_broker_certs(self, pair: KeyPair) -> Path:
        """Write the broker's own certificate, and return where it landed.

        Deliberately NOT a copy of ``ca/ca.crt`` as well, tempting as a
        self-contained folder is: two stored copies of one certificate raise the
        question of which is authoritative, and there is no good answer.
        """
        broker = self._ensure_dir(_BROKER_DIR)
        _write_private(broker / _SERVER_CERT, pair.cert_pem)
        _write_private(broker / _SERVER_KEY, pair.key_pem)
        return broker

    def client_identity(self) -> KeyPair:
        """This machine's client certificate, minting one the first time."""
        if self.has_client():
            return self.load_client()
        pair = pki.issue_client(self.load_ca(), pki.client_common_name())
        self.save_client(pair)
        return pair

    # --- what each robot presents -------------------------------------------
    #
    # Kept, where it used to be minted for the write and dropped. Two reasons, and
    # the second is the one that forces it: a supplied certificate CANNOT be
    # recreated — losing it means going back to whoever signed it — and a robot
    # re-provisioned (a new WiFi password is enough) should still be the same
    # client to the broker afterwards, or every ACL and log line keyed to its
    # certificate moves under it.
    #
    # This is not a new exposure in the default mode. `ca/ca.key` is already here,
    # so anyone who can read the store can mint any identity in it; a copy of what
    # was minted adds nothing they could not make. In SUPPLIED mode there is no CA
    # key to steal and these are the only private keys present — which is the
    # whole point of that mode.
    def robot_client_dir(self, serial: str | Serial) -> Path:
        return self._dir(Serial(serial) if isinstance(serial, str) else serial) / _CLIENT_DIR

    def has_robot_identity(self, serial: str | Serial) -> bool:
        client = self.robot_client_dir(serial)
        return (client / _CLIENT_CERT).is_file() and (client / _CLIENT_KEY).is_file()

    def load_robot_identity(self, serial: str | Serial) -> KeyPair:
        client = self.robot_client_dir(serial)
        return pki.read_pair(client / _CLIENT_CERT, client / _CLIENT_KEY)

    def save_robot_identity(self, serial: str | Serial, pair: KeyPair) -> None:
        client = self.robot_client_dir(serial)
        client.mkdir(parents=True, exist_ok=True)
        client.chmod(0o700)
        _write_private(client / _CLIENT_CERT, pair.cert_pem)
        _write_private(client / _CLIENT_KEY, pair.key_pem)

    def forget_robot_identity(self, serial: str | Serial) -> None:
        client = self.robot_client_dir(serial)
        for name in (_CLIENT_CERT, _CLIENT_KEY):
            (client / name).unlink(missing_ok=True)

    def robot_identity(
        self, serial: str | Serial, *, reissue: bool = False, persist: bool = True
    ) -> KeyPair:
        """What this robot presents to the broker, minting one the first time.

        The same shape as `client_identity()` for this machine, and deliberately
        so: one rule for every identity the store is responsible for, whether it
        belongs to a laptop or a litter box.

        `reissue` is the escape hatch a cached identity needs — a key believed
        compromised has to be replaceable without deleting the robot's profile and
        the measurements on it. Only meaningful where the store can sign; a
        supplied identity is replaced by supplying another.

        `persist` is what provisioning turns off. Writing a replacement before the
        robot has accepted it means an abort — a failed scan, a declined
        confirmation — leaves the store holding a certificate the robot does not
        have, and in `supplied` mode leaves the previous one deleted with nothing
        able to recreate it.
        """
        if not reissue and self.has_robot_identity(serial):
            return self.load_robot_identity(serial)
        parsed = Serial(serial) if isinstance(serial, str) else serial
        pair = pki.issue_client(self.load_ca(), parsed.value)
        if persist:
            self.save_robot_identity(parsed, pair)
        return pair

    def assert_usable(self, broker: Broker | None = None) -> None:
        """Refuse a stored mode the files on disk cannot actually carry out.

        Called where an identity may have to be MINTED or handed over — `setup`
        and `provision` — not on the way to the broker. Connecting needs something
        to present, which a store holds already; signing is a separate capability
        and only the next robot needs it.

        The whole value of writing the mode down is that its absence stops being
        ambiguous — so a mode that no longer matches has to be an error here,
        loudly, and not a downgrade to whatever the files happen to support. That
        downgrade is the failure this field was added to remove.
        """
        mode = (broker or self.load_broker()).auth
        if mode is AuthMode.MUTUAL and not self.has_ca():
            raise RobotProfileError(
                f"{self.broker_path} says auth is 'mutual', which means whiskerless "
                f"signs every identity — but {self.ca_key_path} is not there. Put the "
                "key back, or run `whiskerless setup --auth supplied` if identities "
                "are issued elsewhere now"
            )
        if mode is not AuthMode.MUTUAL and not self.has_ca_cert():
            raise RobotProfileError(
                f"{self.broker_path} says auth is {mode.value!r}, which still needs the "
                f"CA certificate the robots were told to trust — {self.ca_path} is not "
                "there. Supply it with `whiskerless setup --ca <file>`"
            )

    def _ensure_root(self) -> None:
        # Created explicitly rather than by mkdir(parents=True), which would give
        # the directory umask permissions — and this one holds the CA key.
        # Parents get ordinary permissions; the store itself does not. Splitting
        # the two is what lets WHISKERLESS_HOME point somewhere that does not
        # exist yet without either failing or making its ancestors 0700.
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(exist_ok=True)
        self.root.chmod(0o700)
        marker = self.root / _LAYOUT_FILE
        if not marker.is_file() and not self._migrating:
            # Never stamped mid-migration. A marker written before the CA is
            # hoisted would make the next run skip the unfinished work forever,
            # and `setup` would then generate a replacement CA that every
            # existing robot refuses.
            # A BARE INTEGER, because every build that has ever shipped parses this file with
            # `int()`. Writing JSON here made an older duplicate install read the layout as 0,
            # re-run the layout-1 migration over a layout-1 store, rewrite every profile and
            # repeat its migration warning on every single command — for as long as both
            # versions were installed, since the marker it could not read never changed.
            _write_private(marker, f"{LAYOUT_VERSION}\n")
            # The richer facts live BESIDE it, in a file older builds never look at. Only this
            # build needs them, and only to name the version that can read a newer store.
            _write_private(
                self.root / _LAYOUT_DETAIL_FILE,
                json.dumps(
                    {
                        "layout_version": str(LAYOUT_VERSION),
                        "tool_version": _tool_version(),
                        "min_tool_version": _LAYOUT_SINCE[LAYOUT_VERSION],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )

    def _ensure_dir(self, name: str) -> Path:
        self._ensure_root()
        directory = self.root / name
        directory.mkdir(exist_ok=True)
        directory.chmod(0o700)
        return directory

    @_locked
    def save(self, profile: RobotProfile) -> None:
        """Write a profile, replacing whatever was there.

        For a caller that composed the profile itself. A caller that READ one first, changed a
        field and is writing it back must use `update()` instead — see the note there.
        """
        self._save_unlocked(profile)

    @_locked
    def update(
        self, serial: str, transform: Callable[[RobotProfile], RobotProfile]
    ) -> RobotProfile:
        """Read, change and write one profile with the lock held across all three.

        `save()` alone serialises only the WRITE. Two commands that each read the profile first —
        `rename` and a calibration write, say — could both read the old object and then save
        different replacements, and the second silently reverted the first. Nothing warned: both
        commands reported success, and the lost change was only visible later.
        """
        # `load()` takes no lock of its own, so calling it here is safe under ours.
        updated = transform(self.load(serial))
        self._save_unlocked(updated)
        return updated

    def _save_unlocked(self, profile: RobotProfile) -> None:
        directory = self._dir(profile.serial)
        # One path establishes the root, so the layout marker cannot be missed by
        # whichever operation happens to run first on a fresh machine.
        self._ensure_dir("robots")
        # A robot whose anchor is preserved keeps its `host` too. The store holds one
        # broker, so this field is inert — but it is the only record of WHICH broker
        # the preserved authority belongs to, and the migration notice tells the
        # reader to split that robot into its own store, which needs the address.
        stray = directory / _CA_FILE
        preserving = stray.is_file() and not self._is_store_anchor(stray)
        payload = {
            "serial": profile.serial.value,
            "serial_verified": profile.serial.verified,
            "name": profile.name,
            "wifi_ssid": profile.wifi_ssid,
            "litter_full_mm": profile.litter_full_mm,
            "litter_empty_mm": profile.litter_empty_mm,
            "cert_serial": profile.cert_serial,
        }
        if preserving:
            # Absent rather than null when there is nothing to carry: a `host` key
            # holding nothing reads as a broker that was cleared on purpose.
            carried = self._recorded_host(directory)
            if carried:
                payload["host"] = carried
        _write_private(directory / _PROFILE_FILE, json.dumps(payload, indent=2) + "\n")
        # There is one CA for the whole store now, so a per-robot copy is USUALLY
        # a leftover from an older layout, removed rather than left for load() to
        # resurrect against a broker it no longer matches.
        #
        # Unless it differs from the store's, in which case it is the only copy of
        # some other authority — the case the layout-1 migration deliberately
        # declines to touch. Unlinking it here would undo that protection at the
        # first rename or calibration, which is to say silently and long after
        # anybody connects the two.
        if not preserving:
            stray.unlink(missing_ok=True)

    @staticmethod
    def _recorded_host(directory: Path) -> str | None:
        """The broker address a pre-layout-1 profile carried, if it is still there."""
        try:
            raw = json.loads((directory / _PROFILE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        host = raw.get("host") if isinstance(raw, dict) else None
        return host if isinstance(host, str) and host else None

    def _is_store_anchor(self, candidate: Path) -> bool:
        """Whether this file is a copy of the store's own CA, and provably so.

        Unreadable answers False: the destructive branch is the one that needs
        proof, and there is no way to put back what unlinking removes.
        """
        if not self.has_ca_cert():
            return False
        try:
            return candidate.read_text(encoding="utf-8").strip() == (
                self.ca_path.read_text(encoding="utf-8").strip()
            )
        except OSError:
            return False

    def load(self, serial: str) -> RobotProfile:
        parsed = Serial(serial)
        path = self._dir(parsed) / _PROFILE_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise RobotProfileError(
                f"no saved profile for {parsed.value} — run `whiskerless provision` first, "
                "or pass --host explicitly"
            ) from None
        except (OSError, ValueError) as exc:
            raise RobotProfileError(f"could not read the profile for {parsed.value}: {exc}") from exc
        if not isinstance(raw, dict):
            raise RobotProfileError(f"the profile for {parsed.value} is not a JSON object")

        return RobotProfile(
            # The directory name is the identity — it is what `load` and `resolve`
            # key on. The serial inside the JSON is there to be readable, and a
            # hand-edited mismatch must not make a robot answer to two names.
            serial=Serial(parsed.value, bool(raw.get("serial_verified"))),
            name=str(raw.get("name") or ""),
            wifi_ssid=str(raw.get("wifi_ssid") or ""),
            # Hand-edited garbage here loses the calibration, not the robot:
            # an unreachable profile is a far worse outcome than an unanchored
            # percentage, which the next `calibrate` press restores.
            litter_full_mm=_optional_int(raw.get("litter_full_mm")),
            litter_empty_mm=_optional_int(raw.get("litter_empty_mm")),
            cert_serial=raw.get("cert_serial") if isinstance(raw.get("cert_serial"), str) else None,
        )

    def list_robot_profiles(self) -> tuple[RobotProfile, ...]:
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
            except RobotProfileError:
                continue
        return tuple(found)

    def damaged(self) -> tuple[tuple[str, str], ...]:
        """The robot directories that no longer load, each with the reason."""
        broken = []
        for entry in self._entries():
            try:
                self.load(entry.name)
            except RobotProfileError as exc:
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
        """The profile to act on: the named one, the default, or the only one.

        `serial` accepts a display NAME as well as a serial, because a robot the user has called
        "Upstairs" should be selectable by that — being made to type `LR4C…` for a robot you named
        is exactly the friction that stops people naming them. The serial is tried first: it is the
        identity, and a name is only a label, so a name that happens to look like a serial must
        never shadow the real one.

        Deliberately does NOT prompt. This is a library call with non-CLI callers, so ambiguity
        raises here and the CLI layer decides whether a person is present to ask.
        """
        if serial:
            try:
                return self.load(serial)
            except RobotProfileError:
                # An existing serial DIRECTORY means the answer is that robot, damaged or not.
                # Without this, a profile that failed to load fell through to the name search —
                # and a healthy robot whose display name happened to equal the requested serial
                # answered for it, sending a command aimed at one physical robot to another.
                # The flag is computed inside the suppression and acted on OUTSIDE it: a bare
                # `raise` in there re-raises a RobotProfileError, which is a WhiskerlessError, so
                # `suppress` swallowed the very error this branch exists to propagate.
                existing = False
                with contextlib.suppress(ValueError, WhiskerlessError):
                    existing = self._dir(Serial(serial)).is_dir()
                if existing:
                    raise
                # EVERY match, not the first. Nothing stops two robots being called "Bathroom" —
                # neither provisioning nor `rename` checks — and returning the first serial-sorted
                # one meant `forget Bathroom` removed a robot while printing the name of the robot
                # the user meant. A name that identifies two things identifies neither.
                matched = [p for p in self.list_robot_profiles() if p.display_name == serial]
                if len(matched) == 1:
                    return matched[0]
                if matched:
                    serials = ", ".join(p.serial.value for p in matched)
                    raise AmbiguousRobotError(
                        f"{serial!r} is the name of more than one robot ({serials}) — "
                        "use the serial, or rename one of them"
                    ) from None
                raise
        default = self.get_default()
        if default:
            return self.load(default)
        known = self.list_robot_profiles()
        if len(known) == 1:
            return known[0]
        if not known:
            raise RobotProfileError(
                "no robots are set up on this machine — run `whiskerless provision` first"
            )
        names = ", ".join(profile.serial.value for profile in known)
        raise RobotProfileError(
            f"several robots are set up ({names}) — pick one with --serial, "
            "or choose a default with `whiskerless use <serial>`"
        )

    def get_default(self) -> str | None:
        try:
            value = (self.root / _DEFAULT_FILE).read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return None
        return value or None

    @_locked
    def set_default(self, serial: str) -> None:
        parsed = Serial(serial)
        if not (self._dir(parsed) / _PROFILE_FILE).is_file():
            raise RobotProfileError(f"no saved profile for {parsed.value}")
        _write_private(self.root / _DEFAULT_FILE, parsed.value + "\n")

    @_locked
    def forget(self, serial: str) -> None:
        """Remove a robot's stored profile. The robot itself is untouched."""
        parsed = Serial(serial)
        directory = self._dir(parsed)
        if not directory.is_dir():
            raise RobotProfileError(f"no saved profile for {parsed.value}")
        for name in (_PROFILE_FILE, _CA_FILE):
            (directory / name).unlink(missing_ok=True)
        # The identity is this store's, so forgetting the robot forgets it too.
        # Left behind it would be a private key belonging to a robot nobody here
        # remembers, and — because the directory would stay non-empty — the robot
        # would come back as damaged in `robots`, unremovable by a second forget,
        # and silently reused by the next provision of that serial.
        self.forget_robot_identity(parsed)
        with contextlib.suppress(OSError):
            self.robot_client_dir(parsed).rmdir()
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
