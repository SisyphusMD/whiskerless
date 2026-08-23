#!/usr/bin/env bash
# Recompute the pins that Renovate cannot derive on its own, and rewrite them in place.
#
# Run by Renovate as a postUpgradeTask on the update branch. The case that makes this mandatory:
# PYTHON_SHA256 guards the CPython tarball the Linux binaries are built from, and Renovate's
# python-version datasource bumps PYTHON_VERSION without knowing that checksum. Patch updates
# automerge, so without this a Python bump would sail through green and then fail every subsequent
# tagged release inside linux.Dockerfile, where the sha256 is verified.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
pins="$here/release-pins.env"

sha256_stdin() {
  # macOS has shasum, Linux runners have sha256sum; neither is guaranteed to be the other.
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  else
    shasum -a 256 | cut -d' ' -f1
  fi
}

read_pin() { # read_pin <VAR_NAME>
  sed -nE "s|^[[:space:]]*$1=\"([^\"]+)\".*|\\1|p" "$pins" | head -1
}

rewrite() { # rewrite <sed-expression>
  # -E and a temp file: BSD and GNU sed disagree about -i's argument, so neither form is portable.
  sed -E "$1" "$pins" > "$pins.tmp"
  mv "$pins.tmp" "$pins"
}

py_version="$(read_pin PYTHON_VERSION)"
py_current="$(read_pin PYTHON_SHA256)"
[ -n "$py_version" ] || { echo "could not read PYTHON_VERSION from $pins" >&2; exit 1; }

url="https://www.python.org/ftp/python/${py_version}/Python-${py_version}.tar.xz"
py_fresh="$(curl -fsSL --retry 3 --retry-delay 2 "$url" | sha256_stdin)"
[ -n "$py_fresh" ] || { echo "could not hash $url" >&2; exit 1; }

if [ "$py_fresh" = "$py_current" ]; then
  echo "PYTHON_SHA256 already correct for CPython $py_version"
else
  rewrite "s|^([[:space:]]*PYTHON_SHA256=\")[0-9a-f]{64}(\")|\\1${py_fresh}\\2|"
  echo "PYTHON_SHA256 -> $py_fresh (CPython $py_version)"
  [ "$(read_pin PYTHON_SHA256)" = "$py_fresh" ] || {
    echo "rewrite did not take effect" >&2; exit 1; }
fi
