# How whiskerless authenticates, and why

A record of the decisions behind the certificate work, kept because the *reasoning*
is the part that gets lost. Most of these look arbitrary from the outside and are
not; several reverse an earlier position in this project, and knowing which way the
argument ran is what stops it being re-litigated.

## The fact everything else follows from

**The Litter-Robot cannot send a username or a password.** There is no field for
one: not in the BLE provisioning schema, not among the NVS keys the provisioning
component persists, and not as a string anywhere in the firmware. It was built for
AWS IoT, which authenticates clients by certificate. Verified by decoding the
firmware's protobuf-c descriptor tables and the `mqtt` NVS namespace's contiguous
key block — see [the app-onboarding capture](../devices/litter-robot-4/provisioning/app-onboarding-capture.md).

Two consequences, and neither is negotiable:

* The listener the robot connects to must accept it **by certificate or
  anonymously**. A password-protected listener locks it out permanently.
* The **port is 8883** and cannot move. It is a compile-time constant loaded at
  exactly one place in the firmware; 443 and 1883 appear nowhere.

## Decisions

### Every robot gets an identity — how, is written down — decided 2026-08-19

Superseding the decision below on the same day, and narrowly. That one was right
about the failure and wrong about the remedy: it enforced "the store must be able
to **sign**", when what the fleet actually needs is "every robot must end up with
an identity this store can **account for**". Signing is one way to get there.
Being handed the certificate is another, and it is equally verifiable — it chains
to the CA, it is not expired, it matches its key.

The case that forced it: somebody whose CA lives in cert-manager, Vault, or an
offline root, who hands whiskerless the CA certificate and a certificate per
robot, and never lets the signing key near a laptop. That is **stricter** than
the default, not weaker, and the previous decision refused it.

So the store records **how it authenticates**, in `broker.json`:

| `auth` | who issues a robot's identity | this machine's own | the listener |
|---|---|---|---|
| `mutual` (default) | whiskerless, from the CA key it holds | issued here | either |
| `supplied` | you, from a key that never arrives here | you supply it | either |
| `anonymous` | nobody — the robot keeps its factory certificate | none presented | must allow anonymous |

Three properties are load-bearing:

**It is stored, never derived.** The same absence — no `ca.key` — means "I keep it
in cert-manager" and "I lost it", and those want opposite handling. Derived, the
second silently becomes the first, which is the exact failure the decision below
was written about. Written down, a mode the files can no longer carry out is an
error from `assert_usable()`, naming both.

**It persists.** `setup --host <new address>` is a routine thing to run, and a
per-run flag defaulting to `mutual` would move a cert-manager store back onto
certificates whiskerless signs — on the second run, not the first, which is the
kind of change nobody goes looking for.

**The CLI authenticates the way the robots do.** One listener, one standard. A
CLI presenting a certificate on a listener that accepts anonymous clients would
be the single client on it held to a different rule. A `supplied` store that has
lost its own certificate is an error rather than an anonymous connection, which
on a permissive listener would otherwise succeed while the mode went on claiming
otherwise.

`supplied` is refused while `ca/ca.key` is still on the machine, because the mode
states that it is not — and `setup` says to **move** that file, not delete it: if
the authority you issue from turns out not to be this one, the copy here is the
only thing that can still sign for the robots you already have. `anonymous` makes
no claim about the key and leaves it alone.

Everything handed to whiskerless is checked before it is filed, because each of
these otherwise surfaces at the robot as a handshake failure that names none of
them: it must chain to the store's CA, be valid *now* (not merely unexpired —
a not-yet-valid certificate is refused by the broker until the hour it starts),
not be a CA itself, and carry the robot's serial as its common name. That last
one is not cosmetic: `use_identity_as_username` takes the broker username from it,
so another robot's certificate connects this robot under another robot's name and
ACLs. A missing common name and an `extendedKeyUsage` without `clientAuth` are
warned about rather than refused — both work on plenty of brokers.

The worst of them is the one a signature check alone cannot catch: **a CA
certificate is signed by the stored authority when it IS the stored authority**,
so `--robot-cert ca.crt --robot-key ca.key` passes a chain check and writes the
signing key of the whole fleet into a litter box.

