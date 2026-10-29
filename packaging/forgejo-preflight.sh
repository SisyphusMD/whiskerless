#!/bin/sh
# Fail fast, and recognisably, when this GitHub runner's address is banned at Forgejo's edge.
#
#   forgejo-preflight.sh [forge-url]      default https://forgejo.bryantserver.com
#
# GitHub's hosted runners borrow recycled cloud addresses, and the cluster's CrowdSec bans an
# address that probed it, for hours. A runner that inherits one gets HTTP 403 for everything it asks
# Forgejo, however correct the request (observed, dreame-valetudo v0.3.0-rc.48: the x86_64_linux
# bottle job's tap clone, five tries). Nothing in the repository causes that and a fresh runner
# almost always has a different address, so it is the runner's fault, like a resolver outage.
#
# The probe is an ANONYMOUS read of a public endpoint, which Forgejo itself never answers with 403.
# A 403 here can only be the edge, so it is safe to call transient; a 403 later, on an authenticated
# upload, may be a revoked token and must stay red. That is why this runs as its own step, first:
# triage-infra-failure.py retries only when THIS step failed with THIS script's marker.
set -eu

forge="${1:-https://forgejo.bryantserver.com}"
url="$forge/api/v1/version"

# A dropped connection or a 5xx is not a ban: let curl retry those itself, then report plainly.
code=$(curl -sS -o /dev/null -w '%{http_code}' --retry 3 --retry-all-errors --max-time 30 "$url" 2>/dev/null) || code=000
case "$code" in
  200)
    echo "forgejo-preflight: $forge is reachable from this runner"
    ;;
  403)
    # The exact spelling triage-infra-failure.py matches. Change both together.
    echo "forgejo-preflight: edge refused this runner (anonymous GET $url returned HTTP 403)" >&2
    exit 1
    ;;
  *)
    echo "forgejo-preflight: $url returned HTTP $code" >&2
    exit 1
    ;;
esac
