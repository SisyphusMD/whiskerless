#!/usr/bin/env bash
# Integration: content-quorum release reconciliation against a stateful stubbed curl (no network).
# The stub keeps each registry's assets as real files, so an upload is observable and a copy that
# reconcile must not touch can be checked byte-for-byte afterwards.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; root="$(cd "$here/../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
calls="$tmp/curl.log"; : > "$calls"
history="$tmp/curl-history.log"; : > "$history"
remotes="$tmp/remotes"

fail() { echo "FAIL: $1"; exit 1; }

# Release 990 is the stable tag v9.9.0; 991 is the prerelease v9.9.0-rc.1.
cat > "$tmp/curl" <<'STUB'
#!/usr/bin/env bash
set -u
printf 'curl %s\n' "$*" >> "$STUB_CALLS"
printf 'curl %s\n' "$*" >> "$STUB_HISTORY"
case "$*" in
  *forgejo.nas.bryantserver.com*) registry=nas ;;
  *github.com*) registry=github ;;
  *) registry=cluster ;;
esac
id=0
case "$*" in
  *v9.9.0-rc.1*) id=991 ;;
  *v9.9.0*) id=990 ;;
esac
case "$*" in
  *"/releases/991"*) id=991 ;;
  *"/releases/990"*) id=990 ;;
esac
prerelease=false
[ "$id" != 991 ] || prerelease=true
directory="$STUB_REMOTES/$registry/$id"