Validity is rechecked every time rather than trusted because it passed once — a
changed WiFi password is a re-provision, and an authority managed elsewhere can
expire between two robots. Where the store can sign, an expired certificate of
ours is quietly replaced, because the fix is free. Where it cannot, it is an error
naming the file, because presenting it produces a TLS failure that names nothing.

Nothing is filed until it has passed. Certificates are read, checked, and written
only once they are known good and — for a robot — only once the robot has accepted
them, so an abort or a rejected replacement leaves the working one exactly as it
was. In `supplied` mode that matters more than tidiness: the copy in the store may
be the only one.

`anonymous` is the mode the decision below deleted, back as something you ask for
by name. What was wrong with it was never the posture — it was that it was the
*default outcome of upgrading*, and invisible. Typed out, it is neither.

### Identities are stored, not minted per run — decided 2026-08-19

A robot's certificate used to be issued during provisioning, written over BLE, and
dropped. Now it is kept, at `robots/<serial>/client/`, exactly where this
machine's own has always been kept at `client/`.

Two reasons, and the second forces it. A supplied certificate **cannot be
recreated** — losing it means going back to whoever signed it. And a robot that
gets re-provisioned (a changed WiFi password is enough) should still be the same
client to the broker afterwards, or every ACL, every `use_identity_as_username`
log line, and every `cert_serial` on file moves under it.

The rule this leaves is one rule, not two: **the store keeps what it cannot
recreate, and caches what it can.** Same slot either way, so nothing downstream
has to know which it is holding.

It is not a new exposure in the default mode. `ca/ca.key` is already in the store,
so anyone who can read it can mint any identity in the fleet; a copy of what was
already minted adds nothing they could not produce. In `supplied` mode there is no
CA key to take, and these are the only private keys present — which is the point
of that mode. `--reissue` replaces one believed compromised without touching the
profile beside it.

Because provisioning now leaves behind material a backup taken before it does not
have, `provision` says so when it finishes. In `supplied` mode that material
cannot be produced again by anything on this machine, so a backup from before that
moment is not stale — it is missing the only copy.

### A store must be able to sign — decided 2026-08-19, superseded the same day

Until 0.2.0 a store could hold a CA *certificate* with no key. The robot was told
whom to trust and kept its factory identity; the broker's listener stayed
anonymous. It was a real arrangement — somebody whose signing key lives in a
secrets manager — and it is now refused.

What made it untenable was not the posture but the silence. It is also exactly
what an upgraded 0.1.3 store looks like, because the certificate hoists across
from the robot profiles and the key was never in there to hoist. So the default
outcome of upgrading was a store that could not issue anything, that said nothing
about it, and that looked identical to a working one until somebody was standing
at a robot with the pairing window open.

Two modes also cost more than they returned: `can_issue` forked `_ensure_pki`,
`_refresh_server_cert`, provisioning and the broker documentation, and the weaker
branch was the one nobody exercised.

So a certificate without its key is now an unfinished setup rather than a choice.
`setup` resolves it once — file the key, or generate a new authority and accept
re-provisioning every robot — and everything downstream can assume a store that
signs.

> Superseded by the decision above, which keeps this one's diagnosis and drops
> its remedy: the silence was the problem, and a stated mode removes it without
> refusing the arrangement.

**The anonymous listener stays supported.** That is a different question: the
robot arrives from the factory with a Whisker certificate, and requiring the
broker to demand client certificates would make a private key mandatory for the
simplest possible setup, where losing it costs a physical visit to every robot.
There is no opt-out at provisioning either. `--no-client-cert` was removed with
the same reasoning: the store holds a signing key by definition, and a robot
holding a certificate still connects to a listener that does not ask for one,
while a robot without one cannot connect to a listener that does. The flag only
created a way to end up unable to tighten the broker later, discovered at the
robot.



### Certificates only — broker username/password removed from the project

Running two authentication schemes against one broker bought nothing but
complexity: the robot could never use the password half, so it existed solely for
the CLI, which is perfectly capable of presenting a certificate like the robot
does. `--username`, `--password`, `WHISKERLESS_PASSWORD` and the profile fields
are gone.

