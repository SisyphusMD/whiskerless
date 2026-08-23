#!/usr/bin/env bash
# packaging/prune-rcs.sh against a stubbed set of registries, with no network.
#
# This is the only irreversible operation on the release path, and every interesting branch in it is
# a state nobody can reproduce on demand: a half-fanned-out stable, a draft left by an interrupted
# publisher, a registry that cannot be read, a delete that reports 204 and does not take. Stubbing
# the registries is the only way to reach them before they happen during a release.
#
# The stub is a small MUTABLE fake registry rather than a canned response table: a DELETE actually
# changes what the next GET returns, so the script's delete-then-RE-READ verification is exercised
# instead of mocked away. In particular it reproduces the behaviours a naive 204-returning stub hides:
#
#   * DELETE /releases/<id>       removes the release; the git tag survives.
#   * DELETE /git/refs/tags/<t>   removes the ref — but if the release still lists, that release is
#                                 STRANDED as an untagged draft which keeps listing, so by-id
#                                 verification still fails. This is what enforces release-first.
#   * DELETE /tags/<name>         Forgejo's tag DB row. Removes nothing else.
#   * the two package endpoints   delete differently on purpose, so a caller using the wrong one
#                                 shows up as a version still being served rather than as a pass.
#
# Optional knobs: STUBBORN (every delete is a 204 that lied), FLAKY_TAG (a tag-ref delete that only
# takes on a retry), STICKY_RELEASE (a release delete that persistently 500s), UNREADABLE (a registry
# whose reads fail), UNREADABLE_INDEX (only the apt/dnf index fails, so enumeration succeeds and the
# replacement check cannot be answered), UNREADABLE_STABLE_INDEX (only the stable's index read
# fails, the candidate's succeeds), UNREADABLE_INDEX_DIST=<dist> (only that distribution's index
# fails, so a candidate can hold one definite keep reason and one unanswered question at once).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STATE="$TMP/state"

# The package name the script derives from PROJECT_REPO_SLUG. Read the same way here so the
# fixtures below are this project's, not a hardcoded sibling's.
# shellcheck source=/dev/null
. "$ROOT/packaging/project.env"
FAKE_PKG="${PROJECT_REPO_SLUG##*/}"
# Deliberately not named PKG: the script assigns to that, and bash keeps an already-exported
# variable exported, so the script would overwrite what the stub reads.
export FAKE_PKG

cat > "$TMP/curl" <<'SH'
#!/usr/bin/env bash
# A fake registry. Understands the flag shapes the script actually uses: -o FILE, -w FORMAT, -f
# (fail on error status), -X DELETE. Anything else is skipped.
set -uo pipefail
method=GET; out=""; wfmt=""; failf=0; url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -o) out="$2"; shift 2 ;;
    -w) wfmt="$2"; shift 2 ;;
    -H) shift 2 ;;
    --max-time|--retry|--retry-max-time) shift 2 ;;
    --retry-connrefused) shift ;;
    -*) case "$1" in *f*) failf=1 ;; esac; shift ;;
    *) url="$1"; shift ;;
  esac
done

case "$url" in
  *api.github.com*)   reg=github ;;
  *forgejo.nas.*)     reg=nas ;;
  *)                  reg=cluster ;;
esac

# Anchored on the separator: GitHub's own ?per_page= ends in "page=" too, and matching that would
# read the page SIZE as the page NUMBER and serve an empty list to every GitHub read.
page=1
case "$url" in
  *[?\&]page=*) page="${url##*[?&]page=}"; page="${page%%&*}" ;;
esac

REL="$STATE/releases-$reg.json"
REFS="$STATE/tagrefs-$reg"
PKGS="$STATE/packages"      # lines: <type> <version> <arch> <dist>

emit() { # emit <status> <body>
  local code="$1" body="$2"
  [ -n "$out" ] && printf '%s' "$body" > "$out"
  if [ "$failf" = 1 ] && [ "$code" != 200 ] && [ "$code" != 204 ]; then
    [ -n "$wfmt" ] && printf "${wfmt//\%\{http_code\}/$code}"
    exit 22
  fi
  if [ -n "$wfmt" ]; then
    [ -z "$out" ] && printf '%s' "$body"
    printf "${wfmt//\%\{http_code\}/$code}"
  elif [ -z "$out" ]; then
    printf '%s' "$body"
  fi
  exit 0
}

