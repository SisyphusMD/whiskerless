#!/usr/bin/env bash
# Bring the vendored standard into line with whatever PROJECT_STANDARD now pins.
#
#   revendor-standard.sh
#
# Renovate can raise the pin in release-pins.env, because that line carries a datasource. It cannot
# re-vendor: the files come from a tag of another repository. So an unaided bump lands a pin that
# claims one version beside files from another, the drift lock fails it, and the PR sits red until a
# human does by hand what this does automatically. Called from refresh-pins.sh, which Renovate
# already runs as a postUpgradeTask, so the pin and the files it describes reach the branch together.
#
# Nothing here decides WHICH version to move to. That is the pin's job, and this only obeys it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
pins="$here/release-pins.env"
lock="$root/STANDARD.lock"

pinned="$(sed -nE 's|^[[:space:]]*PROJECT_STANDARD="([^"]+)".*|\1|p' "$pins" | head -1)"
[ -n "$pinned" ] || { echo "no PROJECT_STANDARD pin in $pins" >&2; exit 1; }
want="v${pinned}"

# The lock is the record of what is actually on disk. Comparing against it rather than re-vendoring
# unconditionally keeps this a no-op on every branch that did not touch the pin — which is nearly all
# of them, and Renovate runs this on each one.
have="$(sed -nE 's|.*"source_tag"[[:space:]]*:[[:space:]]*"([^"]+)".*|\1|p' "$lock" | head -1)"
if [ "$have" = "$want" ]; then
  echo "standard already vendored from $want"
  exit 0
fi

# Stated rather than assumed. The Renovate image is Node-based and carries python3 today, and it is
# pinned by digest so that cannot change without a visible bump — but if one ever drops it, this has
# to say so plainly instead of half-vendoring.
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to re-vendor the standard, and this environment has none" >&2
  exit 1
}

echo "re-vendoring the standard: $have -> $want"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Shallow, and at the tag: vendor.py stamps the lock from `git describe --exact-match`, so the
# checkout has to BE the tag rather than a branch that happens to contain it.
# Bounded three ways, because each covers a stall the others do not. GIT_TERMINAL_PROMPT stops a
# credential prompt waiting on a terminal nobody is at; the low-speed settings abort a transfer that
# connects and then crawls; the wall clock catches one that stays just fast enough to look alive and
# never finishes. Unbounded, any of them pins the Renovate worker until the whole job deadline and
# starves every other repository in that run.
deadline="${REVENDOR_CLONE_SECONDS:-300}"
GIT_TERMINAL_PROMPT=0 git \
  -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 -c advice.detachedHead=false \
  clone --quiet --depth 1 --branch "$want" \
  https://forgejo.bryantserver.com/SisyphusMD/project-standard.git "$work/standard" &
clone=$!

# A shell watchdog rather than coreutils `timeout`, which a default macOS install does not have.
# The low-speed settings above only catch a transfer that crawls; a server feeding bytes just fast
# enough to look alive would otherwise hold this open forever.
( sleep "$deadline"; kill -TERM "$clone" 2>/dev/null || true ) &
watchdog=$!

rc=0
wait "$clone" || rc=$?
kill -TERM "$watchdog" 2>/dev/null || true
wait "$watchdog" 2>/dev/null || true
if [ "$rc" -ne 0 ]; then
  echo "cloning the standard at $want failed or exceeded ${deadline}s" >&2
  exit 1
fi

# The standard's own vendor.py, not a copy of its logic: one implementation decides what `shared/`
# means and how the lock is written, and it travels with the tag being vendored.
python3 "$work/standard/tools/vendor.py" "$root" >/dev/null

# Fail closed. A silent partial vendor would leave exactly the pin/files disagreement this exists to
# prevent, and the next thing to notice would be the drift lock failing in CI.
now="$(sed -nE 's|.*"source_tag"[[:space:]]*:[[:space:]]*"([^"]+)".*|\1|p' "$lock" | head -1)"
[ "$now" = "$want" ] || { echo "re-vendor did not take: lock says $now, pin says $want" >&2; exit 1; }
echo "standard re-vendored from $want"
