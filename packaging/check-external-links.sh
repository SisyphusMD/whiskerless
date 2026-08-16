#!/usr/bin/env bash
# Check that the external pages this repo cites as SOURCES still resolve.
#
# Only load-bearing citations belong here — pages whose content we relied on and
# would have to re-derive if they moved. Whisker's control-panel article is the
# button matrix in docs/devices/litter-robot-4/control-panel.md; the brands
# announcement is why the integration ships its own images instead of PRing
# home-assistant/brands. A rotted URL there leaves a claim with no way back to
# its evidence.
#
# NOT a link checker for every URL in the repo: badges, package indexes and
# GitHub issue links come and go, and failing CI on someone else's outage buys
# nothing. packaging/check-doc-links.py covers the relative links, which are the
# ones we can actually break ourselves.
set -euo pipefail

URLS=(
  "https://www.litter-robot.com/support/article/litter-robot-4-control-panel-button-functions/"
  "https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api"
)

fail=0
for url in "${URLS[@]}"; do
  # Retry before believing a failure: a transient 5xx from a vendor CDN is not a
  # repo problem, and a check that cries wolf gets ignored the one time it is
  # right. HEAD first, then GET — some hosts answer HEAD with 405 while serving
  # the page perfectly well.
  code=$(curl -sS -o /dev/null -w '%{http_code}' -L --max-time 20 \
    --retry 3 --retry-delay 2 --retry-all-errors -A "whiskerless-ci" -I "$url" || echo 000)
  case "$code" in
    2*|3*) echo "ok   $code  $url"; continue ;;
  esac
  code=$(curl -sS -o /dev/null -w '%{http_code}' -L --max-time 20 \
    --retry 3 --retry-delay 2 --retry-all-errors -A "whiskerless-ci" "$url" || echo 000)
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