if [ "$method" = DELETE ]; then
  printf '%s\n' "$url" >> "$STATE/delete-order"
  # STUBBORN: every delete reports success and does not take, so the verifying re-read still finds
  # the object. That is the case a status-code-trusting implementation calls done.
  [ "${STUBBORN:-0}" = 1 ] && emit 204 ""
  case "$url" in
    */git/refs/tags/*)
      tag="${url##*/git/refs/tags/}"
      # A 204 that lied on the FIRST attempt per registry: eventual consistency.
      if [ -n "${FLAKY_TAG:-}" ] && [ "$tag" = "$FLAKY_TAG" ]; then
        n=$(( $(cat "$STATE/flaky-$reg" 2>/dev/null || echo 0) + 1 ))
        echo "$n" > "$STATE/flaky-$reg"
        [ "$n" -lt 2 ] && emit 204 ""
      fi
      # Release still attached: removing the ref STRANDS it as an untagged draft that keeps listing.
      if [ -f "$REL" ] && jq -e --arg t "$tag" 'any(.[]?; (.tag_name? // "") == $t)' "$REL" >/dev/null 2>&1; then
        jq --arg t "$tag" 'map(if (.tag_name? // "") == $t then .tag_name = "" else . end)' \
          "$REL" > "$REL.tmp" && mv "$REL.tmp" "$REL"
      fi
      [ -f "$REFS" ] && { grep -vxF "$tag" "$REFS" > "$REFS.tmp" || true; mv "$REFS.tmp" "$REFS"; }
      emit 204 "" ;;
    */api/v1/packages/*/debian/*)
      ver="${url##*/}"
      [ -f "$PKGS" ] && { grep -v "^debian $ver " "$PKGS" > "$PKGS.tmp" || true; mv "$PKGS.tmp" "$PKGS"; }
      emit 204 "" ;;
    */api/packages/*/rpm/*/package/*)
      arch="${url##*/}"; rest="${url%/*}"; ver="${rest##*/}"
      [ -f "$PKGS" ] && { grep -v "^rpm $ver $arch " "$PKGS" > "$PKGS.tmp" || true; mv "$PKGS.tmp" "$PKGS"; }
      emit 204 "" ;;
    */releases/*)
      id="${url##*/releases/}"
      # A release delete that persistently fails: a 500 whose object survives. The sweep must then
      # NOT delete the tag, which would strand the still-listed release as a draft.
      [ "$id" = "${STICKY_RELEASE:-}" ] && emit 500 '{"message":"nope"}'
      [ -f "$REL" ] && { jq --arg id "$id" 'map(select(((.id? // "") | tostring) != $id))' "$REL" \
        > "$REL.tmp" && mv "$REL.tmp" "$REL"; }
      emit 204 "" ;;
    */tags/*)
      tag="${url##*/}"
      printf 'dbrow %s %s\n' "$reg" "$tag" >> "$STATE/dbrows"
      emit 204 "" ;;
  esac
  emit 204 ""
fi

# An unreadable registry, to prove the sweep fails closed rather than sweeping a partial picture.
if [ -n "${UNREADABLE:-}" ] && [ "$reg" = "$UNREADABLE" ]; then
  emit 500 '{"message":"boom"}'
fi

