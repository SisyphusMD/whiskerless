#!/usr/bin/env bash
# Integration: drive forgejo-release.sh + github-release.sh + update-tap.sh
# end-to-end against a STUBBED curl (no network, no forge). Published release bytes are immutable, so
# these assertions cover what each publisher REFUSES as much as what it uploads: identical bytes are
# a no-op, differing or ambiguous bytes abort the run, an unverified release state blocks the upload,
# and no publisher ever issues a DELETE. The rc-pruning sweep is the one script that DOES delete —
# whole superseded rc releases, only once the stable is verified present on all three registries — and
# is covered with its own STATEFUL stub whose DELETEs actually mutate what the next GET returns, so
# removal is proven by re-reading the live list and git refs (and the release-before-tag order and the
# git-refs delete endpoint the real forges require), never by trusting the HTTP code. Run directly:
# bash tests/release/release-scripts.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; root="$(cd "$here/../.." && pwd)"

# This project's names, read the same way the scripts under test read them, so the fixtures below are
# this repo's rather than a hardcoded sibling's. NAME is the repo and package name; DIST is the
# distribution filename form, which PEP 625 spells with underscores; INITIAL is the letter PyPI files
# its source under.
# shellcheck source=/dev/null
. "$root/packaging/project.env"

# The give-up path is asserted below, and the real 300s CDN grace period would be paid on every
# run of this suite in both projects, in ci.yml and in both release gates.
export TAP_DOWNLOAD_WINDOW=2
SLUG="$PROJECT_REPO_SLUG"
NAME="${SLUG##*/}"
DIST="${NAME//-/_}"
INITIAL="${NAME:0:1}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
calls="$tmp/curl.log"              # reset per scenario
history="$tmp/curl-history.log"    # never reset: the global no-DELETE assertion reads this
state="$tmp/remote-present"
remote="$tmp/remote-asset"
lookups="$tmp/release-lookups"
: > "$history"

fail() { echo "FAIL: $1"; exit 1; }

# Stateful forge stub. STUB_MODE selects what the release already holds: absent, identical,
# different, duplicate, race-same, race-different, unpersisted-state, create, or create-race.
cat > "$tmp/curl" <<'STUB'
#!/usr/bin/env bash
set -u
printf 'curl %s\n' "$*" >> "$STUB_CALLS"
printf 'curl %s\n' "$*" >> "$STUB_HISTORY"
out=""; upload=""; previous=""
for argument in "$@"; do
  [ "$previous" = -o ] && out="$argument"
  [ "$previous" = --data-binary ] && upload="${argument#@}"
  case "$argument" in attachment=@*) upload="${argument#attachment=@}" ;; esac
  previous="$argument"
done
# Metadata reads are file-backed too now, so -o alone no longer identifies an asset download —
# only the download URL does. Everything else with -o still wants the JSON body below, just written
# to the file instead of stdout.
if [ -n "$out" ]; then
  case "$*" in
    *download.example*) cp "$STUB_REMOTE" "$out"; exit 0 ;;
    *) exec > "$out" ;;
  esac
fi
if [ -n "$upload" ]; then
  case "$STUB_MODE" in
    # A forge that rejects the upload after storing it, and one that stored somebody else's bytes.
    race-same) cp "$upload" "$STUB_REMOTE"; : > "$STUB_STATE"; exit 22 ;;
    race-different) printf 'racing different bytes\n' > "$STUB_REMOTE"; : > "$STUB_STATE"; exit 22 ;;
    *) cp "$upload" "$STUB_REMOTE"; : > "$STUB_STATE"; exit 0 ;;
  esac
