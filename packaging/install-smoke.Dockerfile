# syntax=docker/dockerfile:1
# Every Linux install channel we publish, installed from the PUBLISHED artifacts
# and then run, one buildx target per channel.
#
# A Dockerfile rather than the obvious `docker run`, for the two reasons
# publish.yml already hit on this runner: a plain `docker run --platform arm64`
# dies with `exec format error` because the host has no usable binfmt, and a bind
# mount of the workspace is invisible to the daemon because the job itself runs
# in a container. BuildKit carries its own QEMU and streams its context, so both
# problems go away — and it is the pattern package-smoke.Dockerfile established.
#
# Each channel ends by touching /passed and exporting it through a `scratch`
# stage, so the workflow asserts a FILE rather than trusting an exit code that
# buildx may have cached.

ARG V
ARG PV
ARG DL
ARG DIST
ARG REPOFILE
ARG FORGE
ARG ARCH_DEB
ARG ARCH_RPM
ARG ARCH_BIN

# --- Debian-family base -------------------------------------------------------------
# openssl is verified present rather than assumed: installed-smoke.sh SKIPS its
# certificate half without it, which is most of what it proves.
FROM debian:13-slim AS deb-base
RUN set -eux; \
    apt-get update -qq >/dev/null; \
    apt-get install -y -qq curl ca-certificates openssl >/dev/null; \
    command -v openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh

# --- a downloaded .deb, installed by hand — still a documented route -----------------
FROM deb-base AS deb-file
ARG V PV DL ARCH_DEB
RUN set -eux; \
    curl -fsSL -o /tmp/w.deb "$DL/whiskerless_${PV}_${ARCH_DEB}.deb"; \
    apt-get install -y -qq /tmp/w.deb >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS deb-file-result
COPY --from=deb-file /passed /passed

# --- the apt repository, which is how most people should be installing ---------------
FROM deb-base AS apt-repo
ARG V DIST FORGE
RUN set -eux; \
    install -d /etc/apt/keyrings; \
    curl -fsSL "$FORGE/api/packages/SisyphusMD/debian/repository.key" -o /etc/apt/keyrings/w.asc; \
    echo "deb [signed-by=/etc/apt/keyrings/w.asc] $FORGE/api/packages/SisyphusMD/debian $DIST main" \
      > /etc/apt/sources.list.d/w.list; \
    apt-get update -qq >/dev/null; \
    apt-get install -y -qq whiskerless >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS apt-repo-result
COPY --from=apt-repo /passed /passed

# --- the frozen binary, on an image with no Python at all — the point of it ----------
FROM deb-base AS raw-binary
ARG V DL ARCH_BIN
RUN set -eux; \
    curl -fsSL -o /usr/local/bin/whiskerless "$DL/whiskerless-${V}-linux-${ARCH_BIN}"; \
    chmod +x /usr/local/bin/whiskerless; \
    if command -v python3 >/dev/null; then \
      echo "this image has python — the test is not proving what it claims"; exit 1; fi; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS raw-binary-result
COPY --from=raw-binary /passed /passed

# --- PyPI, through uvx, the way the README offers it --------------------------------
FROM deb-base AS pypi-uvx
ARG V
RUN set -eux; \
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; \
    PYPI_V=$(printf '%s' "$V" | sed -E 's/-rc\.([0-9]+)$/rc\1/'); \
    printf '#!/bin/sh\nexport PATH="$HOME/.local/bin:$PATH"\nexec uvx -q --from '"'"'whiskerless[ble]==%s'"'"' whiskerless "$@"\n' \
      "$PYPI_V" > /usr/local/bin/whiskerless; \
    chmod +x /usr/local/bin/whiskerless; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS pypi-uvx-result
COPY --from=pypi-uvx /passed /passed

# --- RPM-family base ----------------------------------------------------------------
FROM rockylinux/rockylinux:9 AS rpm-base
RUN set -eux; \
    dnf install -y -q openssl >/dev/null; \
    command -v openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh

FROM rpm-base AS rpm-file
ARG V PV DL ARCH_RPM
RUN set -eux; \
    curl -fsSL -o /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    dnf install -y -q /tmp/w.rpm >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS rpm-file-result
COPY --from=rpm-file /passed /passed

FROM rpm-base AS dnf-repo
ARG V REPOFILE FORGE
RUN set -eux; \
    curl -fsSL "$FORGE/SisyphusMD/whiskerless/raw/branch/main/packaging/$REPOFILE" \
      -o /etc/yum.repos.d/whiskerless.repo; \
    dnf install -y -q whiskerless >/dev/null; \
    rpm -qi whiskerless | grep -qi "4bbacd5a6ff38564"; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS dnf-repo-result
COPY --from=dnf-repo /passed /passed

# --- a poured Homebrew bottle -------------------------------------------------------
# renovate: datasource=docker depName=homebrew/brew
FROM homebrew/brew:latest@sha256:b0072bfdebf5934ae24b93b44a1928a88057399b3283ffa0177bb86084fdedfd AS bottle-pour
ARG V FORGE
COPY packaging/installed-smoke.sh /smoke.sh
# No USER juggling: this image already runs as `linuxbrew` (brew refuses to run as
# root), so the marker goes in that user's HOME rather than at / where it could
# not be written.
RUN set -eux; \
    before=$(brew list --formula | grep -cE '^rust$|^llvm$|^pkgconf$' || true); \
    brew update --quiet >/dev/null 2>&1; \
    brew tap sisyphusmd/tap "$FORGE/SisyphusMD/homebrew-tap.git" >/dev/null 2>&1; \
    case "$V" in *-rc.*) formula=whiskerless-rc ;; *) formula=whiskerless ;; esac; \
    brew install "sisyphusmd/tap/$formula" > /tmp/i.log 2>&1 || { tail -20 /tmp/i.log; exit 1; }; \
    grep -qi "pouring whiskerless" /tmp/i.log \
      || { echo "did not pour:"; grep -iE 'building|installing' /tmp/i.log | head -5; exit 1; }; \
    after=$(brew list --formula | grep -cE '^rust$|^llvm$|^pkgconf$' || true); \
    [ "$after" -le "$before" ] \
      || { echo "build-only deps appeared ($before -> $after) — it built from source"; exit 1; }; \
    bash /smoke.sh "$(brew --prefix)/bin/whiskerless" "$V"; \
    touch "$HOME/passed"
FROM scratch AS bottle-pour-result
COPY --from=bottle-pour /home/linuxbrew/passed /passed

# --- a real broker, over TLS, with certificates whiskerless issued itself ------------
# The one channel that is not an install: it proves the SHIPPED binary can still
# hold a TLS session against a `require_certificate` broker and decode what a
# robot sends. mosquitto is a local process here, so this needs no daemon and no
# published port — which is what lets it run on both arches.
FROM deb-base AS broker
ARG V DL ARCH_BIN
RUN set -eux; apt-get install -y -qq mosquitto mosquitto-clients >/dev/null
COPY packaging/broker-smoke.sh /broker-smoke.sh
COPY tests/integration/fixtures/lr4_state.json /lr4_state.json
RUN set -eux; \
    curl -fsSL -o /usr/local/bin/whiskerless "$DL/whiskerless-${V}-linux-${ARCH_BIN}"; \
    chmod +x /usr/local/bin/whiskerless; \
    bash /broker-smoke.sh /usr/local/bin/whiskerless /lr4_state.json; \
    touch /passed
FROM scratch AS broker-result
COPY --from=broker /passed /passed