# An index that answers neither yes nor no. Distinct from UNREADABLE above, which takes out a whole
# registry: here every enumeration succeeds and only the apt/dnf lookup fails, which is the case that
# leaves the sweep unable to say whether a stable replaces the candidate it is about to delete.
case "$url" in
  *api/packages/*/debian/dists/*|*api/packages/*/rpm/*/repodata/*)
    [ -n "${UNREADABLE_INDEX:-}" ] && emit 503 '{"message":"index unavailable"}'
    # Both lookups for a pair go to the SAME url — it carries the distribution and architecture but
    # not the version — so failing by url alone cannot separate them. Counting reads PER url can: the
    # first read of an index is always the candidate's and any later one is the stable's, because the
    # stable is only asked about once the candidate answered. A global ordinal would not work, since
    # a candidate that is simply absent from a distribution ends that pair with no stable read at all
    # and slides every later count by one.
    # One distribution's index only, so a candidate can have a DEFINITE keep reason from another.
    if [ -n "${UNREADABLE_INDEX_DIST:-}" ]; then
      case "$url" in
        */dists/"$UNREADABLE_INDEX_DIST"/*|*/rpm/"$UNREADABLE_INDEX_DIST"/*)
          emit 503 '{"message":"index unavailable"}' ;;
      esac
    fi
    if [ -n "${UNREADABLE_STABLE_INDEX:-}" ]; then
      key=$(printf '%s' "$url" | tr -c 'a-zA-Z0-9' '_')
      hits=$(cat "$STATE/idx-$key" 2>/dev/null || echo 0)
      hits=$((hits + 1)); printf '%s' "$hits" > "$STATE/idx-$key"
      [ "$hits" -gt 1 ] && emit 503 '{"message":"index unavailable"}'
    fi ;;
esac

case "$url" in
  # ---- the apt/dnf package registry (cluster only) ----
  *api/v1/packages/*/files)
    # .../packages/<owner>/<type>/<name>/<version>/files
    rest="${url%/files}"; ver="${rest##*/}"; rest="${rest%/*}"; rest="${rest%/*}"; type="${rest##*/}"
    body=$(while read -r t v a _d; do
             [ "$t" = "$type" ] && [ "$v" = "$ver" ] || continue
             case "$t" in
               debian) printf '%s_%s_%s.deb\n' "$FAKE_PKG" "$v" "$a" ;;
               rpm)    printf '%s-%s.%s.rpm\n' "$FAKE_PKG" "$v" "$a" ;;
             esac
           done < "$PKGS" 2>/dev/null | sort -u | jq -R . | jq -s 'map({name: .})')
    emit 200 "${body:-[]}" ;;
  *api/v1/packages/*)
    [ "$page" -gt 1 ] && emit 200 '[]'
    # Includes a SIBLING project's package at the same versions: the delete is by version, and this
    # owner holds every project's packages, so a name filter that is not applied deletes theirs too.
    body=$(cut -d' ' -f1,2 "$PKGS" 2>/dev/null | sort -u \
      | jq -R --arg n "$FAKE_PKG" 'split(" ") | {name: $n, type: .[0], version: .[1]}' \
      | jq -s --arg n "$FAKE_PKG" '. + [{name: ("other-" + $n), type: "debian", version: "9.9.9"}]')
    emit 200 "${body:-[]}" ;;
  # The published debian index, which is arch-scoped by URL.
  *api/packages/*/debian/dists/*)
    rest="${url%/Packages}"; arch="${rest##*binary-}"
    rest="${rest%%/main/*}"; dist="${rest##*/}"
    body=$(while read -r t v a d; do
             [ "$t" = debian ] && [ "$a" = "$arch" ] && [ "$d" = "$dist" ] || continue
             printf 'Package: %s\nVersion: %s\n\n' "$FAKE_PKG" "$v"
           done < "$PKGS" 2>/dev/null)
    [ -n "$body" ] || emit 404 ""
    emit 200 "$body" ;;
  # The published rpm index: gzipped, and NOT arch-scoped by URL, so arch lives inside the entry.
  *api/packages/*/rpm/*/repodata/primary.xml.gz)
    rest="${url%/repodata/*}"; dist="${rest##*/}"
    xml=$(while read -r t v a d; do
            [ "$t" = rpm ] && [ "$d" = "$dist" ] || continue
            printf '<package><name>%s</name><arch>%s</arch><version ver="%s"/></package>' \
              "$FAKE_PKG" "$a" "${v%-*}"
          done < "$PKGS" 2>/dev/null)
    [ -n "$xml" ] || emit 404 ""
    if [ -n "$out" ]; then
      printf '%s' "$xml" | gzip -c > "$out"
      [ -n "$wfmt" ] && printf "${wfmt//\%\{http_code\}/200}"
      exit 0
    fi
    emit 200 "$xml" ;;
  *api/packages/*) emit 404 "" ;;

  # ---- releases and tags ----
  */releases\?*)
    [ "$page" -gt 1 ] && emit 200 '[]'
    emit 200 "$(cat "$REL")" ;;
  # The git TAG list, which is what finds an orphan tag whose release is already gone.
  */tags\?*)
    [ "$page" -gt 1 ] && emit 200 '[]'
    emit 200 "$(jq -R . < "$REFS" | jq -s 'map({name: .})')" ;;
  */git/refs/tags/*)
    tag="${url##*/}"
    grep -qxF "$tag" "$REFS" 2>/dev/null || emit 404 '{"message":"Not Found"}'
    emit 200 "$(jq -n --arg r "refs/tags/$tag" '{ref:$r}')" ;;
  # GET-by-tag, used only for the stable stem, and only meaningful while its ref exists.
  */releases/tags/*)
    stem="${url##*/}"
    # A per-stem file wins when present, so a fixture can publish more than one stable; the generic
    # file stays the single-stable default every other case here relies on.
    f="$STATE/stable-$reg-$stem.json"
    [ -f "$f" ] || f="$STATE/stable-$reg.json"
    [ -f "$f" ] || emit 404 '{"message":"Not Found"}'
    body="$(jq --arg s "$stem" 'if .tag_name == $s then . else empty end' < "$f")"
    [ -n "$body" ] || emit 404 '{"message":"Not Found"}'
    emit 200 "$body" ;;
