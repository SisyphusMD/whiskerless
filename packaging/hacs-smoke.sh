#!/usr/bin/env bash
# Install the Home Assistant integration the way HACS installs it, then load it.
#   hacs-smoke.sh <tag> <version> [forge-url]
#
# The integration is the project's other half and nothing installed it. It also has
# a failure mode the library does not: it is DEVELOPED against src/ at HEAD but
# SHIPS depending on the PUBLISHED library through its manifest, exactly as the
# official litterrobot integration depends on pylitterbot. Use one API that has not
# been released yet and every HACS user gets an integration that cannot start,
# while every test in this repository still passes.
#
# So this takes what HACS takes — the repository archive AT THE TAG, not a
# checkout, which for a re-dispatch would be main and pin the wrong version — then
# installs the requirements its manifest asks for and imports the whole integration
# against them.
set -euo pipefail

TAG="${1:?usage: $0 <tag> <version> [forge]}"
VERSION="${2:?usage: $0 <tag> <version> [forge]}"
FORGE="${3:-https://forgejo.bryantserver.com}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "== HACS smoke: $TAG"

curl -fsSL "$FORGE/SisyphusMD/whiskerless/archive/${TAG}.tar.gz" -o "$work/repo.tgz"
mkdir -p "$work/extract" "$work/cfg/custom_components"
tar xzf "$work/repo.tgz" -C "$work/extract"
cp -r "$work"/extract/*/custom_components/whiskerless "$work/cfg/custom_components/"

manifest="$work/cfg/custom_components/whiskerless/manifest.json"
declared="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$manifest")"
if [ "$declared" != "$VERSION" ]; then
  echo "  FAIL  the tag's manifest says $declared, not $VERSION — HACS would offer an update whose library pin belongs to another release" >&2
  exit 1
fi
echo "  ok    the manifest at $TAG declares $declared"

python3 -m venv "$work/ha"
"$work/ha/bin/pip" install -q homeassistant
echo "  ok    home assistant installed"

# Installed straight from the manifest, the way Home Assistant installs them, so a
# requirement PyPI cannot satisfy fails here rather than on somebody's box. The
# spelling matters too: the tag is `0.2.0-rc.31` and PyPI normalises to
# `0.2.0rc31`, and pip is what decides whether those are the same thing.
python3 -c "import json,sys; print('\n'.join(json.load(open(sys.argv[1]))['requirements']))" "$manifest" \
  | while read -r requirement; do
      [ -n "$requirement" ] || continue
      echo "  ..    manifest requires $requirement"
      "$work/ha/bin/pip" install -q "$requirement"
    done
echo "  ok    every manifest requirement installed from PyPI"

touch "$work/cfg/custom_components/__init__.py"
WHISKERLESS_CFG="$work/cfg" "$work/ha/bin/python" - <<'PY'
import importlib, os, pathlib, sys

sys.path.insert(0, os.environ["WHISKERLESS_CFG"])
package = pathlib.Path(os.environ["WHISKERLESS_CFG"]) / "custom_components" / "whiskerless"
modules = sorted(p.stem for p in package.glob("*.py") if p.stem != "__init__")
if not modules:
    raise SystemExit("no integration modules found — the archive layout changed")
importlib.import_module("custom_components.whiskerless")
for name in modules:
    importlib.import_module(f"custom_components.whiskerless.{name}")
print(f"  ok    {len(modules) + 1} integration modules import against the published library")
PY

echo
echo "HACS smoke PASS: $TAG"