This does **not** touch anybody's other MQTT clients. Home Assistant, Zigbee2MQTT
and friends authenticate on their own listener with passwords, and the whiskerless
integration never opens its own broker connection — it rides Home Assistant's.

### `cryptography`, not an `openssl` subprocess

Certificate generation is core function now, not a nicety, so it must not hinge on
a binary that stock Windows does not ship. `cryptography` has prebuilt wheels for
macOS, Linux and Windows and pulls only `cffi` and `pycparser`.

This reverses an earlier decision in this project. When `keyring` wanted the same
compiled stack on Linux, it was refused — the stack was a large cost to reach a
Secret Service a headless box does not run. Here the stack *is* the feature.

### No keychain, and the WiFi passphrase is never stored

`keyring` was added to hold the broker password, on the argument that a secret
needed by *every command* should not be retyped constantly or exported into the
environment. Deleting the broker password deleted that argument with it.

What remains is the WiFi passphrase, wanted once per robot while somebody is
standing in front of it. Storing it bought a dependency, platform variance,
headless edge cases, and a backup story that did not cover itself — the keychain
lives outside `~/whiskerless`, so "back up this directory" would have been a lie.

The CA private key is a different kind of secret and lives in a file on purpose:
it is archival, it must survive machine loss, and every tool in the world stores
CA keys as files because you need to carry and archive them. Match the storage to
the secret.

### One visible directory, one versioning marker

`~/whiskerless`, not `~/.whiskerless`. It holds a CA private key that must be
backed up, and "back up this folder" is useless advice if the folder is invisible
in a file manager. Matches the sibling dreame-valetudo project.

```
~/whiskerless/
├── .layout              structure version, separate from the release version
├── broker.json          the ONE broker every robot here talks to
├── ca/ca.crt  ca.key    the authority; the key never leaves this machine
├── client/              this machine's identity to the broker
├── broker/              server.crt + server.key — copy to your broker
└── robots/<serial>/profile.json
```

### One broker per store

The broker, its port and its CA used to live on every robot profile, and a whole
apparatus existed to reconcile them: a `SharedSetup` type computing what the
robots agreed on, `merge_overrides` laying flags over a profile, a per-robot copy
of the CA, and a prompt that had to *describe whose* CA it was offering. None of
those values ever actually differ — a household points its robots at one broker.

Hoisting them to the store deleted all of it, and deleted `whiskerless adopt`
with it: once the broker was no longer per-robot, adopt only recorded a serial,
and it could never give a robot the certificate it now needs. Re-provisioning is
the honest path.

A genuinely separate broker is a separate store: point `WHISKERLESS_HOME` at
another directory and it gets its own CA, its own robots, its own everything.
That is more honest than pretending one machine can straddle two brokers, because
under mutual TLS it cannot — the CA that signed one broker's certificate did not
sign the other's.

The same reasoning removed `--host`, `--port`, `--ca` and `--insecure` from the
everyday commands. Under mutual TLS a one-off `--host` would still present this
store's CA and this machine's client certificate, so it could only ever produce a
confusing TLS failure. `--host` and `--ca` survive on `setup`, which is where the
broker is established — and moving the broker there reissues its server
certificate, because a certificate whose SAN names the old address fails every
handshake the robot attempts and looks exactly like a broken robot.

`--port` and `--insecure` did not survive anywhere. Both existed only to let the
CLI differ from the robot, and the robot cannot differ: its port is a
compile-time constant with no provisioning field, and it verifies the broker
against the name it was given. Since the CLI connects to the host in the store,
and `setup` guarantees the certificate names that host, hostname verification
here can only ever pass — a flag to skip it could not rescue a broker the robots
were already failing against, it could only hide it.

`.layout` is the **only** version marker. An earlier design also stamped a format
version inside each `profile.json`; both were kept briefly and that was a mistake —
two numbers to remember to bump, and two that can disagree. A renamed field inside
`profile.json` is a structural change like any other, so one marker covers the
directory shape *and* the file shapes. A store written by a newer whiskerless is
refused by name rather than read optimistically.

`~/.whiskerless` migrates forward automatically, **renamed rather than copied** —
two directories that both look like the store is where somebody edits the wrong
one. If both exist the old one is left alone, because a silent merge around a
private key is not something to attempt.