esac
emit 404 '{"message":"Not Found"}'
SH
chmod +x "$TMP/curl"

# A world with one prunable rc (v1.0.0-rc.1, superseded by a fully published v1.0.0) and one rc whose
# stable has NOT shipped (v2.0.0-rc.1). The second must survive every scenario below.
reset() {
  rm -rf "$STATE"; mkdir -p "$STATE"
  : > "$STATE/delete-order"; : > "$STATE/dbrows"; : > "$STATE/packages"
  local reg
  for reg in cluster nas github; do
    cat > "$STATE/releases-$reg.json" <<JSON
[{"tag_name":"v1.0.0-rc.1","id":"11$reg"},
 {"tag_name":"v2.0.0-rc.1","id":"22$reg"},
 {"tag_name":"v1.0.0","id":"90$reg"}]
JSON
    printf 'v1.0.0-rc.1\nv2.0.0-rc.1\nv1.0.0\n' > "$STATE/tagrefs-$reg"
    cat > "$STATE/stable-$reg.json" <<JSON
{"tag_name":"v1.0.0","id":90,"draft":false,"prerelease":false,
 "assets":[{"name":"${FAKE_PKG}_1.0.0_amd64.deb"},{"name":"${FAKE_PKG}-1.0.0.x86_64.rpm"}]}
JSON
  done
}

run() { # run [VAR=val ...]
  env PATH="$TMP:$PATH" STATE="$STATE" FAKE_PKG="$FAKE_PKG" PRUNE_RETRY_SLEEP=0 \
    CLUSTER_TOKEN=t NAS_TOKEN=t GH_TOKEN=t PACKAGE_TOKEN=t \
    "$@" bash "$ROOT/packaging/prune-rcs.sh" 2>&1 || true
}

deletes() { wc -l < "$STATE/delete-order" | tr -d ' '; }
fail() { echo "FAIL: $*" >&2; exit 1; }
# The rc whose stable never shipped is the control in every case: it must never be touched.
survivor() {
  grep -q 'v2.0.0-rc.1' "$STATE/delete-order" && fail "deleted an rc whose stable has not shipped"
  return 0
}

# --- the dry-run default -----------------------------------------------------------------------
# Fail closed. A sweep that deletes because nobody said not to is the one bug whose blast radius is
# every release candidate on every registry.
reset
out="$(run)"
[ "$(deletes)" = 0 ] || fail "the default run issued $(deletes) DELETE(s); it must be a dry run"
case "$out" in *"dry-run"*) ;; *) fail "the default run did not announce itself as a dry run: $out" ;; esac
case "$out" in *"v2.0.0-rc.1"*) fail "the dry run offered to prune a stable-less rc" ;; esac

# Only an exact "false" authorizes deletion: an API dispatch that passes its input through
# unevaluated, or a human typing True, must not delete.
# shellcheck disable=SC2016 # the UNexpanded expression is the case: a dispatch that never
# evaluated its input reaches the script as this literal, and it must not authorize a delete.
for value in True TRUE 1 yes "" '${{ inputs.dry_run }}'; do
  reset
  run DRY_RUN="$value" >/dev/null
  [ "$(deletes)" = 0 ] || fail "DRY_RUN=$value issued $(deletes) DELETE(s); only \"false\" may delete"
done

# --- a real sweep ------------------------------------------------------------------------------
reset
out="$(run DRY_RUN=false)"
[ "$(deletes)" -gt 0 ] || fail "DRY_RUN=false issued no DELETE at all"
case "$out" in *"v1.0.0-rc.1"*) ;; *) fail "the prunable rc was not reported: $out" ;; esac
survivor
# The stable stem is not an rc and must never be touched, on any registry.
grep -Eq '/releases/90(cluster|nas|github)$' "$STATE/delete-order" && fail "deleted the STABLE release"
grep -Eq 'git/refs/tags/v1\.0\.0$' "$STATE/delete-order" && fail "deleted the STABLE tag"

# Release before tag, per registry. A tag removed first strands the release as an untagged draft that
# keeps listing under an empty tag_name, which the rc-shaped enumeration can never rediscover.
for reg in api.github.com forgejo.nas forgejo.bryantserver; do
  rel="$(grep -n "$reg" "$STATE/delete-order" | grep -E '/releases/11[a-z]+$' | head -1 | cut -d: -f1 || true)"
  ref="$(grep -n "$reg" "$STATE/delete-order" | grep -E '/git/refs/tags/v1\.0\.0-rc\.1$' | head -1 | cut -d: -f1 || true)"
  [ -n "$rel" ] && [ -n "$ref" ] || fail "$reg: expected both a release and a tag-ref DELETE"
  [ "$rel" -lt "$ref" ] || fail "$reg deleted the tag ref before the release"
