#!/usr/bin/env bash
# Block until a release is genuinely installable, then return.
#   wait-for-release.sh <tag>        e.g. v0.2.0-rc.30
#
# One definition, called by BOTH install matrices — the Linux one on Forgejo and
# the macOS one on GitHub. They start from the same tag push and would otherwise
# each carry their own idea of "ready", which is the kind of drift that leaves one
# forge testing a half-published release and reporting success.
#
# "Installable" is two things, and the second is the one that bites:
#
#   1. The release carries every artifact. The .pkg and the bottles are built by
#      separate workflows and arrive minutes apart, so this waits for the slowest.
#
#   2. The TAP advertises the checksums the release is serving RIGHT NOW. Bottle
#      legs install from the tap, and the tap is written in two passes: the
#      formula lands as soon as PyPI has the sdist, the `bottle do` block only
#      once the bottles exist. A leg let through between them installs the right
#      version by BUILDING it from source. Worse, a bottle REBUILD replaces the
#      archives under an unchanged tag, so a tag-shaped check would pass instantly
#      while the tap still advertised the replaced bytes — the state that once
#      broke `brew install` for everyone.
set -euo pipefail

TAG="${1:?usage: $0 <tag>}"
case "$TAG" in
  v[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "::error::not a release tag: $TAG" >&2; exit 1 ;;
esac

FORGE="${FORGE:-https://forgejo.bryantserver.com}"
API="$FORGE/api/v1/repos/SisyphusMD/whiskerless/releases/tags/$TAG"
ATTEMPTS="${WAIT_ATTEMPTS:-120}"
INTERVAL="${WAIT_INTERVAL:-30}"

case "$TAG" in
  *-rc.*) FORMULA=whiskerless-rc ;;
  *)      FORMULA=whiskerless ;;
esac

# Bounded, always. The attempt count only bounds this if each request is bounded
# too — a connection that is accepted and then stalls would otherwise hang past
# it, to whatever the runner's own timeout is.
fetch() { curl -sfL --connect-timeout 10 --max-time 60 --retry 2 --retry-connrefused "$1"; }

tap_ready() {  # tap_ready <release-json>
  local rel="$1" rb want have
  rb=$(fetch "$FORGE/SisyphusMD/homebrew-tap/raw/branch/main/Formula/$FORMULA.rb") || return 1
  # Fixed-string and including the closing quote: unanchored, rc.2 is a prefix of
  # rc.28 and matches its root_url.
  printf '%s\n' "$rb" | grep -qF "releases/download/${TAG}\"" || return 1
  have=$(printf '%s\n' "$rb" | awk '/^ *bottle do$/,/^ *end$/' \
           | sed -n 's/.*"\([0-9a-f]\{64\}\)".*/\1/p' | LC_ALL=C sort -u)
  # The outer manifest key is tap-qualified; `formula.name` is the short name,
  # which is what tells a stable release's two sets of bottles apart.
  want=$(printf '%s\n' "$rel" \
           | jq -r '.assets[]? | select(.name | endswith(".bottle.json")) | .browser_download_url' \
           | while read -r u; do
               [ -n "$u" ] || continue
               fetch "$u" | jq -r --arg f "$FORMULA" \
                 '.[] | select(.formula.name == $f) | .bottle.tags[].sha256'
             done | LC_ALL=C sort -u)
  [ -n "$want" ] && [ "$want" = "$have" ]
}

for _ in $(seq 1 "$ATTEMPTS"); do
  rel=$(fetch "$API" || true)
  names=$(printf '%s' "$rel" | jq -r '.assets[]?.name' 2>/dev/null || true)
  have() { printf '%s\n' "$names" | grep -q "$1"; }
  # Either checksum layout. A dispatch deliberately runs the CURRENT scripts against an older
  # tag — that is the whole point of the tag input — and a release cut before the per-architecture
  # split carries one `SHA256SUMS` instead of two. Demanding the new pair would make such a
  # dispatch wait out its full deadline and then fail for a release that is perfectly complete.
  if have '\.deb$' && have '\.rpm$' && have 'linux-x86_64$' && have 'linux-arm64$' \
     && have 'macos-arm64\.pkg$' && have 'bottle\.tar\.gz$' \
     && { { have 'SHA256SUMS-x86_64' && have 'SHA256SUMS-aarch64'; } || have '^SHA256SUMS$'; }; then
    if tap_ready "$rel"; then
      echo "$TAG is complete and the tap advertises the bottles it is serving"
      exit 0
    fi
    echo "  release complete; waiting for the tap to match $TAG's current bottles"
  fi
  sleep "$INTERVAL"
done
echo "::error::$TAG never became installable — nothing to install-test" >&2
exit 1
