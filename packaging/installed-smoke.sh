#!/usr/bin/env bash
# What "an installed whiskerless works" means — one definition, called by every
# install channel there is.
#   installed-smoke.sh <path-to-whiskerless> <expected-version>
#
# It exists because each channel used to invent its own check, so what got proven
# depended on which channel you were looking at, and the ones nobody wrote a
# check for (the .pkg, a poured bottle, PyPI) were proven by nothing at all. Any
# new channel now costs one line: install it, then call this.
#
# Everything here runs with NO robot and NO broker, because that is the only way
# it can run unattended on a release. It is deliberately more than `--help`: the
# certificate work is the largest thing in the project that a packaged build can
# exercise on its own, so it is exercised.
#
# Needs `openssl` for the certificate half; without it that half SKIPS loudly
# rather than passing quietly, since a smoke that silently checks less than it
# claims is worse than no smoke.
set -uo pipefail

[ "$#" -eq 2 ] || { echo "usage: $0 <path-to-whiskerless> <expected-version>" >&2; exit 2; }
CLI="$1"; WANT="$2"
command -v "$CLI" >/dev/null 2>&1 || [ -x "$CLI" ] || { echo "not executable: $CLI" >&2; exit 2; }

fails=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
skip() { printf '  SKIP  %s\n' "$1"; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# `diff` is NOT on every base image this runs on — rockylinux:9 ships no
# diffutils — and depending on it made this smoke report "restore did not
# reproduce the store" on an image where restore was perfectly fine. A test that
# fails for its own reasons and blames the product is worse than no test, so the
# comparison is done with a checksum manifest instead.
if command -v sha256sum >/dev/null 2>&1; then shacmd="sha256sum"; else shacmd="shasum -a 256"; fi
tree_manifest() {  # tree_manifest <dir> -> "<relative path> <sha256>" per file, sorted
  ( cd "$1" 2>/dev/null || return 1
    find . -type f | LC_ALL=C sort | while read -r f; do
      printf '%s %s\n' "$f" "$($shacmd "$f" | awk '{print $1}')"
    done )
}

echo "== whiskerless installed smoke: $CLI"

# --- 1. it is the build we think it is ------------------------------------------
# Both spellings pass: the tag says 0.2.0-rc.28, PEP 440 says 0.2.0rc28, and which
# one a channel reports depends on how it was packaged.
got="$("$CLI" --version 2>&1 | tr -d '\r')"
alt="$(printf '%s' "$WANT" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
case "$got" in
  *"$WANT"*|*"$alt"*) pass "reports $got" ;;
  *) fail "version is '$got', wanted $WANT (or $alt)" ;;
esac

# --- 2. every advertised subcommand can at least describe itself ------------------
# Parsed from the binary rather than hardcoded, so a subcommand added without a
# help page is caught here rather than by a user.
if "$CLI" --help >/dev/null 2>&1; then pass "--help"; else fail "--help"; fi
# `head -1`: argparse prints the choice list twice, in the usage line and again
# beside the positional, and counting both reports twice as many subcommands as
# exist — which would still "pass", just meaninglessly.
subs="$("$CLI" --help 2>&1 | tr ' ' '\n' | sed -n 's/^{\(.*\)}.*$/\1/p' | head -1 | tr ',' ' ')"
if [ -z "$subs" ]; then
  fail "could not read the subcommand list from --help"
else
  bad=""
  for s in $subs; do
    "$CLI" "$s" --help >/dev/null 2>&1 || bad="$bad $s"
  done
  if [ -z "$bad" ]; then
    pass "$(printf '%s' "$subs" | wc -w | tr -d ' ') subcommands have help"
  else
    fail "no help for:$bad"
  fi
fi

# --- 3. the guard survived packaging ---------------------------------------------
# The one thing that must never break, whatever the channel did to the code. It
# prints its verdict before opening any connection, so a host with no broker
# still exercises it; the exit status is the broker's, not the guard's.
# Captured before matching, deliberately. `send` exits non-zero when it cannot
# reach a broker — which is always, here — and piping it into grep would let
# pipefail report a matched pattern as a failure. The guard prints its verdict
# before any connection is attempted, which is the whole reason this is testable
# without a broker.
guard="$("$CLI" send 0x02A30000 2>&1 || true)"
case "$guard" in
  *[Nn]ever*) pass "refuses a NEVER_SEND opcode" ;;
  *) fail "0x02A30000 was NOT refused — the safety guard did not survive packaging: $guard" ;;