done

# Forgejo's stale tag DB row is cleared on both instances; GitHub has no such row.
_db='/api/v1/repos/[^/]+/[^/]+/tags/v1\.0\.0-rc\.1$'
grep -Eq "forgejo\.bryantserver\.com$_db" "$STATE/delete-order" \
  || fail "the cluster Forgejo tag DB row was never cleared"
grep -Eq "forgejo\.nas\.bryantserver\.com$_db" "$STATE/delete-order" \
  || fail "the NAS Forgejo tag DB row was never cleared"
grep -Eq 'api\.github\.com/repos/[^/]+/[^/]+/tags/v1\.0\.0-rc\.1$' "$STATE/delete-order" \
  && fail "issued the Forgejo-only tag DB delete against GitHub"

# Idempotent: nothing left to find, so a re-run deletes nothing and still succeeds.
run DRY_RUN=false >/dev/null
[ "$(grep -Ec '/releases/11[a-z]+$' "$STATE/delete-order")" -le 3 ] \
  || fail "a re-run re-issued deletes for an rc that was already gone"

# --- a delete that reports success and does not take -------------------------------------------
# The whole reason removal is confirmed by re-reading rather than by trusting a 204.
reset
out="$(run DRY_RUN=false STUBBORN=1)"
case "$out" in *residue*) ;; *) fail "a delete that never took was reported as a clean prune: $out" ;; esac

# Eventual consistency: a tag-ref delete that only takes on the retry must still end verified gone.
reset
out="$(run DRY_RUN=false FLAKY_TAG=v1.0.0-rc.1)"
case "$out" in *residue*) fail "a retryable tag delete was reported as residue: $out" ;; esac
[ "$(grep -Ec 'forgejo\.bryantserver\.com.*/git/refs/tags/v1\.0\.0-rc\.1$' "$STATE/delete-order")" -ge 2 ] \
  || fail "a flaky tag-ref delete was never retried"

# A release delete that persistently fails must NOT be followed by its tag delete: that would strand
# the still-listed release as an untagged draft nothing ever enumerates again.
reset
out="$(run DRY_RUN=false STICKY_RELEASE=11cluster)"
case "$out" in *residue*) ;; *) fail "a persistently failing release delete was reported clean: $out" ;; esac
grep -Eq 'forgejo\.bryantserver\.com.*/git/refs/tags/v1\.0\.0-rc\.1$' "$STATE/delete-order" \
  && fail "deleted the tag ref while its release delete kept failing (strands an untagged draft)"

# --- the stable-is-fully-published gate --------------------------------------------------------
reset; rm "$STATE/stable-nas.json"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned while the stable was missing from a registry"

reset; jq '.draft = true' "$STATE/stable-github.json" > "$TMP/j" && mv "$TMP/j" "$STATE/stable-github.json"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned against a DRAFT stable, which nobody can install"

reset; jq '.prerelease = true' "$STATE/stable-cluster.json" > "$TMP/j" && mv "$TMP/j" "$STATE/stable-cluster.json"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned against a stable still marked prerelease"

reset; jq '.assets = [{"name":"a.deb"}]' "$STATE/stable-nas.json" > "$TMP/j" && mv "$TMP/j" "$STATE/stable-nas.json"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned while the registries served different asset sets (partial fan-out)"

reset; jq '.assets = []' "$STATE/stable-cluster.json" > "$TMP/j" && mv "$TMP/j" "$STATE/stable-cluster.json"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned against a stable serving no assets at all"

# A duplicated asset name is the ambiguous copy reconcile refuses to treat as usable: its download
# URL is undefined, so it is not evidence the stable is installable.
reset
jq '.assets += [.assets[0]]' "$STATE/stable-github.json" > "$TMP/j" && mv "$TMP/j" "$STATE/stable-github.json"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned against a stable serving a duplicated asset name"

# Bottles reach GitHub and the cluster and never the NAS, by design. Comparing raw sets would make
# every bottled stable look permanently half-fanned-out and keep its candidates forever.
reset
for reg in cluster github; do
  jq --arg n "$FAKE_PKG-1.0.0.arm64_sequoia.bottle.tar.gz" '.assets += [{"name":$n}]' \
    "$STATE/stable-$reg.json" > "$TMP/j" && mv "$TMP/j" "$STATE/stable-$reg.json"