emit_assets() {
  local first=true file name
  printf '['
  for file in "$directory"/*; do
    [ -f "$file" ] || continue
    name=$(basename "$file")
    [ "$first" = true ] || printf ','
    first=false
    printf '{"name":"%s","id":1,"browser_download_url":"mock://%s"}' \
      "$name" "${file#"$STUB_REMOTES"/}"
    if [ "$name" = "${STUB_DUPLICATE_NAME:-}" ] && [ "$registry" = "${STUB_DUPLICATE_REGISTRY:-}" ]
    then
      printf ',{"name":"%s","id":2,"browser_download_url":"mock://%s"}' \
        "$name" "${file#"$STUB_REMOTES"/}"
    fi
  done
  printf ']\n'
}

out=""; upload=""; url=""; previous=""
for argument in "$@"; do
  [ "$previous" = -o ] && out="$argument"
  [ "$previous" = --data-binary ] && upload="${argument#@}"
  case "$argument" in
    attachment=@*) upload="${argument#attachment=@}" ;;
    mock://*) url="$argument" ;;
  esac
  previous="$argument"
done
if [ -n "$out" ]; then
  [ -n "$url" ] || exit 22
  cp "$STUB_REMOTES/${url#mock://}" "$out" 2>/dev/null || exit 22
  exit 0
fi
if [ -n "$upload" ]; then
  name=$(basename "$upload")
  # A forge refuses a second asset under an existing name; only a delete could free it.
  [ ! -e "$directory/$name" ] || exit 22
  cp "$upload" "$directory/$name"
  exit 0
fi
case "$*" in
  *"/releases/$id/assets"*) emit_assets ;;
  *"/releases/tags/"*)
    printf '{"id":%s,"draft":false,"prerelease":%s,"assets":' "$id" "$prerelease"
    emit_assets | tr -d '\n'
    printf '}\n' ;;
  *"/releases/$id"*) printf '{"id":%s,"draft":false,"prerelease":%s}\n' "$id" "$prerelease" ;;
  *"/git/ref/tags/"*|*"/tags/"*) printf '{}\n' ;;
  *"/releases"*) printf '{"id":%s,"draft":false,"prerelease":%s}\n' "$id" "$prerelease" ;;
esac
STUB
chmod +x "$tmp/curl"
export PATH="$tmp:$PATH" CLUSTER_TOKEN=ctok NAS_TOKEN=ntok GH_TOKEN=gtok
export STUB_CALLS="$calls" STUB_HISTORY="$history" STUB_REMOTES="$remotes"

for registry in cluster github nas; do
  mkdir -p "$remotes/$registry/990" "$remotes/$registry/991"
done
seed() { printf '%s' "$2" > "$remotes/$1"; }

# --- the stable release, v9.9.0 -------------------------------------------------------------
# amd64 .deb: GitHub holds different bytes under the same name — cluster + NAS are the quorum.
seed cluster/990/whiskerless_9.9.0_amd64.deb GOOD
seed github/990/whiskerless_9.9.0_amd64.deb EVIL
seed nas/990/whiskerless_9.9.0_amd64.deb GOOD
# arm64 .deb: one copy each, disagreeing. That is not a quorum, it is a question for a human.
seed cluster/990/whiskerless_9.9.0_arm64.deb LEFT
seed github/990/whiskerless_9.9.0_arm64.deb RGHT
# The standalone binaries carry no extension at all, which is the shape most likely to be missed
# by a role table written from memory.
seed cluster/990/whiskerless-9.9.0-linux-x86_64 BINARY
seed github/990/whiskerless-9.9.0-linux-x86_64 BINARY
# One checksum file per architecture, each written by the forge that built that half. They are two
# roles, not one `SHA256SUMS-*` glob, because a role matching two names is what reconcile calls
# ambiguous — and it skips the entire tag when it sees one.
seed cluster/990/SHA256SUMS-x86_64 SUMS
seed nas/990/SHA256SUMS-x86_64 SUMS
seed cluster/990/SHA256SUMS-aarch64 ARMSUMS
seed github/990/SHA256SUMS-aarch64 ARMSUMS
# Bottles: present on the real releases, deliberately outside the quorum model.
seed cluster/990/whiskerless-9.9.0.arm64_sequoia.bottle.tar.gz BOTTLE
seed cluster/990/whiskerless-9.9.0.arm64_sequoia.bottle.json MANIFEST
# Outside the release matrix entirely, whatever it is named.
seed cluster/990/whiskerless-evil.deb EVIL

# --- the prerelease, v9.9.1-rc.1: the two spellings of one asset -----------------------------
# Forgejo stores the native `~rc.1` verbatim; GitHub rewrites `~` to `.` in the STORED name.
# Compared literally these look like two assets sharing one role, which would make every
# prerelease tag ambiguous and silently unreconciled.
seed "cluster/991/whiskerless_9.9.0~rc.1_amd64.deb" RCDEB
seed "nas/991/whiskerless_9.9.0~rc.1_amd64.deb" RCDEB
seed "github/991/whiskerless_9.9.0.rc.1_amd64.deb" RCDEB

repo="$tmp/repo"; mkdir -p "$repo"; cd "$repo"
git init -q; git config user.email t@t; git config user.name t
git commit -q --allow-empty -m seed
git tag v9.9.0; git tag v9.9.0-rc.1; git tag v9.9.0-preview

if ! out="$(bash "$root/packaging/reconcile-releases.sh" 2>&1)"; then
  fail "reconcile exited nonzero: $out"
fi

# A registry missing an asset two others agree on is filled from that content quorum.
[ "$(cat "$remotes/nas/990/whiskerless-9.9.0-linux-x86_64" 2>/dev/null)" = BINARY ] \
  || fail "the missing standalone binary was not filled from the quorum"
[ "$(cat "$remotes/github/990/SHA256SUMS-x86_64" 2>/dev/null)" = SUMS ] \
  || fail "the missing SHA256SUMS-x86_64 was not filled from the quorum"
# The arm64 file is a separate role and must reconcile on its own terms; a glob collapsing the two
# would have made this tag ambiguous and skipped it, quietly, since reconcile is warn-only.
[ "$(cat "$remotes/nas/990/SHA256SUMS-aarch64" 2>/dev/null)" = ARMSUMS ] \
  || fail "the missing SHA256SUMS-aarch64 was not filled from the quorum"

# Published bytes are immutable: a dissenting copy is reported for an operator, never overwritten.
[ "$(cat "$remotes/github/990/whiskerless_9.9.0_amd64.deb")" = EVIL ] \
  || fail "a registry publishing different bytes was rewritten instead of reported"
grep -q 'already publishes other whiskerless_9.9.0_amd64.deb bytes' <<<"$out" \
  || fail "the dissenting copy was not reported for review"

# One copy each, disagreeing, is not a quorum — nothing may be invented from it.
grep -q 'no two registries agree on v9.9.0 asset whiskerless_9.9.0_arm64.deb' <<<"$out" \
  || fail "a single-copy disagreement was not reported as having no quorum"
[ ! -e "$remotes/nas/990/whiskerless_9.9.0_arm64.deb" ] \
  || fail "an asset with no quorum was invented onto a third registry"

# Bottles are ignored, not warned about. A warning per bottle per tag on every release would train
# the reader to skip the one warning that means something.
! grep -q 'ignoring unexpected v9.9.0 asset whiskerless-9.9.0.arm64_sequoia.bottle' <<<"$out" \
  || fail "a bottle was reported as an unexpected asset"
! grep -Eq 'assets\?name=[^ ]*\.bottle\.' "$calls" \
  || fail "a bottle was reconciled; they are deliberately outside the quorum model"

# A genuinely stray upload IS reported — which is what the ignore list must not swallow.
grep -q 'ignoring unexpected v9.9.0 asset whiskerless-evil.deb' <<<"$out" \
  || fail "a stray asset outside the release matrix was not reported"

# The two registry spellings of one rc asset are one asset: not ambiguous, not a gap.
! grep -q "could not resolve v9.9.0-rc.1's assets" <<<"$out" \
  || fail "the two spellings of one rc asset were read as an ambiguous role"
! grep -Eq 'releases/991/assets\?name=[^ ]*_amd64\.deb.*attachment=@' "$calls" \
  || fail "an rc asset every registry already serves was uploaded again"

# Only the two tag shapes a release workflow can cut are addressed at all.
grep -q 'ignoring tag outside the release grammar: v9.9.0-preview' <<<"$out" \
  || fail "a tag outside the release grammar was not skipped"

# Converged: a second pass repairs nothing and still refuses to touch the dissenting copy.
: > "$calls"
if ! out="$(bash "$root/packaging/reconcile-releases.sh" 2>&1)"; then
  fail "the second reconcile pass exited nonzero: $out"
fi
! grep -Eq 'attachment=@|data-binary @' "$calls" \
  || fail "a converged reconcile pass uploaded an asset"

echo "PASS: reconcile fills only missing copies from a two-registry SHA-256 quorum, reports rather"
echo "      than rewrites a dissenting registry, and leaves the non-reproducible bottles alone"
