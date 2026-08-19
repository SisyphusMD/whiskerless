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
    default                        serial used when none is given

**One secret lives here on purpose: the CA private key.** It is archival — it
must survive machine loss, and every tool on earth keeps CA keys as files
because you have to carry and archive them. Everything else is either public or
not stored at all: the WiFi passphrase is asked for at the robot and forgotten,
and a robot's own client certificate is written to the robot and never kept.
Files are 0600 and directories 0700 throughout.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import pki
from .exceptions import ProfileError
from .mqtt import DEFAULT_TLS_PORT, MqttSettings
from .pki import KeyPair

HOME_ENV = "WHISKERLESS_HOME"
#: Deliberately NOT hidden. This directory holds the CA private key, and the one
#: instruction that matters about it — back this up — is useless if the folder is
#: invisible in a file manager. Matches the sibling dreame-valetudo project.
DEFAULT_SUBDIR = "whiskerless"
#: Where a pre-1 layout lived. Migrated forward on first sight, never read in place.
LEGACY_SUBDIR = ".whiskerless"

#: Set for the life of the process by the run that hoists a pre-0.2.0 store,
#: whether or not the store also moved. The CLI reports it once, because that run
#: is the only moment anything knows for certain that somebody is upgrading rather
#: than starting fresh — and 0.2.0 changes things about their setup that they did
#: not ask for and cannot see.
MIGRATED_FROM_LEGACY = False

#: Broker addresses found on other robots while hoisting, and not kept. Before
#: layout 1 each robot carried its own, so two of them could in principle name
#: two brokers; one store now holds one. Almost certainly nobody's setup, but
#: picking silently would leave a robot pointed somewhere that is not theirs.
MIGRATED_DISCARDED_BROKERS: tuple[str, ...] = ()

#: Where the store was moved to, and which broker was kept — captured as it
#: happens so the CLI can report it without reopening the store. Reopening would
#: re-run a migration that may have just failed, and that second failure would
#: replace the error already reported.
MIGRATED_TO: Path | None = None
MIGRATED_BROKER: str | None = None

#: On-disk STRUCTURE version, deliberately separate from the release version: a
#: stable build and a release candidate share a layout freely, and most releases
#: do not touch it. Bumped only by a real structural change, and every bump ships
#: with the migration that reaches it.
LAYOUT_VERSION = 1
_LAYOUT_FILE = ".layout"

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
    # secret, and the only trace kept of it — the certificate itself lives on the
    # robot alone. Nothing reads this today; it exists so a revocation list can be
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
            store = cls(_expand(override, environ))
        else:
            store = cls(_home(environ) / DEFAULT_SUBDIR)
            store._migrate_legacy_home(_home(environ) / LEGACY_SUBDIR)
        store.check_layout()
        if store.root.is_dir() and store.layout_version() < LAYOUT_VERSION:
            object.__setattr__(store, "_migrating", True)
            try:
                store._migrate_to_layout_1()
            finally:
                object.__setattr__(store, "_migrating", False)
            store._ensure_root()  # stamps only now that every step has landed
        return store

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
            global MIGRATED_FROM_LEGACY, MIGRATED_TO
            MIGRATED_FROM_LEGACY = True
            MIGRATED_TO = self.root
        except OSError as exc:
            # Carrying on would start a second, empty store while the real one
            # stays hidden — every robot would look forgotten, and a second CA
            # would be generated beside the one they already trust.
            raise ProfileError(
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
                global MIGRATED_BROKER
                MIGRATED_BROKER = host
                others = {found for found in hosts if found != host}
                if others:
                    global MIGRATED_DISCARDED_BROKERS
                    MIGRATED_DISCARDED_BROKERS = tuple(sorted(others))

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
                    raise ProfileError(
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
        global MIGRATED_FROM_LEGACY
        MIGRATED_FROM_LEGACY = True

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
            except (ProfileError, OSError):
                continue

    def layout_version(self) -> int:
        """The structure version on disk. Absent marker means pre-versioning."""
        try:
            return int((self.root / _LAYOUT_FILE).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
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
            raise ProfileError(
                f"{self.root} was written by a newer whiskerless "
                f"(layout {found}; this build understands {LAYOUT_VERSION}) — upgrade "
                f"whiskerless, or point WHISKERLESS_HOME somewhere else"
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
            raise ProfileError(
                "no broker is set up on this machine — run `whiskerless provision`"
            ) from None
        except (OSError, ValueError) as exc:
            raise ProfileError(f"could not read {self.broker_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ProfileError(f"{self.broker_path} is not a JSON object")
        host = raw.get("host")
        if not isinstance(host, str) or not host:
            raise ProfileError(f"{self.broker_path} has no broker host")
        # A store written before these were dropped still carries `port` and
        # `verify_hostname`. They are ignored rather than rejected: the file is
        # rewritten host-only on the next save, and refusing to open a store over a
        # key that no longer means anything would strand somebody's CA.
        return Broker(host=host)

    def save_broker(self, broker: Broker) -> None:
        self._ensure_root()
        _write_private(
            self.broker_path,
            json.dumps(
                {"host": broker.host},
                indent=2,
            )
            + "\n",
        )

    def settings(self, *, client_id: str | None = None) -> MqttSettings:
        """How to reach the broker, with whatever identity this machine has.

        Assembled here rather than on a profile because none of it is per-robot:
        one broker, one CA, one client certificate for this machine.
        """
        ca_pem = self.ca_path.read_text(encoding="utf-8") if self.has_ca_cert() else None
        identity = self.load_client() if self.has_client() else None
        return self.load_broker().settings(
            ca_pem=ca_pem, identity=identity, client_id=client_id
        )

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

        `cert_serial` is the only trace kept of a robot's identity, and it is what
        distinguishes a robot holding one of ours from a robot still on its
        factory certificate. Replacing the authority invalidates every one of them
        at once — so leaving the serials behind would report robots as current
        while the broker is about to refuse them.
        """
        for profile in self.list_profiles():
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
            _write_private(marker, f"{LAYOUT_VERSION}\n")

    def _ensure_dir(self, name: str) -> Path:
        self._ensure_root()
        directory = self.root / name
        directory.mkdir(exist_ok=True)
        directory.chmod(0o700)
        return directory

    def save(self, profile: RobotProfile) -> None:
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
            raise ProfileError(
                f"no saved profile for {parsed.value} — run `whiskerless provision` first, "
                "or pass --host explicitly"
            ) from None
        except (OSError, ValueError) as exc:
            raise ProfileError(f"could not read the profile for {parsed.value}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ProfileError(f"the profile for {parsed.value} is not a JSON object")

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