done
run DRY_RUN=false >/dev/null
[ "$(deletes)" -gt 0 ] || fail "a bottle present on two registries blocked the prune; bottles are outside the quorum"

# --- an unreadable registry --------------------------------------------------------------------
# Not a verdict about anything. Deleting on a partial picture is how the last copy of an asset goes.
for reg in cluster nas github; do
  reset
  out="$(run DRY_RUN=false UNREADABLE="$reg")"
  [ "$(deletes)" = 0 ] || fail "pruned while $reg could not be read"
  case "$out" in
    *"not fully published"*) fail "reported an unreadable $reg as 'not published', which it is not" ;;
  esac
done

# --- STRICT: one stop, reported two ways --------------------------------------------------------
# STRICT changes the exit status and nothing else. The automatic caller leaves it off so a janitorial
# failure cannot redden a release that already published on all three registries; the manual dispatch
# turns it on so whoever pressed Run learns the sweep did not finish. Every case below therefore
# checks the deletion count too: a reporting knob that changed behaviour would be the worst outcome.
status() { # status [VAR=val ...] -> the script's exit code, which run() deliberately discards
  local rc=0
  env PATH="$TMP:$PATH" STATE="$STATE" FAKE_PKG="$FAKE_PKG" PRUNE_RETRY_SLEEP=0 \
    CLUSTER_TOKEN=t NAS_TOKEN=t GH_TOKEN=t PACKAGE_TOKEN=t \
    "$@" bash "$ROOT/packaging/prune-rcs.sh" >/dev/null 2>&1 || rc=$?
  echo "$rc"
}

reset
[ "$(status DRY_RUN=false UNREADABLE=cluster)" = 0 ] \
  || fail "an unreadable registry reddened the default sweep, which publish.yml runs after a release"

reset
[ "$(status DRY_RUN=false UNREADABLE=cluster STRICT=true)" = 1 ] \
  || fail "STRICT did not surface an unreadable registry"
[ "$(deletes)" = 0 ] || fail "STRICT changed what was deleted; it may only change reporting"

# Fail SAFE, the mirror image of DRY_RUN's fail-closed parse: anything but an exact "true" stays
# quiet, so a caller passing the input through unevaluated cannot start reddening published releases.
# shellcheck disable=SC2016  # the unexpanded literal IS the case: a forge input passed through
for spelling in 1 yes TRUE True '${{ inputs.strict }}'; do
  reset
  [ "$(status DRY_RUN=false UNREADABLE=cluster STRICT="$spelling")" = 0 ] \
    || fail "STRICT=$spelling was treated as strict"
done

# A sweep that finished is a success in both modes.
reset
[ "$(status DRY_RUN=false STRICT=true)" = 0 ] || fail "STRICT reddened a sweep that completed"
survivor

# Residue is the one outcome where the sweep RAN and still left work behind, and it follows the same
# rule: quiet for the release path, loud for the operator who asked.
reset
[ "$(status DRY_RUN=false STUBBORN=1)" = 0 ] || fail "residue reddened the default sweep"
reset
[ "$(status DRY_RUN=false STUBBORN=1 STRICT=true)" = 1 ] || fail "STRICT did not surface residue"

# --- the orphan tag ----------------------------------------------------------------------------
# A previous partial sweep can delete an rc's release and fail before its tag. Enumerating only the
# release listing would never name that tag again, so it would survive every future sweep.
reset
for reg in cluster nas github; do
  jq 'map(select(.tag_name != "v1.0.0-rc.1"))' "$STATE/releases-$reg.json" > "$TMP/j"
  mv "$TMP/j" "$STATE/releases-$reg.json"
done
out="$(run DRY_RUN=false)"
grep -q 'git/refs/tags/v1.0.0-rc.1' "$STATE/delete-order" \
  || fail "an orphan rc tag whose release was already gone was never found: $out"
survivor

# --- the apt/dnf half --------------------------------------------------------------------------
# A published RELEASE does not prove a published PACKAGE, and a candidate left in the repositories is
# still being SERVED: `apt install` hands it to whoever asks long after its release page is gone.
pkgset() { printf '%s\n' "$@" > "$STATE/packages"; }