fi
case "$*" in
  *"/releases/999/assets"*)
    if [ "$STUB_MODE" = duplicate ]; then
      printf '[{"name":"%s","id":1,"browser_download_url":"https://download.example/first"},' \
        "$STUB_ASSET"
      printf '{"name":"%s","id":2,"browser_download_url":"https://download.example/second"}]\n' \
        "$STUB_ASSET"
    elif [ -e "$STUB_STATE" ]; then
      printf '[{"name":"%s","id":1,"browser_download_url":"https://download.example/first"}]\n' \
        "$STUB_ASSET"
    else
      printf '[]\n'
    fi ;;
  *"/releases/999"*)
    if [ "$STUB_MODE" = unpersisted-state ]; then
      printf '{"id":999,"draft":true,"prerelease":true}\n'
    else
      printf '{"id":999,"draft":false,"prerelease":%s}\n' "$STUB_PRERELEASE"
    fi ;;
  *"/releases/tags/"*)
    case "$STUB_MODE" in
      create) printf '{}\n' ;;
      create-race)
        if [ -e "$STUB_LOOKUPS" ]; then
          printf '{"id":999,"draft":false,"prerelease":%s}\n' "$STUB_PRERELEASE"
        else
          : > "$STUB_LOOKUPS"; printf '{}\n'
        fi ;;
      *) printf '{"id":999,"draft":false,"prerelease":%s}\n' "$STUB_PRERELEASE" ;;
    esac ;;
  *"/git/ref/tags/"*|*"/tags/"*) printf '{}\n' ;;
  *"/releases"*)
    [ "$STUB_MODE" != create-race ] || exit 22
    printf '{"id":999,"draft":false,"prerelease":%s}\n' "$STUB_PRERELEASE" ;;
esac
STUB
chmod +x "$tmp/curl"
export PATH="$tmp:$PATH"
export STUB_CALLS="$calls" STUB_HISTORY="$history" STUB_STATE="$state" STUB_REMOTE="$remote"
export STUB_LOOKUPS="$lookups" STUB_ASSET="${NAME}_amd64.deb"
export STUB_MODE=absent STUB_PRERELEASE=false

notes="$tmp/notes.md"; printf 'release notes\n' > "$notes"
asset="$tmp/${NAME}_amd64.deb"; printf 'intended asset bytes\n' > "$asset"

publisher() {
  local forge=$1 mode=$2 expected=$3 tag=${4:-v9.9.9} output status
  rm -f "$state" "$remote" "$lookups"
  : > "$calls"
  export STUB_MODE="$mode"
  case "$tag" in *-*) export STUB_PRERELEASE=true ;; *) export STUB_PRERELEASE=false ;; esac
  case "$mode" in
    identical|duplicate) cp "$asset" "$remote"; : > "$state" ;;
    different) printf 'different existing bytes\n' > "$remote"; : > "$state" ;;
  esac
  set +e
  if [ "$forge" = forgejo ]; then
    output=$(bash "$root/packaging/forgejo-release.sh" forge.example tok "$tag" "$notes" "$asset" 2>&1)
  else
    output=$(bash "$root/packaging/github-release.sh" tok "$tag" "$notes" "$asset" 2>&1)
  fi
  status=$?
  set -e
  if [ "$expected" = success ]; then
    [ "$status" -eq 0 ] || fail "$forge $mode failed: $output"
    cmp -s "$asset" "$remote" || fail "$forge $mode did not leave the intended bytes published"
  else
    if [ "$status" -eq 0 ]; then fail "$forge $mode unexpectedly succeeded: $output"; fi
  fi
}

