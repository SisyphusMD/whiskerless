#!/usr/bin/env bash
# Decide whether one push needs the macOS jobs (.forgejo/workflows/macos.yml).
#
#   macos-scope.sh <ref> [base]     # prints "true" or "false"; base defaults to origin/main
#
# Run from a checkout of the pushed commit with enough history to find where it left <base>.
#
# The macOS jobs run in one VM per macOS version, one job at a time, and every push to every branch
# queues two of them per project. Renovate rebases its whole backlog after each push to main, so one
# main push can queue thirty macOS runs at once, most of them for a Dockerfile digest or a workflow
# that no Mac ever reads, and real verdicts wait hours behind them.
#
# Only a Renovate branch is ever skipped. main, tags and every other branch always run: the release
# gates read the macOS verdict for exact commits on main, and a person's branch has no predictable
# shape. A Renovate branch is skipped only when EVERY path it changes is on the list below, so a
# path nobody thought about runs. A new file can cost a macOS run, never hide one.
#
# A skipped job still satisfies a required check, which is what lets a Renovate PR merge without
# waiting on a Mac. That is safe only because merges are merge commits: the SHA that lands on main
# is new, and main always runs in full. (The release gate, check-forgejo-ci.sh, refuses a run whose
# jobs were all skipped, and refuses Renovate branches outright.)
set -euo pipefail

ref="${1:?usage: macos-scope.sh <ref> [base]}"
base="${2:-origin/main}"

case "$ref" in
  refs/heads/renovate/*) ;;
  *) echo true; exit 0 ;;
esac

# Read only by Linux jobs, Forgejo, or tag-only release workflows. The macOS jobs test the package,
# the formula and its Python dependencies; none of these reach them. The release workflows' macOS
# jobs run on a Mac too, but only for a tag, which this never sees.
linux_only='^(\.forgejo/.*|packaging/[^/]*Dockerfile|packaging/release-pins\.env|STANDARD\.lock)$'
# Except the macOS workflow itself: a bump to an action it uses is exactly what its run would test,
# and the broad .forgejo/ entry above would otherwise skip it.
needs_mac='^\.forgejo/workflows/macos\.yml$'

# Undecidable means run: a scope that cannot be computed must not quietly turn into a skip.
fork="$(git merge-base "$base" HEAD 2>/dev/null)" || { echo true; exit 0; }
# --no-renames: a rename lists only its destination, so moving a file a Mac reads into a
# skippable path would look like adding a skippable file. Both halves have to be classified.
changed="$(git diff --no-renames --name-only "$fork" HEAD)"
if [ -z "$changed" ] || grep -Eq "$needs_mac" <<<"$changed" || grep -Evq "$linux_only" <<<"$changed"; then
  echo true
else
  echo false
fi