`broker/` deliberately does **not** contain a copy of `ca.crt`, tempting as a
self-contained folder is. Two stored copies of one certificate raise the question
of which is authoritative and there is no good answer — and more importantly, a
folder you copy wholesale to a server must be safe to copy wholesale, which means
the CA's files cannot live in it.

### What is issued, and what is kept

| certificate | lifetime | stored? |
|---|---|---|
| the CA | generated once, reused forever | `ca/` — the one thing that must be backed up |
| broker server cert | regenerate freely | `broker/` — an artifact for the user |
| this machine's client cert | minted once, reused | `client/` — we use it on every command |
| a robot's client cert | minted per provision | **never** |

A robot's certificate is written to the robot and forgotten. Nothing needs a
second copy: the robot holds it, the broker verifies it against the CA, and a
replacement is one re-provision away. Keeping one would be another place for a
private key to leak from and no place it could be used.

This machine's certificate is the opposite case and is kept, because *we* are the
one using it. Minting per run would cost an RSA keygen on every command and fill
the broker's log with a different stranger each time.

**CN is the identity.** A robot's is its serial; this machine's is
`whiskerless-<hostname>`, so two machines are distinguishable in the broker log.
With `use_identity_as_username true` the CN becomes the MQTT username.

**RSA-2048, PKCS#1 (`BEGIN RSA PRIVATE KEY`), 100-byte write chunks.** Not
preferences — all three are exactly what the Whisker app writes, observed on the
wire. This project does not guess at what firmware will accept.

### No revocation, deliberately

Revocation needs a record of what was issued *and* the CA key to sign a CRL with.
The CA key already gates it, so the record is never the binding constraint — which
is why the issued certificate's serial number is recorded in `profile.json`
anyway. It is free, it never fails first, and it preserves the option for somebody
who did not plan for one.

The modern answer to revocation is short-lived certificates rather than CRLs, and
that option is **closed here**: the robot's certificate slots are writable only
over BLE, so every rotation is a walk to the robot. Long-lived is the only choice
available.

Weighed against that, extracting a robot's key requires physical possession of the
robot, and the blast radius is one robot's topics. A CRL was judged not worth the
operating burden. The per-issuance-unique-CN allowlist alternative was rejected
for worse reasons still: it needs a broker ACL edit at every provision.

### Bring your own

| you supply | `auth` | robot's identity | broker listener |
|---|---|---|---|
| nothing — we generate the CA | `mutual` | ours, issued per provision | either |
| `ca.crt` + `ca.key` | `mutual` | ours, issued per provision | either |
| `ca.crt` + a certificate per robot | `supplied` | yours, stored here | either |
| `ca.crt` alone | `anonymous` | the factory's, untouched | must allow anonymous |

The last two rows have to be asked for by name — `--auth supplied`, `--auth
anonymous` — and the reason is in the decision at the top of this file: not the
posture, but that the third one used to happen to people by accident while looking
identical to a working setup.

The listener column says "either" for the first three because that is a separate
choice: a robot holding a certificate still connects to a listener that allows
anonymous clients. Requiring them is recommended, not required — except in the
last row, where there is nothing for the listener to check.

**A CA certificate is always required.** There is no "skip" — the robot verifies
your broker against whatever is in its trust slot, so something has to go there.
An earlier version of the setup menu offered a third "skip" option and it was
incoherent: it fell straight through to asking for a CA path anyway. Whether the
robot gets an identity of its own is a *consequence* of handing over the signing
key, not a separate choice.

The confirmation screen fires **after** the network is chosen and before the
first write, not before the BLE link opens. The robot lists the networks it can
see, so the SSID is not known until then — asking earlier printed a blank WiFi
row and asked somebody to approve a thing they had not chosen yet.

Supplied files are **copied in under our own names**, never remembered by path. A
path breaks when the USB stick comes out or the folder is tidied, and it breaks
later, at a moment nobody connects back to the decision. A genuinely offline CA has no exit — the key is copied in and stays. Deleting
`ca/ca.key` afterwards leaves a store that cannot provision at all: since 0.2.0
every robot is issued a certificate, so a store that cannot sign is refused by
`_ensure_pki` before a robot is touched, and the only offers left are to supply
the key again or replace the authority (which strands every robot that trusted
the old one). Robots already provisioned keep working — a listener running
`require_certificate true` should stay that way — but the store is no longer one
you can add a robot with. A `--no-store-ca-key` flag was considered and not
built; after this decision it would only build the state above on purpose.