for forge in forgejo github; do
  publisher "$forge" absent success
  grep -Eq 'attachment=@|data-binary @' "$calls" || fail "$forge did not upload an absent asset"

  publisher "$forge" identical success
  ! grep -Eq 'attachment=@|data-binary @' "$calls" || fail "$forge re-uploaded identical bytes"

  publisher "$forge" different failure
  ! grep -Eq 'attachment=@|data-binary @' "$calls" \
    || fail "$forge tried to replace an asset whose published bytes differ"

  publisher "$forge" duplicate failure
  ! grep -Eq 'attachment=@|data-binary @' "$calls" \
    || fail "$forge uploaded against a name that resolves to two assets"

  publisher "$forge" race-same success
  publisher "$forge" race-different failure

  publisher "$forge" unpersisted-state failure
  ! grep -Eq 'attachment=@|data-binary @' "$calls" \
    || fail "$forge uploaded before the repaired release state read back"

  publisher "$forge" create-race success
  [ "$(grep -c '/releases/tags/' "$calls")" -eq 2 ] \
    || fail "$forge did not recover when another publisher won release creation"
  grep -Eq 'releases/999/assets\?name='"$NAME"'_amd64\.deb' "$calls" \
    || fail "$forge did not upload through the concurrently created release"

  publisher "$forge" create success
  grep -Eq '"prerelease": false' "$calls" \
    || fail "$forge: a stable tag must create a non-prerelease (prerelease:false)"
  grep -Eq '"draft": false' "$calls" \
    || fail "$forge: a created release must be explicitly visible (draft:false)"

  publisher "$forge" create success v9.9.9-rc.1
  grep -Eq '"prerelease": true' "$calls" \
    || fail "$forge: a hyphenated (rc) tag must create a prerelease (prerelease:true)"
done
echo "  immutable publishers: absent uploads, identical no-ops, conflict/duplicate/unverified-state"
echo "                        rejects, upload races, and create recovery OK (both forges)"

# ---- forge-specific endpoints: a wrong URL silently no-ops or 422s against the real API ----
publisher forgejo create success
grep -Eq 'forge\.example/api/v1/repos/'"$SLUG"'/tags/v9\.9\.9' "$calls" \
  || fail "forgejo: no tag-wait call to the plain /tags endpoint"
grep -Eq "$NAME"'/releases([[:space:]]|$)' "$calls" \
  || fail "forgejo: no release-create call to /releases"
grep -Eq 'releases/999/assets\?name='"$NAME"'_amd64\.deb.*-F attachment=@' "$calls" \
  || fail "forgejo: no multipart (-F attachment=@) upload to /releases/999/assets"

publisher github create success
grep -Eq 'api\.github\.com/repos/'"$SLUG"'/git/ref/tags/v9\.9\.9' "$calls" \
  || fail "github: no exact tag-wait call to the singular git/ref/tags endpoint"
! grep -Eq 'api\.github\.com/repos/'"$SLUG"'/git/refs/tags/' "$calls" \
  || fail "github: prefix-matching git/refs endpoint can accept an rc tag in place of stable"
grep -Eq 'POST .*api\.github\.com/repos/'"$SLUG"'/releases([[:space:]]|$)' "$calls" \
  || fail "github: no release-create POST to /releases"
grep -Eq 'data-binary @.*uploads\.github\.com/repos/'"$SLUG"'/releases/999/assets\?name='"$NAME"'_amd64\.deb' "$calls" \
  || fail "github: no data-binary upload to uploads.github.com"
echo "  forge endpoints: tag-wait, create, and the two upload shapes hit the right URLs OK"

# ---- tag grammar: only the two shapes the release workflows cut may address a release API ----
export STUB_MODE=absent STUB_PRERELEASE=false
for forge in forgejo github; do
  : > "$calls"
  if [ "$forge" = forgejo ]; then
    command=(bash "$root/packaging/forgejo-release.sh" forge.example tok v9.9.9-preview "$notes" "$asset")
  else
    command=(bash "$root/packaging/github-release.sh" tok v9.9.9-preview "$notes" "$asset")
  fi
  if "${command[@]}" >/dev/null 2>&1; then
    fail "$forge accepted a tag outside the stable/rc grammar"
  fi
  [ ! -s "$calls" ] || fail "$forge let an invalid tag reach the release API"
done
echo "  tag grammar: a tag outside stable/rc is refused before any API call OK"

tap_runnable=true
python3 -c 'import build' 2>/dev/null || tap_runnable=false
if [ "$tap_runnable" != true ]; then
  echo '  Homebrew formula: SKIPPED — no build frontend, so the sdist cannot be built offline'
