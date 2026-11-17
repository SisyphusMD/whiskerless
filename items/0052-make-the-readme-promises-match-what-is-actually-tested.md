# #52 Make the README promises match what is actually tested

- Kind: pull, state: closed, by cody, created 2026-08-26T07:34:45-07:00
- Labels: none; milestone: none
- refs/pull/52/head -> main, merged: True

The README is a promise — "tested on every minimum version below" — and nothing checked it. Seven claims had drifted from what any lane actually runs:

- The `.rpm` was never installed on the oldest maintained Fedora, only upgrade-tested from source in the pre-merge ladder. Now a real install lane.
- openSUSE Leap 15.6 was already install-tested while the table named 16.0 as the minimum, understating real coverage.
- Windows is claimed to work; nothing tests it. Now stated plainly rather than implied.
- RHEL and Raspberry Pi OS are named but have no lane — RHEL has no public image to install into, Raspberry Pi OS is Debian 12 underneath. Both are covered by inheritance, and now the README says so.

The invariant that replaces the guesswork parses the support table, resolves the Dockerfile stage graph down from the channel list, and asserts every promised version has a channel that really installs the shipped package on it. Text-searching the Dockerfile was not enough: a pinned-but-unused base looks identical to a tested one, which is exactly the Fedora gap.

Two systems carry no version number, so the parse structurally cannot see them — their disclaimers are pinned separately.

Also fixes a lane that reported success while testing very little: the new Fedora base installed only curl, so `installed-smoke.sh` took its no-openssl branch and skipped every certificate, backup and restore check while still printing PASS.
