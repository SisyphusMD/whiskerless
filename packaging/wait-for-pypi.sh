#!/usr/bin/env bash
# Block until this project's library is installable from PyPI at <version>.
#   wait-for-pypi.sh <version>        e.g. 0.2.0-rc.1 (the tag's spelling, without the v)
#
# Every GitHub workflow that can CREATE a release has to call this first. They are triggered by the
# mirrored tag, independently of Forgejo's publish.yml, and the release helpers create the release
# when it is missing — so without this a slow or failed PyPI upload lets HACS offer an update whose
# manifest pins a version pip cannot install. Two workflows need it now (the .pkg and the arm64
# Linux set), which is why it is a script rather than a third inline copy.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"
PKG="${PROJECT_REPO_SLUG#*/}"

version="${1:?usage: wait-for-pypi.sh <version>}"
# PEP 440: the tag says 0.2.0-rc.1, PyPI normalizes it to 0.2.0rc1.
pypi_version="$(printf '%s' "$version" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"

# The per-version endpoint, which is 404 until that exact version is served — the project-level one
# answers 200 from the first release ever made and would pass instantly for a version that does not
# exist.
# WALL CLOCK, and bounded per request. An attempt count would have been a promise the loop could not
# keep: each stalled request can burn --max-time on its own, so 60 attempts of "30s + 10s" is forty
# minutes wearing a ten-minute label. No --retry: the loop is the retry.
#
# The window has to cover the QUEUE, not the upload. These workflows are triggered by the mirrored
# tag, which arrives within seconds, while the Forgejo pipeline that actually uploads to PyPI can sit
# behind unrelated jobs for far longer than the upload itself takes — so this is sized against how
# long a busy forge can defer a job, not against how long twine runs.
window="${PYPI_WAIT_SECONDS:-2700}"
deadline=$(( $(date +%s) + window ))
while :; do
  if curl -sSfI -o /dev/null --connect-timeout 10 --max-time 30 \
      "https://pypi.org/pypi/${PKG}/${pypi_version}/json"; then
    echo "${PKG} ${pypi_version} is on PyPI"
    exit 0
  fi
  [ "$(date +%s)" -lt "$deadline" ] || break
  sleep 10
done
echo "::error::${PKG} ${pypi_version} never appeared on PyPI within ${window}s" >&2
exit 1
