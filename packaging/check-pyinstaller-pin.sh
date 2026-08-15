#!/usr/bin/env bash
# Can the PyInstaller pin be lifted yet?
#
# publish.yml holds PyInstaller at 6.22.0. WHY, in the order it was learned:
#
# 6.22.0 added a onefile bootloader check that closes GHSA-9fxf-4qw3-ghmr: a
# onefile app tells its child where it unpacked itself through _PYI_* environment
# variables, and an attacker who spoofs those can point the child at a directory
# they control. The defence is "if you inherited that state, your parent must be
# running the same executable I am", which on POSIX means comparing
# realpath("/proc/self/exe") against realpath("/proc/<ppid>/exe").
#
# 6.22.1 is where that comparison actually took effect on POSIX (its changelog
# lists it under Incompatible Changes), and it is where our release broke:
# whiskerless cross-builds its arm64 Linux binary by emulating arm64 on an amd64
# runner, and buildkit runs the guest binary through an injected emulator, so the
# child's parent resolves to /dev/.buildkit_qemu_emulator rather than to the app.
# Every emulated run therefore fails — the in-image self-test and both arm64
# package smokes — with "Security validation failure: parent process has
# different executable!". That took out the v0.2.0-rc.18 Linux artifacts after
# PyPI and the Homebrew tap had already published.
#
# Not every emulator trips it: the same onefile binary built with 6.22.1 runs
# fine under Docker Desktop's Rosetta on Apple silicon. So a local probe is NOT
# evidence either way, and the only test that settles it is a real tagged build
# on the runner. That is what makes this script a WATCH rather than a test: it
# tells you when upstream has changed something worth spending a release
# candidate on.
#
# Upstream is actively working the same area — as of 2026-08-15 two commits
# relax the check to skip when /proc/<ppid> is unreadable — but an emulated
# /proc entry is readable and merely points somewhere else, so those particular
# relaxations do not reach this case.
#
# Nothing in CI runs this — a weekly job that is green 51 times a year teaches
# people to ignore it. The standing reminder is a claude.ai scheduled watcher
# ("PyInstaller pin watch", Mondays), which carries the same judgement rule and
# reports to Cody directly; this script is the reasoning it was built from, and
# what to run by hand when you want the answer now.
#
# When this script says a release looks promising: bump PYINSTALLER in
# .forgejo/workflows/publish.yml, cut an rc, and watch the "Create releases +
# Linux binary" job — the only one that runs an emulated binary. If it goes
# green, drop the pyinstaller clamp from .renovaterc.json too and let Renovate
# flow again. If it fails the same way, put the pin back and raise known_bad
# below — the rc that proved it is the cheapest possible test.
set -euo pipefail

workflow="$(cd "$(dirname "$0")/.." && pwd)/.forgejo/workflows/publish.yml"
pinned="$(sed -nE 's|^[[:space:]]*PYINSTALLER="([^"]+)".*|\1|p' "$workflow" | head -1)"
# The newest version OBSERVED failing the arm64 release build. Anything up to and
# including this is already answered; only something newer can change the verdict.
known_bad="6.22.1"
latest="$(curl -fsSL https://pypi.org/pypi/pyinstaller/json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])')"

printf 'pinned %s, known bad %s, newest on PyPI %s\n' "$pinned" "$known_bad" "$latest"

# Only a release newer than the known-bad one can lift the pin. Compared with
# plain integer tuples rather than the `packaging` library, because this script
# lives in a directory called packaging/ and would import THAT. A comparison
# that cannot be made is an error, not a quiet "nothing to see": a watch whose
# failure mode is silence is a watch that never fires.
newer="$(python3 -c '
import re, sys


def parts(version):
    numbers = re.findall(r"\d+", version)
    if not numbers:
        raise SystemExit("unparseable version: " + version)
    return tuple(int(n) for n in numbers)


print("yes" if parts(sys.argv[1]) > parts(sys.argv[2]) else "no")' "$latest" "$known_bad")"

if [ "$newer" != "yes" ]; then
    echo "Nothing newer than the known-bad release. Pin stands."
    exit 0
fi

# The changelog is the signal: every change to the parent-process validation is
# named there, and only such a change could lift this.
notes="$(curl -fsSL "https://pyinstaller.org/en/v${latest}/CHANGES.html" |
    python3 -c '
import html, re, sys

# EVERY section newer than the known-bad release, not just the newest one: if the
# fix ships in 6.22.2 and nobody runs this until 6.23.0 is out, reading only the
# newest section would report an all-clear forever while the fix sat in a release
# already installed.
text = html.unescape(re.sub(r"<[^>]+>", " ", sys.stdin.read()))
text = re.sub(r"[ \t]+", " ", text)
heading = re.compile(r"^\s*(\d+\.\d+\.\d+)\s*\(", re.M)
starts = [(m.group(1), m.start()) for m in heading.finditer(text)]
floor = tuple(int(n) for n in re.findall(r"\d+", sys.argv[1]))

# Each version is headed twice — once in the table of contents, where the
# headings sit back to back, and once over the entries themselves. Taking the
# first match yields a section about ninety characters long and a permanent
# all-clear, so keep the longest instance of each.
sections = {}
for index, (version, start) in enumerate(starts):
    if tuple(int(n) for n in re.findall(r"\d+", version)) <= floor:
        continue
    end = starts[index + 1][1] if index + 1 < len(starts) else len(text)
    body = text[start:end]
    if len(body) > len(sections.get(version, "")):
        sections[version] = body
for version, body in sorted(sections.items()):
    print(re.sub(r"\s+", " ", body))
' "$known_bad")"

# Here-strings rather than pipes into grep: `grep -q` exits at the first match and
# `head` after the first few, which SIGPIPEs the writer, and `pipefail` would then
# turn a match into a HOLD — the one wrong answer this script must never give.
matched="$(grep -oiE "[^.]*(parent[- ]process|procfs)[^.]*\." <<<"$notes" || true)"

if [ -n "$matched" ]; then
    echo
    echo "WORTH A TRY: a release newer than $known_bad touches parent-process validation."
    printf '%s\n' "$matched" | sed -n '1,5p'
    echo
    echo "Read those first. Upstream has twice relaxed this check to skip when the"
    echo "procfs entry is UNREADABLE, which is NOT our case (buildkit's entry reads"
    echo "fine, it just names the emulator), so a release carrying only that is not"
    echo "the fix and does not deserve an rc."
    echo "Bump PYINSTALLER in .forgejo/workflows/publish.yml, cut an rc, and watch"
    echo "the \"Create releases + Linux binary\" job specifically: it is the only one"
    echo "that runs an emulated binary, and its six artifacts (two binaries, two"
    echo ".debs, two .rpms) are the verdict. The two macOS .pkgs come from a"
    echo "separate GitHub workflow and say nothing about this. Green means the pin"
    echo "and the clamp in .renovaterc.json can go; a failure means restore the pin"
    echo "and raise known_bad in this script."
else
    echo "HOLD: nothing newer than $known_bad mentions parent-process validation."
fi
