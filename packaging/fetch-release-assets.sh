#!/usr/bin/env bash
# Wait for a set of assets to appear on the PUBLIC Forgejo release, download them into the current
# directory, and print what arrived.
#   fetch-release-assets.sh <tag> <expected-count> <jq-select-expression>
#
# The release page is the rendezvous between the two forges. Architecture decides where a job runs
# (amd64 here, arm64 and macOS on GitHub), so work that needs BOTH halves — the apt/dnf repositories,
# which must never serve a half-architecture set, and the NAS, which no GitHub runner can reach —
# cannot read the other half from a workspace. It reads it from the release instead.
#
# Downloads whatever DID arrive before reporting a shortfall, and exits 1 in that case. A caller that
# wants the partial set uploaded anyway runs this with `|| partial=true`; one that must not act on an
# incomplete set lets the failure stop it. Reporting a shortfall without downloading is what left the
# NAS with nothing at all the first time this was written inline.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"

tag="${1:?usage: fetch-release-assets.sh <tag> <expected-count> <jq-select>}"
expected="${2:?missing expected count}"
select_expr="${3:?missing jq select expression}"
api="https://forgejo.bryantserver.com/api/v1/repos/${PROJECT_REPO_SLUG}"

# 30 minutes of WALL CLOCK, not 180 attempts: each request can itself take up to --max-time, so an
# attempt count would have promised half an hour and delivered up to three and a half. The .pkg is
# notarized by Apple before it is appended, which is the slowest thing anyone waits on here.
# Every request is bounded. An API that accepts the connection and then stalls would otherwise
# park this curl indefinitely, the loop would never reach its next iteration, and the 30 minutes
# above would be a comment rather than a deadline. No --retry: the loop IS the retry, and nesting
# one inside the other is what let a stalling CDN blow update-tap.sh's stated bound.
urls=""
deadline=$(( $(date +%s) + 1800 ))
while :; do
  urls="$(curl -sf --connect-timeout 10 --max-time 60 "$api/releases/tags/$tag" \
            | jq -r "$select_expr" || true)"
  [ "$(printf '%s\n' "$urls" | grep -c . || true)" -ge "$expected" ] && break
  [ "$(date +%s)" -lt "$deadline" ] || break
  sleep 10
done

# `-f` and a `.part` file, both load-bearing. Without --fail, curl writes a 404 or 5xx error page
# to disk and exits 0, and that HTML would be uploaded under the asset's name — to the NAS, whose
# published assets are immutable, so reconcile would then refuse to overwrite the dissenting copy
# it created. Downloading to `.part` first means a failed transfer never leaves anything under the
# real name for a caller's `./*.deb` glob to pick up either.
downloaded=()
while read -r u; do
  [ -n "$u" ] || continue
  name="$(basename "$u")"
  if curl -fsSL --connect-timeout 10 --max-time 300 --retry 3 --retry-connrefused \
       -o "$name.part" "$u" && [ -s "$name.part" ]; then
    mv "$name.part" "$name"
    downloaded+=("$name")
  else
    rm -f "$name.part"
    echo "::warning::could not download $u" >&2
  fi
done <<<"$urls"

found="${#downloaded[@]}"
[ "$found" -eq 0 ] || printf '%s\n' "${downloaded[@]}"

# Counted from what is ON DISK, not from what the API listed: an asset that was advertised and then
# failed to transfer is not one the caller can publish, and saying otherwise is how a short set gets
# reported as complete.
if [ "$found" -lt "$expected" ]; then
  echo "::error::only ${found}/${expected} assets downloaded from $tag's Forgejo release after 30m" >&2
  exit 1
fi
