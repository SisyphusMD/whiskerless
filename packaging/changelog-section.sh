#!/usr/bin/env bash
# Print the body of one CHANGELOG section, used as the release notes.
#   changelog-section.sh 1.2.3   ->  everything under "## [1.2.3]" up to the next "## ["
set -euo pipefail

version="${1:?usage: changelog-section.sh <version>}"

# A release candidate has no section of its own — the notes still live under
# [Unreleased] until the stable release promotes them — so read those instead of
# emitting empty release notes.
case "$version" in
  *-rc.*) version="Unreleased" ;;
esac

awk -v ver="$version" '
  $0 ~ ("^## \\[" ver "\\]")        { grab = 1; next }
  grab && (/^## \[/ || /^\[[^]]*\]:/) { exit }
  grab {
    if (started || $0 != "") { started = 1; print }
  }
' CHANGELOG.md
