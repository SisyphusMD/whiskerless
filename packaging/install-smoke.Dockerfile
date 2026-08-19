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
ARG TAG

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

# --- pipx, which the README offers for "CLI on PATH" ---------------------------------
FROM deb-base AS pipx
ARG V
RUN set -eux; apt-get install -y -qq pipx >/dev/null
RUN set -eux; \
    PYPI_V=$(printf '%s' "$V" | sed -E 's/-rc\.([0-9]+)$/rc\1/'); \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin \
      pipx install "whiskerless[ble]==${PYPI_V}" >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS pipx-result
COPY --from=pipx /passed /passed

# --- plain pip into a venv, the "library + BLE provisioning" line ---------------------
FROM deb-base AS pip
ARG V
RUN set -eux; apt-get install -y -qq python3 python3-venv >/dev/null
RUN set -eux; \
    PYPI_V=$(printf '%s' "$V" | sed -E 's/-rc\.([0-9]+)$/rc\1/'); \
    python3 -m venv /opt/w; \
    /opt/w/bin/pip install -q "whiskerless[ble]==${PYPI_V}"; \
    ln -s /opt/w/bin/whiskerless /usr/local/bin/whiskerless; \
    # The extra is the point of this line in the README, so prove it arrived
    # rather than only that the CLI runs.
    /opt/w/bin/python -c "import bleak"; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS pip-result
COPY --from=pip /passed /passed

# --- openSUSE, which takes the single .rpm rather than the repository ----------------
# zypper insists on verifying a repository index even with repo_gpgcheck=0, and the
# key that would satisfy it is Forgejo's — which the README deliberately does not ask
# anyone to trust. So this is the documented route: import OUR key, install the file.
FROM opensuse/leap:15.6 AS zypper
ARG V PV DL ARCH_RPM FORGE
RUN set -eux; zypper --non-interactive install -y curl openssl >/dev/null; command -v openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh
RUN set -eux; \
    rpm --import "$FORGE/SisyphusMD/whiskerless/raw/branch/main/packaging/whiskerless-signing-key.asc"; \
    curl -fsSL -o /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    # Not --allow-unsigned-rpm: the imported key has to be what makes this work,
    # or the test proves nothing about the signature.
    zypper --non-interactive install /tmp/w.rpm >/dev/null; \
    rpm -qi whiskerless | grep -qi "4bbacd5a6ff38564"; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS zypper-result
COPY --from=zypper /passed /passed

# --- provisioning, as far as a machine with no robot and no radio can take it --------
# The BLE re-provisioner is why this CLI exists, and until now nothing here ran it:
# every BLE test uses a fake transport, so the real bleak was never loaded by
# anything CI ran. That let a broken provisioner reach four release candidates —
# the detection callback took four parameters and bleak accepts exactly two, so
# every scan died on a TypeError the moment it started.
#
# No radio is needed to catch that. Reaching "scanning" proves the frozen bundle
# really carries the radio stack; failing as a SENTENCE proves the machine without
# Bluetooth gets told what is wrong instead of a stack trace.
FROM deb-base AS provision
ARG V DL ARCH_BIN
RUN set -eux; \
    curl -fsSL -o /usr/local/bin/whiskerless "$DL/whiskerless-${V}-linux-${ARCH_BIN}"; \
    chmod +x /usr/local/bin/whiskerless; \
    openssl req -x509 -newkey rsa:2048 -nodes -keyout /ca.key -out /ca.crt -days 2 \
      -subj "/CN=whiskerless provision smoke" >/dev/null 2>&1; \
    export WHISKERLESS_HOME=/store; \
    whiskerless setup --host 192.0.2.1 --ca /ca.crt --ca-key /ca.key </dev/null >/dev/null; \
    out=$(whiskerless provision --serial LR4C000000 --wifi-ssid ssid --wifi-pass pass \
            --dry-run --yes </dev/null 2>&1) && status=0 || status=$?; \
    printf '%s\n' "$out"; \
    # It has to have STARTED scanning: that is the line that only appears once
    # bleak has imported and the scanner has been constructed and accepted.
    printf '%s' "$out" | grep -qi "scanning for robots over BLE"; \
    # And it has to have failed like a program, not like a crash.
    if printf '%s' "$out" | grep -q "Traceback"; then \
      echo "provisioning failed with a stack trace, not a message"; exit 1; fi; \
    printf '%s' "$out" | grep -qi "no usable Bluetooth"; \
    [ "$status" -ne 0 ] || { echo "no Bluetooth here, so this must not report success"; exit 1; }; \
    touch /passed
FROM scratch AS provision-result
COPY --from=provision /passed /passed

# --- HACS, which is how the Home Assistant integration is actually installed ---------
# The whole check is packaging/hacs-smoke.sh; what it proves and why is documented
# there. Kept out of this file because a RUN cannot carry the explanation: a comment
# inside a line-continued RUN silently truncates the instruction.
FROM deb-base AS hacs
ARG V TAG FORGE
# build-essential is scaffolding, not a product requirement: a HACS user already
# HAS Home Assistant, and installing it here to load the integration against drags
# in a dependency with no aarch64 wheel (lru-dict), which would otherwise make this
# channel pass on one architecture and fail on the other for reasons that say
# nothing about whiskerless.
RUN set -eux; apt-get install -y -qq python3 python3-venv python3-dev build-essential >/dev/null
COPY packaging/hacs-smoke.sh /hacs-smoke.sh
RUN set -eux; bash /hacs-smoke.sh "$TAG" "$V" "$FORGE"; touch /passed
FROM scratch AS hacs-result
COPY --from=hacs /passed /passed