Validation before anything is written, because these failures are otherwise
invisible until a handshake fails: refuse a certificate that is not a CA (the "I
gave you my server cert" mistake), a mismatched pair, or an expired one; warn
about a CA with no `keyUsage` extension, which the robot's mbedTLS accepts and
Python 3.13's `VERIFY_X509_STRICT` then rejects — the worst possible split.

### Setup is a separate command from provisioning

`whiskerless setup` establishes the broker and the certificates; `whiskerless
provision` puts a robot on them. Doing both in one command looked tidier and was
wrong: between generating certificates and a robot being able to use them,
somebody has to copy three files to a broker and restart it — minutes, on
anything more involved than a local Mosquitto. A robot sits in pairing mode with
a limited window, so the single command would have spent that window on paperwork
and then failed in a way that looks exactly like a broken robot.

### Nothing about the machine is committed until a robot accepts it

`broker.json` is written only after provisioning succeeds. An abort, a failed
WiFi join, or a robot that never advertised would otherwise silently retarget
*every other command* at a broker no robot is on. The CA and this machine's
identity are written earlier and deliberately — they are idempotent, reusable,
and a second run should not regenerate them.

An established CA is never replaced. Swapping it would leave every provisioned
robot trusting a certificate the broker no longer presents, and each rescue is a
walk to that robot with a laptop; the refusal names the robots that would be
stranded. Rotating deliberately means starting a fresh store.

### Backup is a command, not an instruction

"Back up `~/whiskerless`" was the whole plan for a while, and it is the kind of
advice people follow exactly as often as it is convenient. `whiskerless backup`
writes one file; `whiskerless restore` puts it back.

**Encryption is offered, never assumed, and never silent.** The archive contains
the signing key, and a backup's whole purpose is to be somewhere else — a USB
stick, a NAS, cloud storage. So an interactive run is asked for a passphrase and
enter means none; an unattended run must say `--no-password` or set
`WHISKERLESS_BACKUP_PASSWORD`, because a cron job that writes a signing key in
the clear should have had to choose that. Encrypted is AES-256-GCM with an
scrypt-derived key, and the header line is the AEAD's associated data, so the
parameters it states are the parameters that were used.

Unencrypted, it is an ordinary `.tar.gz` — deliberately. This file is opened
once, years later, on a bad day, possibly on a machine that does not have
whiskerless on it. `tar` will still be there. The encrypted container is
documented byte for byte in `backup.py`'s module docstring for the same reason:
a backup that can only be read by the program that wrote it is a bet on that
program still existing.

Everything is archived under a single `whiskerless/` directory so unpacking by
hand cannot scatter `ca/`, `robots/` and a bare `.layout` across whatever
directory somebody was standing in.

**Restore refuses to replace a setup, and says what replacing it would cost.**
The question is always which CA is on each side: the same one makes it a dull
overwrite, a different one silently strands every robot that trusts the one
being displaced — so the refusal names those robots, and each of them is a walk
with a laptop. `--force` proceeds, and *moves* the old store aside rather than
deleting it, because what is being displaced may be the only copy of a key
robots in that house still trust.

Member names out of the archive are validated rather than sanitised: absolute
paths, `..`, backslashes and non-regular members are refused outright. Tar path
traversal is ancient and still works, and a name that needs cleaning was not
written by whiskerless — quietly repairing it would hide that. Permissions come
from the restoring end, never from the archive, because one of those files signs
certificates and the archive has been through cloud storage.

### No ACL shipped

`pattern readwrite prod/LR4/%u/#` would confine each robot to its own topics with
one line and no per-robot maintenance. It was skipped as not worth the setup step:
the only clients holding certificates from this CA are ones the user issued, so
the ACL guards against a compromised robot reaching a second robot's topics.
Cheap to add later; `use_identity_as_username true` is still recommended so the
broker log names the robot rather than "anonymous".
