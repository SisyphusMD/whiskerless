#!/usr/bin/env bash
# Check that the external pages this repo cites as SOURCES still resolve.
#
# Only load-bearing citations belong here — pages whose content we relied on and
# would have to re-derive if they moved. Whisker's control-panel article is the
# button matrix in docs/devices/litter-robot-4/control-panel.md; the brands
# announcement is why the integration ships its own images instead of PRing
# home-assistant/brands. The esphome-litter-robot UART reference is the only
# source for the 0x2D factory-reset refusal and the unverified register names in
# docs/devices/litter-robot-4/registers.md. A rotted URL there leaves a claim with
# no way back to its evidence.
#
# NOT a link checker for every URL in the repo: badges, package indexes and
# GitHub issue links come and go, and failing CI on someone else's outage buys
# nothing. packaging/check-doc-links.py covers the relative links, which are the
# ones we can actually break ourselves.
#
# The loop below is identical in dreame-valetudo; keep the two in step.
set -euo pipefail

URLS=(
  "https://www.litter-robot.com/support/article/litter-robot-4-control-panel-button-functions/"
  "https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api"
  "https://codeberg.org/Joseph-DiGiovanni/esphome-litter-robot/src/branch/main/docs/Litter%20Robot%204/UART%20Reference.md"
)

fail=0
for url in "${URLS[@]}"; do
  # Retry before believing a failure: a transient 5xx from a CDN is not a repo problem. HEAD first,
  # then a one-byte ranged GET, because some hosts answer HEAD with 405 while serving the page, and
  # a cited PDF should not be downloaded just to prove it exists.
  code=$(curl -sS -o /dev/null -w '%{http_code}' -L --max-time 20 \
    --retry 3 --retry-delay 2 --retry-all-errors -A "check-external-links" -I "$url" || true)
  case "${code:-000}" in
    2*|3*) echo "ok   $code  $url"; continue ;;
  esac
  code=$(curl -sS -o /dev/null -w '%{http_code}' -L --max-time 20 \
    --retry 3 --retry-delay 2 --retry-all-errors -A "check-external-links" -r 0-0 "$url" || true)
  code=${code:-000}
  case "$code" in
    2*|3*) echo "ok   $code  $url (GET; HEAD refused)" ;;
    *)     echo "FAIL $code  $url"; fail=1 ;;
  esac
done

if [ "$fail" -ne 0 ]; then
  echo
  echo "A cited source no longer resolves. Find where it moved, update the doc that" >&2
  echo "cites it, and update this list — do not just delete the citation." >&2
  exit 1
fi
echo "all cited sources resolve"
