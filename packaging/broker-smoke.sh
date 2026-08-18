#!/usr/bin/env bash
# Run an installed whiskerless against a REAL broker, over TLS, with certificates
# it issued itself — and no robot.
#   broker-smoke.sh <path-to-whiskerless> [state-document.json]
#
# `installed-smoke.sh` proves a build was packaged intact. This proves it can
# still talk: the certificate whiskerless issues is actually accepted by a broker
# configured the way the docs tell people to configure one, the topics it
# subscribes to are the topics a robot publishes on, and a recorded state
# document decodes into the values a user reads.
#
# Everything a robot would do is played by mosquitto's own clients, so the whole
# thing runs unattended. The broker is configured `require_certificate true`,
# which is the strict setting the setup guide builds toward — so this also
# answers "would the identity whiskerless issues be accepted", which is the one
# question the hardware test exists to settle and the one CI could never reach.
#
# mosquitto runs as a LOCAL PROCESS, not in a container. It used to be a
# `docker run -p`, which quietly required a runner that is not itself
# containerised: a job inside a container cannot reach a port published on the
# docker host, and our own Forgejo runners are exactly that. Running the broker
# beside the client needs no daemon, no socket and no networking, so this now
# works anywhere the binaries exist — including inside a buildx stage, which is
# how the arm64 leg gets tested at all.
#
# Needs mosquitto, mosquitto_pub and openssl.
set -uo pipefail

CLI="${1:?usage: $0 <path-to-whiskerless> [state-document.json]}"
here="$(cd "$(dirname "$0")" && pwd)"
DOC="${2:-$here/../tests/integration/fixtures/lr4_state.json}"
[ -f "$DOC" ] || { echo "no state document at $DOC" >&2; exit 2; }
for tool in mosquitto mosquitto_pub openssl; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 2; }
done

SERIAL="LR4C000000"
# 8883, because that is the only port there is. The robot's port is a
# compile-time constant in its firmware and the CLI has no flag to move off it,
# so a smoke on some convenient high port would be testing a configuration
# nothing can actually be in.
PORT=8883

fails=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }

work="$(mktemp -d)"
broker_pid=""
# shellcheck disable=SC2329  # invoked by the EXIT trap below, not by name
cleanup() {
  [ -z "$broker_pid" ] || kill "$broker_pid" 2>/dev/null
  rm -rf "$work"
}
trap cleanup EXIT

echo "== whiskerless broker smoke: $CLI"

# --- the certificates come from whiskerless, which is the point -------------------
ca="$work/ca"; mkdir -p "$ca"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$ca/ca.key" -out "$ca/ca.crt" \
  -days 2 -subj "/CN=whiskerless broker smoke CA" >/dev/null 2>&1
store="$work/store"
# 127.0.0.1 rather than a name: the certificate has to carry whatever the client
# will verify, and this is the address the CLI is about to connect to.
if WHISKERLESS_HOME="$store" "$CLI" setup --host 127.0.0.1 \
     --ca "$ca/ca.crt" --ca-key "$ca/ca.key" </dev/null >/dev/null 2>&1; then
  pass "whiskerless issued the broker's certificate and this machine's identity"
else
  fail "setup failed — nothing else here can run"
  exit 1
fi

# --- a broker configured the way the setup guide tells people to ------------------
conf="$work/mosquitto.conf"
cat > "$conf" <<EOF
listener $PORT
cafile $store/ca/ca.crt
certfile $store/broker/server.crt
keyfile $store/broker/server.key
# The strict setting the docs build toward: the robot (and the CLI) must present
# a certificate this CA signed. Anything less would not answer the question.
require_certificate true
use_identity_as_username true
allow_anonymous false
EOF
# mosquitto refuses to read a key it considers world-accessible, and the store is
# deliberately 0600/0700 — so it runs as whoever owns the store rather than
# dropping privileges to the `mosquitto` user it would pick by default.
echo "user $(id -un)" >> "$conf"
mosquitto -c "$conf" > "$work/mosquitto.log" 2>&1 &
broker_pid=$!

