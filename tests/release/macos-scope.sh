#!/usr/bin/env bash
# packaging/macos-scope.sh against throwaway repositories.
#
# Every mistake this script can make is silent: a wrong "false" skips a Mac that should have run,
# and the Renovate PR still goes green. So the cases that must run are tested as hard as the ones
# that may skip.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCOPE="$ROOT/packaging/macos-scope.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail=0

repo() { # repo <name>: a repository whose main has one commit, published as origin/main
  local dir="$TMP/$1"
  git init -q -b main "$dir"
  git -C "$dir" -c user.name=t -c user.email=t@t commit -q --allow-empty -m base
  git -C "$dir" update-ref refs/remotes/origin/main HEAD
  printf '%s\n' "$dir"
}

touch_paths() { # touch_paths <dir> <path>...: commit those paths on a fresh branch
  local dir="$1"; shift
  git -C "$dir" switch -q -c work
  for p in "$@"; do mkdir -p "$dir/$(dirname "$p")"; echo x >> "$dir/$p"; done
  git -C "$dir" add -A
  git -C "$dir" -c user.name=t -c user.email=t@t commit -q -m change
}

expect() { # expect <want> <label> <ref> <path>...
  local want="$1" label="$2" ref="$3"; shift 3
  local dir got
  dir="$(repo "$label")"
  [ "$#" -eq 0 ] || touch_paths "$dir" "$@"
  got="$(cd "$dir" && bash "$SCOPE" "$ref")"
  if [ "$got" = "$want" ]; then
    echo "ok   $label"
  else
    echo "FAIL $label: wanted $want, got $got"
    fail=1
  fi
}

R=refs/heads/renovate/some-dep
expect false dockerfile-digest "$R" packaging/install-smoke.Dockerfile packaging/package-smoke.Dockerfile
expect false forgejo-only      "$R" .forgejo/workflows/ci.yml packaging/install-smoke.Dockerfile
expect false release-pins      "$R" packaging/release-pins.env
expect false standard-lock     "$R" STANDARD.lock packaging/release-pins.env
expect false linux-workflows   "$R" .github/workflows/install-matrix.yml .github/workflows/release-linux-arm64.yml
expect false hassfest          "$R" .github/workflows/hassfest.yml

# One relevant path among skippable ones is enough to run.
expect true  python-dep        "$R" pyproject.toml
expect true  lockfile          "$R" uv.lock .forgejo/workflows/ci.yml
expect true  macos-workflow    "$R" .github/workflows/ci-macos.yml .forgejo/workflows/ci.yml
expect true  formula-workflow  "$R" .github/workflows/formula-macos.yml
expect true  formula           "$R" packaging/homebrew/thing.rb
expect true  source            "$R" src/pkg/constants.py packaging/release-pins.env
expect true  unknown-path      "$R" somewhere/new.txt
# Anchored, so a Dockerfile in a subdirectory or a lookalike workflow name is not swept in.
expect true  nested-dockerfile "$R" packaging/macos/build.Dockerfile
expect true  lookalike         "$R" .github/workflows/release-macos.yml.bak
expect true  no-change         "$R"

# Never skipped, whatever they change.
expect true  main              refs/heads/main packaging/install-smoke.Dockerfile
expect true  tag               refs/tags/v1.2.3 packaging/install-smoke.Dockerfile
expect true  human-branch      refs/heads/fix/thing packaging/install-smoke.Dockerfile
expect true  pull-request      refs/pull/7/merge packaging/install-smoke.Dockerfile

# Moving a Mac-visible file into a skippable path deletes it from where the Mac reads it.
dir="$(repo rename)"
mkdir -p "$dir/src"; echo 'VALUE = 1' > "$dir/src/constants.py"
git -C "$dir" add -A; git -C "$dir" -c user.name=t -c user.email=t@t commit -q -m seed
git -C "$dir" update-ref refs/remotes/origin/main HEAD
git -C "$dir" switch -q -c work; mkdir -p "$dir/.forgejo"
git -C "$dir" mv src/constants.py .forgejo/constants.py
git -C "$dir" -c user.name=t -c user.email=t@t commit -q -m move
got="$(cd "$dir" && bash "$SCOPE" "$R")"
if [ "$got" = true ]; then echo "ok   rename"; else echo "FAIL rename: got $got"; fail=1; fi

# No origin/main to measure against: undecidable, so it runs.
dir="$TMP/no-base"
git init -q -b main "$dir"
git -C "$dir" -c user.name=t -c user.email=t@t commit -q --allow-empty -m only
got="$(cd "$dir" && bash "$SCOPE" "$R")"
if [ "$got" = true ]; then echo "ok   no-base"; else echo "FAIL no-base: got $got"; fail=1; fi

exit "$fail"