else
# ---- Homebrew formula: the checksum comes from a LOCAL rebuild, and both remotes must match it --
# The formula is generated from a throwaway copy of this tree so the rc case can restamp the
# version, and so the rebuild that update-tap.sh performs is compared against an independent build
# of the same source (which also proves the tarball is byte-reproducible).
source_tree="$tmp/source-tree"
mkdir -p "$source_tree"
# Only what both projects are guaranteed to have is required. `libexec/` and `uv.lock` exist in one
# and deliberately not the other, and copying them unconditionally aborts the fixture under set -e for
# the project that has neither, taking the whole tap section down with it.
cp -R "$root/src" "$root/packaging" "$root/docs" "$source_tree/"
cp "$root/pyproject.toml" "$root/README.md" "$root/LICENSE" "$root/CHANGELOG.md" "$source_tree/"
if [ -d "$root/libexec" ]; then cp -R "$root/libexec" "$source_tree/"; fi
if [ -f "$root/uv.lock" ]; then cp "$root/uv.lock" "$source_tree/"; fi
# A git repo, because update-tap.sh builds the sdist from `git archive` of the tag rather than the
# working tree — hatchling would otherwise sweep untracked neighbours into it and change the hash.
git -C "$source_tree" init -q
git -C "$source_tree" add -A
git -C "$source_tree" -c user.email=t@t -c user.name=t commit -qm fixture
# update-tap.sh builds an sdist, which needs a build frontend AND fetches the backend into an
# isolated environment — both of which mean network. This file's contract is that it runs offline
# with curl stubbed, so the tap section is SKIPPED rather than being made to reach out. CI installs
# `build` (see the tap jobs in publish.yml), so it runs there.

stamp_version() {
  python3 - "$source_tree/pyproject.toml" "$1" <<'PY'
import re
import sys

path, version = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
text, count = re.subn(r'^version = "[^"]+"', f'version = "{version}"', text, count=1, flags=re.M)
if count != 1:
    raise SystemExit("could not stamp the fixture version")
open(path, "w", encoding="utf-8").write(text)
PY
}

# An independent build of the same tree is what PyPI is required to be serving. Built the same way
# update-tap.sh builds its copy, so a mismatch means the artifact differs rather than the method.
build_expected() {
  git -C "$source_tree" add -A
  git -C "$source_tree" -c user.email=t@t -c user.name=t commit -qm "stamp $1" --allow-empty
  rm -rf "$tmp/expected-build"
  python3 -m build --sdist --outdir "$tmp/expected-build" "$source_tree" >/dev/null
  # PEP 625: the sdist filename normalises `-` to `_`, and the version to PEP 440.
  pypi_v="$(printf '%s' "$1" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
  mv "$tmp/expected-build/${DIST}-$pypi_v.tar.gz" "$tmp/expected.tar.gz"
}

cat > "$tmp/curl" <<'STUB'
#!/usr/bin/env bash
set -u
printf 'curl %s\n' "$*" >> "$STUB_CALLS"
printf 'curl %s\n' "$*" >> "$STUB_HISTORY"
out=""; url=""; previous=""
for argument in "$@"; do
  [ "$previous" = -o ] && out="$argument"
  case "$argument" in http*://*) url="$argument" ;; esac
  previous="$argument"
done
[ -n "$out" ] || exit 2
# One source now: the formula builds from the PyPI sdist, so that is the only download to serve.
source=$TAP_PYPI
[ -n "$source" ] || exit 22
cp "$source" "$out"
STUB
chmod +x "$tmp/curl"

# A fixed stable fixture version, stamped like the rc case below: the ambient checkout's version
# may be rc-shaped (the release gate qualifies the STAMPED tree), which would route update-tap.sh
# to the rc formula while the stable assertions below read the stable one.
version="9.7.0"
stamp_version "$version"
tap="$tmp/tap"
build_expected "$version"
export TAP_PYPI="$tmp/expected.tar.gz"

: > "$calls"
bash "$source_tree/packaging/update-tap.sh" "v$version" "$tap" >/dev/null \
  || fail "update-tap.sh exited nonzero when both remotes served the locally built tarball"