# The stable has NOT replaced the candidate in the repositories, so the candidate is the only
# installable copy and must be kept even though every release looks perfect.
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing"
out="$(run DRY_RUN=false)"
[ "$(deletes)" = 0 ] || fail "pruned a candidate the stable has not replaced in apt/dnf"
# Pinned to the REASON, and to the bare type rather than a type/arch or type/dist detail: the stable
# published no package of this type at all, and that is a different finding from one that published
# the wrong architecture or reached the wrong distribution. Asserting only "kept" would pass just as
# happily on either of the downstream guards, leaving this one untested.
case "$out" in
  *"does not yet replace it in: debian rpm"*) ;;
  *) fail "kept the rc, but not because the stable published no package of that type: $out" ;;
esac

# Replaced in the same distribution and architecture: now it may go, through each format's OWN
# endpoint (the generic one leaves rpm's repodata advertising a file that 404s).
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
out="$(run DRY_RUN=false)"
grep -Eq "/api/v1/packages/[^/]+/debian/$FAKE_PKG/1\.0\.0~rc\.1$" "$STATE/delete-order" \
  || fail "the debian candidate was not deleted through the generic endpoint: $out"
grep -Eq "/api/packages/[^/]+/rpm/testing/package/$FAKE_PKG/1\.0\.0~rc\.1-1/x86_64$" "$STATE/delete-order" \
  || fail "the rpm candidate was not deleted through the registry-native endpoint: $out"

# The same fixture that just pruned cleanly, with only the index reads failing. The candidate is
# kept, which is the third outcome a failure counter alone misses: nothing was deleted and no release
# was wrong, but the sweep could not establish that a stable replaces this candidate in apt/dnf.
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
out="$(run DRY_RUN=false UNREADABLE_INDEX=1)"
[ "$(deletes)" = 0 ] || fail "pruned while the package index could not be read: $out"
case "$out" in
  *"could not read a package index"*) ;;
  *) fail "an unreadable index was not reported as undetermined: $out" ;;
esac

reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
[ "$(status DRY_RUN=false UNREADABLE_INDEX=1)" = 0 ] \
  || fail "an unreadable index reddened the default sweep, which publish.yml runs after a release"

reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
[ "$(status DRY_RUN=false UNREADABLE_INDEX=1 STRICT=true)" = 1 ] \
  || fail "STRICT reported success while unable to tell whether the candidate was safe to remove"
[ "$(deletes)" = 0 ] || fail "STRICT changed what was deleted; it may only change reporting"
survivor

# The preview is the manual dispatch's DEFAULT, so it has to be as honest as the real run: a dry run
# that could not read an index did not establish the selection it exists to report.
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
[ "$(status DRY_RUN=true UNREADABLE_INDEX=1 STRICT=true)" = 1 ] \
  || fail "a STRICT preview reported a selection it could not establish"
[ "$(deletes)" = 0 ] || fail "a dry run issued deletions"

reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
[ "$(status DRY_RUN=true UNREADABLE_INDEX=1)" = 0 ] \
  || fail "a non-strict preview reddened on an unreadable index"

# Only the STABLE lookup fails. "I could not ask" must not be filed as "it is not published", which
# would read as a confident keep with a reason attached.
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
out="$(run DRY_RUN=false UNREADABLE_STABLE_INDEX=1)"
[ "$(deletes)" = 0 ] || fail "pruned while the stable's index read failed: $out"
case "$out" in
  *"could not read a package index"*) ;;
  *) fail "an unreadable stable index was filed as a plain missing replacement: $out" ;;
esac
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
[ "$(status DRY_RUN=false UNREADABLE_STABLE_INDEX=1 STRICT=true)" = 1 ] \
  || fail "STRICT passed while the stable's index could not be read"
survivor

# Both counters at once, on different candidates. They describe different tags, so a report that
# picked one would tell the operator about a residue they can retry while dropping a candidate whose
# safety was never established at all.
reset
for reg in cluster nas github; do
  jq --arg i "33$reg" --arg j "93$reg" \
     '. + [{"tag_name":"v3.0.0-rc.1","id":$i},{"tag_name":"v3.0.0","id":$j}]' \
     "$STATE/releases-$reg.json" > "$TMP/j" && mv "$TMP/j" "$STATE/releases-$reg.json"
  printf 'v3.0.0-rc.1\nv3.0.0\n' >> "$STATE/tagrefs-$reg"
  jq '.tag_name = "v3.0.0" | .id = 93' "$STATE/stable-$reg.json" > "$STATE/stable-$reg-v3.0.0.json"
done
# Only v1.0.0 has packages, so it is the stem whose index reads fail; v3.0.0 has none, reaches the
# delete, and STUBBORN makes that delete lie.
pkgset "debian 1.0.0~rc.1 amd64 testing" "rpm 1.0.0~rc.1-1 x86_64 testing" \
       "debian 1.0.0 amd64 testing"      "rpm 1.0.0-1 x86_64 testing"