ready=""
for _ in $(seq 1 30); do
  if ! kill -0 "$broker_pid" 2>/dev/null; then break; fi
  # No `nc` on a minimal image; bash opens the socket itself.
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then ready=1; break; fi
  sleep 1
done
if [ -n "$ready" ]; then
  pass "broker is listening on $PORT with require_certificate"
else
  fail "broker never came up"; tail -10 "$work/mosquitto.log"; exit 1
fi

# mosquitto's own client plays the robot. The payload goes in on STDIN (`-s`)
# rather than as a path, which keeps the publish identical to the one the
# containerised version made.
pub() {  # pub <topic> <file> [extra args]
  mosquitto_pub -h 127.0.0.1 -p "$PORT" \
    --cafile "$store/ca/ca.crt" --cert "$store/client/client.crt" --key "$store/client/client.key" \
    -t "$1" -s "${@:3}" < "$2" 2>&1
}

# --- the strict setting is actually strict ----------------------------------------
# Without this the whole file proves only that a valid certificate works, which a
# certificate-optional listener also allows. The claim being made is that the
# broker REFUSES anything else, so that is tested directly.
if mosquitto_pub -h 127.0.0.1 -p "$PORT" --cafile "$store/ca/ca.crt" \
     -t "prod/LR4/$SERIAL/state" -m '{}' >/dev/null 2>&1; then
  fail "the broker accepted a client with NO certificate — require_certificate is not in force"
else
  pass "a client with no certificate is refused"
fi

# --- the certificate whiskerless issued is one the broker accepts ------------------
# Publishing at all requires the TLS handshake and the client certificate to be
# accepted. If the identity were unusable this fails here, which is exactly the
# failure the hardware test is meant to catch.
if pub "prod/LR4/$SERIAL/state" "$DOC" -r >/dev/null; then
  pass "a whiskerless-issued identity is accepted by a require_certificate broker"
else
  fail "the broker rejected the certificate whiskerless issued"
  pub "prod/LR4/$SERIAL/state" "$DOC" -r 2>&1 | head -3
  tail -6 "$work/mosquitto.log"
fi

# --- the CLI reads it back and decodes it -----------------------------------------
# The document is retained, so `state` gets it on subscribe; no robot has to be
# simulated for the read path.
out="$(WHISKERLESS_HOME="$store" "$CLI" state --serial "$SERIAL" </dev/null 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && [ -n "$out" ] && ! printf '%s' "$out" | grep -qiE "error|timed out|refused"; then
  pass "state connected over TLS and returned a document"
else
  fail "state did not read the retained document (exit $rc)"
  printf '%s\n' "$out" | head -6 | sed 's/^/      /' 
fi
# Decoding, not merely receiving: these are values a user reads off the screen,
# and a wire change that silently stopped decoding would still "return a document".
# VALUES, not labels. Each of these is the decoded form of a field in the
# recorded document — robotStatus 4 becomes "ready", litterLevelPercentage 62,
# DFILevelPercent 35, litterLevel 455 — so a decode that regressed to defaults,
# or silently stopped mapping a field, fails here. Matching on a heading would
# pass while printing nothing but headings.
for want in "robot_status = ready" "litter_level = 62" "waste_drawer_level = 35" "litter_level_mm = 455"; do
  if printf '%s\n' "$out" | grep -qE "^[[:space:]]*${want}\$"; then
    pass "decoded $want"
  else
    fail "state did not decode '$want' from the recorded document"
  fi
done

echo
if [ "$fails" -eq 0 ]; then
  echo "broker smoke PASS"
else
  echo "broker smoke FAILED: $fails check(s)" >&2
fi
[ "$fails" -eq 0 ] || exit 1
exit 0
