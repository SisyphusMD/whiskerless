#!/usr/bin/env bash
# Build, package, sign and smoke ONE architecture's Linux release artifacts.
#   build-linux-arch.sh <amd64|arm64> <tag>
#
# Called by BOTH forges, which is the whole point: architecture decides where a job runs — amd64 on
# the self-hosted Forgejo runner, arm64 on GitHub's native arm runner, nothing emulated anywhere —
# and two inline copies of this logic would drift the first time one was edited. The build recipe
# itself already lived in linux.Dockerfile and nfpm.yaml; this is the orchestration around it.
#
# Requires: docker with buildx, and GPG_SIGNING_KEY in the environment.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$(dirname "$here")"
# Sourced HERE, not by the caller. A caller that sources them makes plain shell assignments, which
# a child `bash` does not inherit — every pin would then be unset under `set -u` and the build would
# die on the first expansion. Owning the sourcing means the two forges cannot get this differently.
# shellcheck source=/dev/null
. "$here/release-pins.env"

arch="${1:?usage: build-linux-arch.sh <amd64|arm64> <tag>}"
tag="${2:?missing tag}"
case "$arch" in
  amd64) rpmarch=x86_64; suffix=x86_64; builder="$MANYLINUX_AMD64" ;;
  arm64) rpmarch=aarch64; suffix=arm64;  builder="$MANYLINUX_ARM64" ;;
  *) echo "unknown architecture: $arch" >&2; exit 2 ;;
esac

# NATIVE, always. `--platform` here names the architecture this runner already is; it is not a
# request to emulate. If the two ever disagree the build silently becomes an emulated one, which is
# the failure mode this whole arrangement exists to remove — so it is checked rather than assumed.
host="$(docker version --format '{{.Server.Arch}}' 2>/dev/null || uname -m)"
case "$host:$arch" in
  x86_64:amd64|amd64:amd64|aarch64:arm64|arm64:arm64) : ;;
  *) echo "refusing to build $arch on a $host host — that would be emulation" >&2; exit 1 ;;
esac

# deb and rpm both sort `~rc.1` BEFORE the final release; the tag's `-rc.1` is illegal in a deb
# version and sorts AFTER 0.2.0 in rpm. `raw` keeps the tag spelling for the raw binary's name.
raw="${tag#v}"
VERSION="${raw/-rc./~rc.}"
ARCH="$arch"
export VERSION ARCH

# Written outside the build context: `docker cp .` sends the whole workspace, so a key sitting in
# the repo tree would be one stray `git add` from being committed.
: "${GPG_SIGNING_KEY:?the signing key secret is missing — refusing to publish unsigned packages}"
KEYFILE="$(mktemp)"; chmod 600 "$KEYFILE"
printf '%s' "$GPG_SIGNING_KEY" > "$KEYFILE"
CIDS=""
cleanup() {
  rm -f "$KEYFILE"
  for c in $CIDS; do docker rm -f "$c" >/dev/null 2>&1 || true; done
}
trap cleanup EXIT

# Generated here, never committed: a checked-in .gz drifts from its source the first time the page
# is edited and nobody regenerates it. -n so the timestamp does not make the package unreproducible.
gzip -9 -n -c packaging/whiskerless.1 > packaging/whiskerless.1.gz

nfpm_pkg() { # nfpm_pkg <deb|rpm> <output-filename>
  local fmt="$1" name="$2" cid
  cid=$(docker create -e ARCH -e VERSION \
    -e NFPM_SIGNING_KEY_FILE=/signing-key.asc -w /w "$NFPM" \
    package -p "$fmt" -f packaging/nfpm.yaml -t "/w/$name")
  CIDS="$CIDS $cid"
  docker cp . "$cid":/w
  docker cp "$KEYFILE" "$cid":/signing-key.asc
  docker start -a "$cid"
  docker cp "$cid":"/w/$name" .
  docker rm -f "$cid" >/dev/null
}

rm -rf "out-$ARCH"
docker buildx build --platform "linux/$arch" \
  --build-arg PYTHON_BUILD_IMAGE="$builder" \
  --build-arg PYTHON_VERSION="$PYTHON_VERSION" \
  --build-arg PYTHON_SHA256="$PYTHON_SHA256" \
  --build-arg PYINSTALLER="$PYINSTALLER" \
  -f packaging/linux.Dockerfile --target export --output "type=local,dest=out-$ARCH" .

# nfpm.yaml reads ./dist/whiskerless; the raw release asset carries the version and arch in its
# name. The tag spelling, not VERSION's ~rc.N: the tilde is a deb/rpm ordering requirement, and
# GitHub rewrites it to a dot in filenames — the raw binary must carry one name on every forge.
rm -rf dist && mkdir dist
cp "out-$ARCH/whiskerless" dist/whiskerless
cp "out-$ARCH/whiskerless" "whiskerless-${raw}-linux-$suffix"
nfpm_pkg deb "whiskerless_${VERSION}_${ARCH}.deb"
nfpm_pkg rpm "whiskerless-${VERSION}.${rpmarch}.rpm"

# nfpm assembles the package OUTSIDE the build image, so nothing else in the release path compares
# what shipped against what was frozen. A .deb carrying a stale or wrong-arch binary still installs,
# still reports a version, and still passes the install smoke — which runs whatever is named
# `whiskerless`. Compare the bytes. Extracted inside a pinned image because nothing else in these
# workflows uses dpkg, so its presence would be an assumption rather than a fact.
built=$(sha256sum dist/whiskerless | cut -d" " -f1)
pcid=$(docker create -w /w "$PARITY_IMAGE" sh -c \
  'dpkg-deb -x /w/pkg.deb /x && sha256sum /x/usr/bin/whiskerless | cut -d" " -f1')
CIDS="$CIDS $pcid"
docker cp "whiskerless_${VERSION}_${ARCH}.deb" "$pcid":/w/pkg.deb
packaged=$(docker start -a "$pcid" 2>/dev/null | tr -d "[:space:]") || true
docker rm -f "$pcid" >/dev/null
[ -n "$packaged" ] || { echo "::error::could not read the packaged binary back"; exit 1; }
[ "$built" = "$packaged" ] || {
  echo "::error::the .deb does not carry the binary that was built ($packaged != $built)"
  exit 1
}
echo "  package parity ok: $packaged"

smoke_pkg() { # smoke_pkg <deb|rpm> <package>
  local fmt="$1" package="$2"
  local result="package-smoke-$fmt-$arch"
  local dockerfile=packaging/package-smoke.Dockerfile
  [ "$fmt" = rpm ] && dockerfile=packaging/package-smoke-rpm.Dockerfile
  cp "$package" "package-smoke.$fmt"
  rm -rf "$result"
  docker buildx build --platform "linux/$arch" \
    -f "$dockerfile" --target result --output "type=local,dest=$result" .
  test -f "$result/package-smoke-passed"
  # Not left lying around: the release step globs ./*.deb and ./*.rpm, and these arch-neutral
  # copies would ship as packages nobody can use.
  rm -f "package-smoke.$fmt"
}
smoke_pkg deb "whiskerless_${VERSION}_${ARCH}.deb"
smoke_pkg rpm "whiskerless-${VERSION}.${rpmarch}.rpm"

ls -l ./*"$ARCH"* ./*"$rpmarch"* "whiskerless-${raw}-linux-$suffix" 2>/dev/null || true
echo "$arch Linux artifacts built, signed, and smoked natively"