out="$(run DRY_RUN=false STUBBORN=1 UNREADABLE_STABLE_INDEX=1)"
case "$out" in
  *"still carry residue"*) ;;
  *) fail "the composed report dropped the residue half: $out" ;;
esac
case "$out" in
  *"could not read a package index"*) ;;
  *) fail "the composed report dropped the unreadable-index half: $out" ;;
esac
survivor

# A definite keep reason and an unanswered one, on the same candidate. The outcome was never in
# doubt — the stable is provably absent from testing — so the unreadable stable-distribution index
# changed nothing and must not redden a STRICT sweep. A guard that fires when the answer was certain
# is one an operator learns to skip.
reset
# The stable must EXIST as a version, or the check short-circuits on "no package of that type"
# and never reaches an index at all. It is served only in `stable`, so `testing` is a definite
# miss while `stable` is the distribution whose index will not answer.
pkgset "debian 1.0.0~rc.1 amd64 testing" "debian 1.0.0~rc.1 amd64 stable" \
       "debian 1.0.0 amd64 stable"
out="$(run DRY_RUN=false UNREADABLE_INDEX_DIST=stable)"
[ "$(deletes)" = 0 ] || fail "pruned a candidate the stable does not replace: $out"
case "$out" in
  *"(unreadable)"*) ;;
  *) fail "the fixture did not actually produce an unreadable distribution: $out" ;;
esac
case "$out" in
  *"could not read a package index"*)
    fail "an unreadable index was called undetermined next to a definite keep reason: $out" ;;
esac
reset
# The stable must EXIST as a version, or the check short-circuits on "no package of that type"
# and never reaches an index at all. It is served only in `stable`, so `testing` is a definite
# miss while `stable` is the distribution whose index will not answer.
pkgset "debian 1.0.0~rc.1 amd64 testing" "debian 1.0.0~rc.1 amd64 stable" \
       "debian 1.0.0 amd64 stable"
[ "$(status DRY_RUN=false UNREADABLE_INDEX_DIST=stable STRICT=true)" = 0 ] \
  || fail "STRICT reddened a sweep whose keep decision was definite"
survivor

# A stable serving a DIFFERENT architecture does not replace the candidate for the one it serves.
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "debian 1.0.0 arm64 testing"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned though the stable replaced a different architecture"

# ...nor one in a different distribution: `testing` subscribers are exactly who the candidate serves.
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "debian 1.0.0 amd64 stable"
run DRY_RUN=false >/dev/null
[ "$(deletes)" = 0 ] || fail "pruned though the stable replaced it only in another distribution"

# A package left behind by a sweep that removed the release first is still found: enumeration reads
# the package registry too, so that residue is self-healing rather than served forever.
reset
pkgset "debian 1.0.0~rc.1 amd64 testing" "debian 1.0.0 amd64 testing"
for reg in cluster nas github; do
  jq 'map(select(.tag_name != "v1.0.0-rc.1"))' "$STATE/releases-$reg.json" > "$TMP/j"
  mv "$TMP/j" "$STATE/releases-$reg.json"
  grep -vxF 'v1.0.0-rc.1' "$STATE/tagrefs-$reg" > "$TMP/j" && mv "$TMP/j" "$STATE/tagrefs-$reg"
done
out="$(run DRY_RUN=false)"
grep -Eq "/debian/$FAKE_PKG/1\.0\.0~rc\.1$" "$STATE/delete-order" \
  || fail "a package with no release or tag left to name it was never cleared: $out"

# --- tokens ------------------------------------------------------------------------------------
# An absent credential must not read as "nothing to prune": GitHub's releases are public, so the
# sweep would enumerate fine and only fail at the first DELETE, having already swept the others.
for var in CLUSTER_TOKEN NAS_TOKEN GH_TOKEN PACKAGE_TOKEN; do
  reset
  out="$(env PATH="$TMP:$PATH" STATE="$STATE" FAKE_PKG="$FAKE_PKG" PRUNE_RETRY_SLEEP=0 \
    CLUSTER_TOKEN=t NAS_TOKEN=t GH_TOKEN=t PACKAGE_TOKEN=t \
    "$var=" bash "$ROOT/packaging/prune-rcs.sh" 2>&1 || true)"
  case "$out" in
    *"$var"*) ;;
    *) fail "an empty $var was not refused: $out" ;;
  esac
done

echo "prune sweep: PASS"