esac

# --- 4. it refuses to set up without a way to trust anything ---------------------
# The refusal is the feature: a robot pointed at a broker it cannot verify is the
# failure this project exists to avoid, and it has to say what to do about it.
# The STATUS matters as much as the text: a regression that prints a warning
# mentioning --ca and then carries on would satisfy a text-only check while
# having set nothing up.
out="$(WHISKERLESS_HOME="$work/refuse" "$CLI" setup --host 192.0.2.1 </dev/null 2>&1)"; rc=$?
case "$out" in
  *"--ca"*)
    if [ "$rc" -ne 0 ]; then
      pass "setup refuses without a CA, names the flag, and exits non-zero"
    else
      fail "setup named --ca but exited 0 — that is a warning, not a refusal"
    fi
    ;;
  *) fail "setup did not refuse cleanly without a CA: $out" ;;
esac

# --- 5. the certificate path, which is most of what a packaged build can prove ----
if ! command -v openssl >/dev/null 2>&1; then
  skip "certificate checks (no openssl on this image)"
else
  ca="$work/ca"; mkdir -p "$ca"
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$ca/ca.key" -out "$ca/ca.crt" \
    -days 2 -subj "/CN=whiskerless installed smoke" >/dev/null 2>&1 \
    || { fail "could not make a throwaway CA"; }
  store="$work/store"
  if WHISKERLESS_HOME="$store" "$CLI" setup --host 192.0.2.1 \
       --ca "$ca/ca.crt" --ca-key "$ca/ca.key" </dev/null >/dev/null 2>&1; then
    pass "setup --ca --ca-key completes"
  else
    fail "setup --ca --ca-key failed"
  fi
  miss=""
  for f in ca/ca.crt ca/ca.key broker/server.crt broker/server.key client/client.crt client/client.key; do
    [ -f "$store/$f" ] || miss="$miss $f"
  done
  if [ -z "$miss" ]; then
    pass "the store holds every file a broker and this machine need"
  else
    fail "setup did not create:$miss"
  fi
  # The point of #72: a supplied CA *and* key means whiskerless can issue, and an
  # issued certificate that does not chain is worse than none — it fails every
  # handshake while looking right on disk.
  for leaf in broker/server.crt client/client.crt; do
    if [ -f "$store/$leaf" ] && openssl verify -CAfile "$ca/ca.crt" "$store/$leaf" >/dev/null 2>&1; then
      pass "$leaf chains to the supplied CA"
    else
      fail "$leaf does not verify against the CA that supposedly issued it"
    fi
  done
  # A store with no robots must say so rather than print nothing or crash.
  empty="$(WHISKERLESS_HOME="$store" "$CLI" robots </dev/null 2>&1 || true)"
  case "$empty" in
    *"no robots"*) pass "robots reports an empty store" ;;
    *) fail "robots did not report an empty store: $empty" ;;
  esac
  # backup/restore is the only protection for a CA key that cannot be regenerated,
  # so "it produced a file" is not the check — the restored store has to match.
  arc="$work/backup.tar.gz"
  if WHISKERLESS_HOME="$store" "$CLI" backup --no-password "$arc" </dev/null >/dev/null 2>&1 \
     && [ -s "$arc" ]; then
    pass "backup writes an archive"
    restored="$work/restored"
    if WHISKERLESS_HOME="$restored" "$CLI" restore "$arc" </dev/null >/dev/null 2>&1; then
      if [ "$(tree_manifest "$store")" = "$(tree_manifest "$restored")" ]; then
        pass "restore reproduces the store exactly"
      else
        fail "restore produced a different store"
        printf '%s\n' "--- original ---"; tree_manifest "$store"
        printf '%s\n' "--- restored ---"; tree_manifest "$restored"
      fi
    else
      fail "restore did not run"
    fi
  else
    fail "backup did not write an archive"
  fi
fi

echo
if [ "$fails" -eq 0 ]; then
  echo "installed smoke PASS: $got"
else
  echo "installed smoke FAILED: $fails check(s)" >&2
fi
[ "$fails" -eq 0 ] || exit 1
exit 0
