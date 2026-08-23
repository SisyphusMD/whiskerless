#!/usr/bin/env bash
# The ONE place a formula template becomes a formula. Writes to stdout.
#   render-formula.sh <template.rb> <pypi-version> <sdist-sha256> [bottle-block-file]
#
# It exists because there were three copies of this substitution — the tap's two
# passes and the install smoke — and teaching only two of them about a newly added
# marker shipped a formula carrying the bare word `REPLACE_BOTTLE_BLOCK`. Ruby
# parses a bare word as a constant, so nothing caught it until Homebrew tried to
# load the formula and died on `uninitialized constant`, on the one job that has
# to be green before a release can be tagged.
#
# So: one renderer, and it refuses to emit anything with a marker left in it. A
# new marker in the template then fails loudly here rather than quietly in a
# formula users install.
set -euo pipefail

[ "$#" -ge 3 ] && [ "$#" -le 4 ] || {
  echo "usage: $0 <template.rb> <pypi-version> <sdist-sha256> [bottle-block-file]" >&2; exit 2; }
template="$1"; version="$2"; sha="$3"; block="${4:-}"

[ -f "$template" ] || { echo "no such template: $template" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Always a file, and never empty: `sed r` on an empty file swallows the blank line
# the marker stands in for and glues the block onto `license`.
printf '\n' > "$work/block"
if [ -n "$block" ]; then
  [ -f "$block" ] || { echo "no such bottle block: $block" >&2; exit 2; }
  cat "$block" >> "$work/block"
  printf '\n' >> "$work/block"
fi

# Two spellings for the same thing, because the two projects name their source archive
# differently and both are accurate: whiskerless publishes a PyPI sdist, dreame-valetudo a
# byte-reproducible source tarball. Substituting both is what lets ONE renderer serve both
# templates — and the leftover-marker guard below still catches a template that used neither.
sed -e "s|REPLACE_PYPI_VERSION|${version}|g" \
    -e "s|REPLACE_VERSION|${version}|g" \
    -e "s|REPLACE_SDIST_SHA256|${sha}|" \
    -e "s|REPLACE_TARBALL_SHA256|${sha}|" \
    -e "/REPLACE_BOTTLE_BLOCK/r $work/block" \
    -e "/REPLACE_BOTTLE_BLOCK/d" \
    "$template" > "$work/out.rb"

# Any leftover marker, matched as a pattern rather than a hand-kept list — the
# list going stale is the bug this file was created to make impossible.
if grep -q 'REPLACE_' "$work/out.rb"; then
  echo "template markers survived rendering $template:" >&2
  grep -n 'REPLACE_' "$work/out.rb" >&2
  exit 1
fi

cat "$work/out.rb"