stable="$tap/Formula/${NAME}.rb"
digest="$(shasum -a 256 "$tmp/expected.tar.gz" | awk '{print $1}')"
grep -Fq "sha256 \"$digest\"" "$stable" \
  || fail "formula checksum does not match an independent build of the same source"
pypi_v="$(printf '%s' "$version" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
grep -Fq "files.pythonhosted.org/packages/source/$INITIAL/$NAME/${DIST}-$pypi_v.tar.gz" \
  "$stable" || fail "stable formula does not build from the PyPI sdist"
# The release-asset url and its GitHub mirror are what the sdist replaced. A formula carrying both
# would be served two different archives against one checksum.
! grep -q 'releases/download/' "$stable" \
  || fail "stable formula still points at a release asset"
! grep -q '^  mirror ' "$stable" \
  || fail "stable formula still carries a mirror line"
# ANY marker, matched as a pattern rather than a hand-kept list — the list going stale is the bug
# render-formula.sh exists to make impossible, and a named-marker check here would go stale the same
# way. A bare `REPLACE_BOTTLE_BLOCK` parses as a Ruby constant, so Homebrew fails at install time.
! grep -q 'REPLACE_' "$stable" \
  || fail "stable formula retained an unsubstituted placeholder"
# One copy to check now, and it is the one the formula names: the checksum must come from a local
# build and be CONFIRMED against what PyPI actually serves, never taken from the download.
grep -Fq "files.pythonhosted.org/packages/source/$INITIAL/$NAME/${DIST}-$pypi_v.tar.gz" \
  "$calls" || fail "update-tap did not verify the PyPI sdist the formula points at"

# A stable tag also RE-POINTS the rc formula at the same stable tarball (fall-through), so the rc
# brew channel keeps resolving after this version's superseded rc releases are pruned.
rc_fallthrough="$tap/Formula/${NAME}-rc.rb"
[ -f "$stable" ] && [ -f "$rc_fallthrough" ] \
  || fail "a stable tag must write BOTH the stable and the rc fall-through formula"
for formula in "$stable" "$rc_fallthrough"; do
  grep -Fq "sha256 \"$digest\"" "$formula" \
    || fail "$formula checksum does not match the stable build"
  grep -Fq "url \"https://files.pythonhosted.org/packages/source/$INITIAL/$NAME/${DIST}-$pypi_v.tar.gz\"" "$formula" \
    || fail "$formula does not point its url at the stable PyPI sdist"
  # Any marker, not a list of them. Naming the ones one project happens to use lets the other's
  # spellings through, which is the same trap the checksum marker above avoids, and render-formula.sh
  # already treats a leftover `REPLACE_` of any name as fatal.
  ! grep -q 'REPLACE_' "$formula" \
    || fail "$formula retained an unsubstituted placeholder"
done
echo "  Homebrew formula: checksum from the local rebuild, PyPI confirmed to serve it OK"
echo "  Homebrew formula: a stable tag writes both formulas, rc falling through to the stable OK"

# A registry that cannot serve the tag, or serves other bytes, must not yield a formula at all.
: > "$calls"
TAP_PYPI="" bash "$source_tree/packaging/update-tap.sh" "v$version" "$tmp/unavailable-tap" \
  >/dev/null 2>&1 && fail "update-tap wrote a formula while the primary registry had no copy"
[ ! -e "$tmp/unavailable-tap/Formula" ] || fail "update-tap left a formula behind on failure"

printf 'a different published tarball\n' > "$tmp/other.tar.gz"
: > "$calls"
TAP_PYPI="$tmp/other.tar.gz" bash "$source_tree/packaging/update-tap.sh" "v$version" \
  "$tmp/mismatch-tap" >/dev/null 2>&1 \
  && fail "update-tap accepted a mirror serving bytes other than the locally built tarball"
echo "  Homebrew formula: a missing or dissenting published copy fails closed OK"

