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
#
#   3. The apt/dnf REGISTRY serves this version. The matrix installs from those
#      repositories, and registry publishing is a separate job that waits for BOTH
#      architectures to land — arm64 is built on the other forge now — so it can
#      finish after the bottles. It used to be a step of the release job, which
#      ordered it ahead of everything here by accident rather than by design.
#      Without this, a healthy release gets a red apt-repo leg for having been
#      asked too early.
set -euo pipefail

TAG="${1:?usage: $0 <tag>}"
case "$TAG" in
  v[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "::error::not a release tag: $TAG" >&2; exit 1 ;;
esac

FORGE="${FORGE:-https://forgejo.bryantserver.com}"
API="$FORGE/api/v1/repos/SisyphusMD/whiskerless/releases/tags/$TAG"
# 300 x 30s = 150 minutes, and the number comes from the chain this waits on rather than from
# taste. The bottles cannot start until publish.yml has proven the formula installs and pushed the
# first tap pass, which builds from source; build-bottles.sh will itself wait up to 90 minutes for
# that, and the bottle build then takes about half an hour before the second pass lands them on the
# release. A budget under the sum of those does not test a slow release, it fails one.
ATTEMPTS="${WAIT_ATTEMPTS:-300}"
INTERVAL="${WAIT_INTERVAL:-30}"

case "$TAG" in
  *-rc.*) FORMULA=whiskerless-rc ;;
  *)      FORMULA=whiskerless ;;
esac

# Bounded, always. The attempt count only bounds this if each request is bounded
# too — a connection that is accepted and then stalls would otherwise hang past
# it, to whatever the runner's own timeout is.
fetch() { curl -sfL --connect-timeout 10 --max-time 60 --retry 2 --retry-connrefused "$1"; }

# The registry versions publish-registry.sh writes: debian keeps the native `~rc.`
# form, and rpm carries nfpm's release suffix. Derived the same way there, so the
# two move together if that suffix ever changes.
PKGVER="${TAG#v}"; PKGVER="${PKGVER/-rc./~rc.}"
PKGAPI="$FORGE/api/v1/packages/SisyphusMD"

# Scope: this answers "has the registry been written yet", not "is the release good". A
# distribution whose upload FAILED already fails publish-registry.sh, which exits non-zero and
# reddens its job — a red apt-repo leg there is a correct report, not the premature one this
# guards against.
registry_ready() {
  local kind ver a b
  for kind in debian rpm; do
    # BOTH architectures, by filename. A non-empty list is not enough: the two are
    # uploaded one after the other, so a poll landing between them would release
    # the arm64 legs against a repository that only has amd64 — and that fails
    # deterministically on a retry after a partial publish, not just rarely.
    case "$kind" in
      debian) ver="$PKGVER";    a="_amd64.deb";  b="_arm64.deb" ;;
      rpm)    ver="$PKGVER-1";  a=".x86_64.rpm"; b=".aarch64.rpm" ;;
    esac
    # `fetch` carries curl's -f, and that is load-bearing rather than tidiness.
    # Without it a 404 still writes its JSON error object to stdout and jq would
    # be reading that object instead of a file list. Verified against this
    # registry, as were the two version spellings above.
    fetch "$PKGAPI/$kind/whiskerless/$ver/files" 2>/dev/null \
      | jq -e --arg a "$a" --arg b "$b" \
          '[.[].name] | any(endswith($a)) and any(endswith($b))' >/dev/null 2>&1 || return 1
  done
}

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
  # Named, not just counted. A silent poll that ends in "never became installable" says nothing
  # about WHICH artifact never arrived, and that is the one fact needed to tell a slow bottle from
  # a broken .pkg.
  missing=""
  for pattern in '\.deb$' '\.rpm$' 'linux-x86_64$' 'linux-arm64$' 'macos-arm64\.pkg$' 'bottle\.tar\.gz$'; do
    have "$pattern" || missing="$missing $pattern"
  done
  { { have 'SHA256SUMS-x86_64' && have 'SHA256SUMS-aarch64'; } || have '^SHA256SUMS$'; } \
    || missing="$missing SHA256SUMS"
  if [ -z "$missing" ]; then
    if tap_ready "$rel" && registry_ready; then
      echo "$TAG is complete, the tap advertises the bottles it is serving, and apt/dnf have it"
      exit 0
    fi
    echo "  release complete; waiting for the tap and the apt/dnf registry to catch up to $TAG"
  else
    echo "  waiting: $TAG does not carry$missing yet"
  fi
  sleep "$INTERVAL"
done
echo "::error::$TAG never became installable — nothing to install-test" >&2
exit 1
