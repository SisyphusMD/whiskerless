#!/usr/bin/env bash
# Decide whether one push needs the GitHub mirror's macOS workflows.
#
#   macos-scope.sh <ref> [base]     # prints "true" or "false"; base defaults to origin/main
#
# Run from a checkout of the pushed commit with enough history to find where it left <base>.
#
# GitHub runs this account's macOS jobs a few at a time, and every push to every branch queues
# two of them per project. Renovate rebases its whole backlog after each push to main, so one main
# push used to queue thirty macOS runs at once, most of them for a Dockerfile digest or a Forgejo
# workflow that no Mac ever reads, and real verdicts waited hours behind them.
#
# Only a Renovate branch is ever skipped. main, tags and every other branch always run: the release
# gates read the macOS verdict for exact commits on main, and a person's branch has no predictable
# shape. A Renovate branch is skipped only when EVERY path it changes is on the list below, so a
# path nobody thought about runs. A new file can cost a macOS run, never hide one.
#
# A skipped run still concludes "success" (the job that ran this succeeded), which is what lets
# check-mirror-ci.sh pass a Renovate PR without waiting on a Mac. That is safe only because merges
# are merge commits: the SHA that lands on main is new, and main always runs in full.
set -euo pipefail

ref="${1:?usage: macos-scope.sh <ref> [base]}"
base="${2:-origin/main}"

case "$ref" in
  refs/heads/renovate/*) ;;
  *) echo true; exit 0 ;;
esac

# Read only by Linux jobs, Forgejo, or tag-only release workflows. The macOS CI and formula
# workflows test the package, the formula and its Python dependencies; none of these reach them.
# release-macos.yml and bottles.yml do run on a Mac, but only for a tag, which this never sees.
linux_only='^(\.forgejo/.*|packaging/[^/]*Dockerfile|packaging/release-pins\.env|STANDARD\.lock|\.github/workflows/(bottles|ci-pr|hassfest|install-matrix|release-linux-arm64|release-macos|retry-infra-failures)\.yml)$'

# Undecidable means run: a scope that cannot be computed must not quietly turn into a skip.
fork="$(git merge-base "$base" HEAD 2>/dev/null)" || { echo true; exit 0; }
# --no-renames: a rename lists only its destination, so moving a file a Mac reads into a
# skippable path would look like adding a skippable file. Both halves have to be classified.
changed="$(git diff --no-renames --name-only "$fork" HEAD)"
if [ -z "$changed" ] || grep -Evq "$linux_only" <<<"$changed"; then
  echo true
else
  echo false
fi