# The NEXT version's candidate, not this one's. The stable pass above re-pointed the rc formula at
# 9.7.0 (the documented fall-through), so a 9.7.0-rc.1 arriving afterwards really would move the rc
# channel backward — the guard below is asserted separately for exactly that.
next_rc="9.8.0-rc.1"
stamp_version "$next_rc"
build_expected "$next_rc"
export TAP_PYPI="$tmp/expected.tar.gz"
bash "$source_tree/packaging/update-tap.sh" "v$next_rc" "$tap" >/dev/null \
  || fail "update-tap.sh exited nonzero for a valid rc formula"
rc="$tap/Formula/${NAME}-rc.rb"
next_rc_pypi="$(printf '%s' "$next_rc" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
grep -Fq "${DIST}-$next_rc_pypi.tar.gz" "$rc" \
  || fail "rc formula does not name the PEP 440 sdist for this candidate"
grep -Fq "sha256 \"$(shasum -a 256 "$tmp/expected.tar.gz" | awk '{print $1}')\"" "$rc" \
  || fail "rc formula checksum does not match the rc source rebuild"

# A LATE pass for an older tag must not publish over the newer formula. `tap-bottles.yml`
# documents a manual rerun for a partial bottle set, so this arrives in practice — and the
# tap-write concurrency group serialises writers without saying anything about version order.
stamp_version "$version-rc.1"
build_expected "$version-rc.1"
export TAP_PYPI="$tmp/expected.tar.gz"
# SKIPPED, not failed. A late rerun for an older tag is a normal thing to happen — tap-bottles.yml
# documents a manual one — so it leaves the newer formula alone and exits clean rather than
# painting a release red for behaving correctly.
bash "$source_tree/packaging/update-tap.sh" "v$version-rc.1" "$tap" >/dev/null 2>&1 \
  || fail "update-tap.sh failed instead of skipping a stale pass"
grep -Fq "${DIST}-$next_rc_pypi.tar.gz" "$rc" \
  || fail "the refused pass modified the formula anyway"
echo "  Homebrew formula: a late pass for an older tag is refused, not published OK"
stamp_version "$version"

: > "$calls"
if bash "$source_tree/packaging/update-tap.sh" v9.9.9-preview "$tmp/invalid-tap" >/dev/null 2>&1; then
  fail "update-tap accepted a tag outside the stable/rc grammar"
fi
[ ! -s "$calls" ] || fail "update-tap let an invalid tag reach a release registry"

template="$source_tree/packaging/homebrew/${NAME}.rb"
cp "$template" "$tmp/template.rb"
# Read the marker out of the template rather than naming one project's spelling. render-formula.sh
# accepts REPLACE_SDIST_SHA256 and REPLACE_TARBALL_SHA256 on purpose, because the two projects
# describe their source archive differently, so hardcoding either makes this a no-op for the other
# and the assertion below then passes against a template that was never actually broken.
sha_marker="$(grep -o 'REPLACE_[A-Z]*_SHA256' "$tmp/template.rb" | head -1)"
[ -n "$sha_marker" ] || fail "the formula template carries no sdist checksum placeholder"
sed "s/$sha_marker/missing-checksum-placeholder/" "$tmp/template.rb" > "$template"
build_expected "$version"
export TAP_PYPI="$tmp/expected.tar.gz"
if bash "$source_tree/packaging/update-tap.sh" "v$version" "$tmp/broken-tap" >/dev/null 2>&1; then
  fail "update-tap accepted a formula template whose checksum placeholder was missing"
fi
cp "$tmp/template.rb" "$template"
echo "  Homebrew formula: rc channel, tag grammar, and fail-closed template OK"
fi

# The whole point of the rewrite: no immutable-asset publisher may remove published bytes, ever.
# The rc sweep is the one script that DOES delete, and it is covered on its own in
# tests/release/prune-rcs.sh, against its own stubbed registries.
! grep -q -- '-X DELETE' "$history" || fail "a release script issued an asset DELETE"


echo "PASS: release publishers treat published assets as immutable, and the tap formula is built"
echo "      from a local rebuild both registries are proven to serve"
