# syntax=docker/dockerfile:1
# Every Linux install channel we publish, installed from the PUBLISHED artifacts
# and then run, one buildx target per channel.
#
# A Dockerfile rather than the obvious `docker run`, because on Forgejo the job
# itself runs in a container and a bind mount of the workspace is invisible to the
# daemon. BuildKit streams its context instead, so there is nothing to mount — and
# it is the pattern package-smoke.Dockerfile established.
#
# Built for the architecture the runner already is, never emulated: the amd64 legs
# run on Forgejo and the arm64 legs on GitHub's native arm runner, and
# install-matrix-arch.sh refuses to run when host and target disagree.
#
# Each channel ends by touching /passed and exporting it through a `scratch`
# stage, so the workflow asserts a FILE rather than trusting an exit code that
# buildx may have cached.

# Qualification bases are digest-pinned, not tag-tracked: a tag moves under you and the
# matrix silently starts qualifying against a different distro snapshot than the one it
# reported green on. Renovate bumps these deliberately. Same discipline, and the same two
# digests, as dreame-valetudo's package matrix.

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
ARG GH_DL
ARG GH_PV

# --- Debian-family base -------------------------------------------------------------
# openssl is verified present rather than assumed: installed-smoke.sh SKIPS its
# certificate half without it, which is most of what it proves.
# A mirror that drops a connection mid-fetch is not this project failing, but apt treats it as
# fatal and the whole install leg goes red for it — observed against ports.ubuntu.com. Retries are
# set as apt POLICY rather than around each call: every derived stage inherits the file, so a new
# leg cannot forget it. This is not laundering a flaky test, it is making a network fetch survive
# the network; a package that genuinely does not install still fails.
# renovate: datasource=docker depName=debian-13-current packageName=debian
FROM debian:13-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132 AS deb-base
RUN set -eux; \
    echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/99retries; \
    apt-get update -qq >/dev/null; \
    apt-get install -y -qq curl ca-certificates openssl >/dev/null; \
    command -v openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch

# --- a downloaded .deb, installed by hand — still a documented route -----------------
FROM deb-base AS deb-file
ARG V PV DL ARCH_DEB
RUN set -eux; \
    /fetch /tmp/w.deb "$DL/whiskerless_${PV}_${ARCH_DEB}.deb"; \
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
    /fetch /etc/apt/keyrings/w.asc "$FORGE/api/packages/SisyphusMD/debian/repository.key"; \
    echo "deb [signed-by=/etc/apt/keyrings/w.asc] $FORGE/api/packages/SisyphusMD/debian $DIST main" \
      > /etc/apt/sources.list.d/w.list; \
    echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/99retries; \
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
    /fetch /usr/local/bin/whiskerless "$DL/whiskerless-${V}-linux-${ARCH_BIN}"; \
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
    curl -LsSf --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 10 -o /tmp/uv-install.sh https://astral.sh/uv/install.sh; \
    sh /tmp/uv-install.sh >/dev/null 2>&1; \
    PYPI_V=$(printf '%s' "$V" | sed -E 's/-rc\.([0-9]+)$/rc\1/'); \
    printf '#!/bin/sh\nexport PATH="$HOME/.local/bin:$PATH"\nexec uvx -q --from '"'"'whiskerless[ble]==%s'"'"' whiskerless "$@"\n' \
      "$PYPI_V" > /usr/local/bin/whiskerless; \
    chmod +x /usr/local/bin/whiskerless; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS pypi-uvx-result
COPY --from=pypi-uvx /passed /passed

# --- RPM-family base ----------------------------------------------------------------
# renovate: datasource=docker depName=rocky-9-compat packageName=rockylinux/rockylinux
FROM rockylinux/rockylinux:9@sha256:8101994123cf3d0a8fee517bee7f39e555c7d92bd2d9eb3303cc988a0eeed00f AS rpm-base
RUN set -eux; \
    dnf install -y -q openssl >/dev/null; \
    command -v openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch

FROM rpm-base AS rpm-file
ARG V PV DL ARCH_RPM
RUN set -eux; \
    /fetch /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    dnf install -y -q /tmp/w.rpm >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS rpm-file-result
COPY --from=rpm-file /passed /passed

FROM rpm-base AS dnf-repo
ARG V REPOFILE FORGE TAG
RUN set -eux; \
    /fetch /etc/yum.repos.d/sisyphusmd.repo \
      "$FORGE/SisyphusMD/whiskerless/raw/tag/$TAG/packaging/$REPOFILE"; \
    dnf install -y -q whiskerless >/dev/null; \
    rpm -qi whiskerless | grep -qi "cce50015d058e9bf"; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS dnf-repo-result
COPY --from=dnf-repo /passed /passed

# --- the .deb's LIFECYCLE, not just its install ---------------------------------------
# Everything else here proves a clean install. Nothing proved the three things that actually bite
# after one: that the native version sorts where the release process assumes it does, that a
# reinstall is idempotent, and that removal takes the package's files with it.
#
# The ordering assertion uses real dpkg on the real package metadata. `0.2.0~rc.35` must sort ABOVE
# the previous candidate and BELOW the stable it is a candidate for — that is what makes rc→stable
# an upgrade rather than a downgrade, and it is a property of nFPM's semver normalisation that no
# test here exercised.
FROM deb-base AS deb-lifecycle
ARG V PV DL ARCH_DEB
RUN set -eux; \
    /fetch /tmp/w.deb "$DL/whiskerless_${PV}_${ARCH_DEB}.deb"; \
    apt-get install -y -qq /tmp/w.deb >/dev/null; \
    installed=$(dpkg-query -W -f='${Version}' whiskerless); \
    [ "$installed" = "$PV" ] || { echo "installed $installed, expected $PV"; exit 1; }; \
    stable=${PV%%\~*}; \
    case "$PV" in \
      *\~rc.*) \
        prev="${PV%.*}.$(( ${PV##*.} - 1 ))"; \
        dpkg --compare-versions "$prev" lt "$installed" \
          || { echo "$installed does not sort above the previous candidate $prev"; exit 1; }; \
        dpkg --compare-versions "$installed" lt "$stable" \
          || { echo "$installed does not sort below stable $stable — rc->stable would be a downgrade"; exit 1; }; \
        ;; \
    esac; \
    apt-get install -y -qq --reinstall /tmp/w.deb >/dev/null; \
    [ "$(dpkg-query -W -f='${Version}' whiskerless)" = "$PV" ]; \
    bash /smoke.sh whiskerless "$V"; \
    apt-get remove -y -qq whiskerless >/dev/null; \
    ! command -v whiskerless >/dev/null || { echo "removal left the binary behind"; exit 1; }; \
    touch /passed
FROM scratch AS deb-lifecycle-result
COPY --from=deb-lifecycle /passed /passed

# --- the .deb as GITHUB serves it — a different origin AND a different filename --------
# Forgejo is canonical, and every other target here downloads from it. GitHub is still a PROMISED
# origin — it is where the README sends people for the .pkg, and it is the only place HACS installs
# from — and GitHub rewrites `~` to `.` in the stored asset name, so the file those users fetch has
# a name no other test ever constructs. A mirror is not evidence for the origin it mirrors: if the
# GitHub copy were missing, misnamed or truncated, nothing here would have said so.
FROM deb-base AS deb-file-github
ARG V GH_DL GH_PV ARCH_DEB
RUN set -eux; \
    /fetch /tmp/w.deb "$GH_DL/whiskerless_${GH_PV}_${ARCH_DEB}.deb"; \
    apt-get install -y -qq /tmp/w.deb >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS deb-file-github-result
COPY --from=deb-file-github /passed /passed

# --- the same .deb, on the OTHER distros the floor promises -------------------------
# Channel breadth was here; distro depth was not. A package that installs on Debian 13 can still
# fail on the oldest release the glibc floor claims, and nothing noticed. Digests are the ones
# dreame-valetudo pins, deliberately: both projects then qualify against identical snapshots.
# renovate: datasource=docker depName=debian-12-compat packageName=debian
FROM debian:12-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171 AS deb-file-floor
ARG V PV DL ARCH_DEB
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
RUN set -eux; \
    echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/99retries; \
    apt-get update -qq >/dev/null; \
    apt-get install -y -qq curl ca-certificates openssl >/dev/null; \
    /fetch /tmp/w.deb "$DL/whiskerless_${PV}_${ARCH_DEB}.deb"; \
    apt-get install -y -qq /tmp/w.deb >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS deb-file-floor-result
COPY --from=deb-file-floor /passed /passed

# renovate: datasource=docker depName=ubuntu-22.04-compat packageName=ubuntu
FROM ubuntu:22.04@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc AS deb-file-ubuntu-floor
ARG V PV DL ARCH_DEB
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
RUN set -eux; \
    echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/99retries; \
    apt-get update -qq >/dev/null; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates openssl >/dev/null; \
    /fetch /tmp/w.deb "$DL/whiskerless_${PV}_${ARCH_DEB}.deb"; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq /tmp/w.deb >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS deb-file-ubuntu-floor-result
COPY --from=deb-file-ubuntu-floor /passed /passed

# renovate: datasource=docker depName=ubuntu-26.04-current packageName=ubuntu
FROM ubuntu:26.04@sha256:2260313b31c8c011cd2eebe728008efac1b3982be73eb71348ea2648d2c0e09b AS deb-file-ubuntu
ARG V PV DL ARCH_DEB
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
RUN set -eux; \
    echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/99retries; \
    apt-get update -qq >/dev/null; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates openssl >/dev/null; \
    /fetch /tmp/w.deb "$DL/whiskerless_${PV}_${ARCH_DEB}.deb"; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq /tmp/w.deb >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS deb-file-ubuntu-result
COPY --from=deb-file-ubuntu /passed /passed

# --- the same .rpm, on the oldest and newest RPM distros the floor promises ----------
# One .rpm ships for every RPM distro, so installing it on exactly one of them proves the least
# it could. Rocky 8 is the floor, Rocky 10 the current release of the same family, and Fedora a
# separate lineage; a package that installs on Rocky 9 can still fail on any of them.
# renovate: datasource=docker depName=rocky-8-compat packageName=rockylinux/rockylinux
FROM rockylinux/rockylinux:8@sha256:e8a49c5403b687db05d4d67333fa45808fbe74f36e683cec7abb1f7d0f2338c6 AS rpm-file-floor
ARG V PV DL ARCH_RPM
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
RUN set -eux; \
    dnf install -y -q openssl >/dev/null; \
    /fetch /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    dnf install -y -q /tmp/w.rpm >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS rpm-file-floor-result
COPY --from=rpm-file-floor /passed /passed

# renovate: datasource=docker depName=rocky-10-current packageName=rockylinux/rockylinux
FROM rockylinux/rockylinux:10@sha256:827d37bc128288ccf160ee318bb3cb92d591164cb217e92f8bc61e3982ae1834 AS rpm-file-current
ARG V PV DL ARCH_RPM
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
RUN set -eux; \
    dnf install -y -q openssl >/dev/null; \
    /fetch /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    dnf install -y -q /tmp/w.rpm >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS rpm-file-current-result
COPY --from=rpm-file-current /passed /passed

# renovate: datasource=docker depName=fedora-44-current packageName=fedora
FROM fedora:44@sha256:6c75d5bf57cb0fa5aa4b92c6a83c86c791644496d9ac230de7711f5b8ec3b898 AS fedora-base
RUN set -eux; dnf install -y -q openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch

FROM fedora-base AS rpm-file-fedora
ARG V PV DL ARCH_RPM
RUN set -eux; \
    /fetch /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    dnf install -y -q /tmp/w.rpm >/dev/null; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS rpm-file-fedora-result
COPY --from=rpm-file-fedora /passed /passed

# dnf5 is a reimplementation rather than a new version of dnf: it parses .repo files and enforces
# gpgcheck in its own code, so the leg above proves nothing about it. Fedora 41 onward ships it as
# `dnf`, which makes it the repository client a current-Fedora user actually gets.
FROM fedora-base AS dnf5-repo
ARG V REPOFILE FORGE TAG
RUN set -eux; \
    dnf --version | head -1 | grep -q '^dnf5 '; \
    /fetch /etc/yum.repos.d/sisyphusmd.repo \
      "$FORGE/SisyphusMD/whiskerless/raw/tag/$TAG/packaging/$REPOFILE"; \
    dnf install -y -q whiskerless >/dev/null; \
    rpm -qi whiskerless | grep -qi "cce50015d058e9bf"; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS dnf5-repo-result
COPY --from=dnf5-repo /passed /passed

# --- a poured Homebrew bottle -------------------------------------------------------
# renovate: datasource=docker depName=homebrew/brew
FROM homebrew/brew:latest@sha256:b0072bfdebf5934ae24b93b44a1928a88057399b3283ffa0177bb86084fdedfd AS bottle-pour
ARG V FORGE
# Injected by the caller, not hardcoded: this also builds on GitHub's hosted runners, which are not
# on the network the mirror lives on. Empty means upstream. It must be ARTIFACT_DOMAIN and not
# BOTTLE_DOMAIN - the latter makes Homebrew ask for a legacy flat file the registry does not serve,
# so every bottle 404s and falls back, mirroring nothing while looking configured.
#
# The retry count rises with it, and only with it. A pull-through registry buffers an entry from
# upstream before it sends any of it, so one nobody has fetched yet goes quiet while it syncs:
# measured at about 21s from a runner, against the roughly 7s Homebrew's default three tries allow.
# Each further try also gives the registry longer to finish, so the same fetch succeeds once warm -
# a 170MB bottle already synced serves in about 2s. Upstream needs none of this: it streams
# immediately.
#
# The token is what makes a mirror MISS survivable, and is the reason this was reverted once
# without it. Homebrew normally sends `Authorization: Bearer QQ==`, the anonymous credential for
# public GitHub Packages, but it suppresses that header once ARTIFACT_DOMAIN is set with no
# registry credentials — so a bottle the mirror cannot serve falls back to ghcr.io bare and gets a
# 401 rather than the bottle. QQ== is that same anonymous bearer, restored explicitly; ghcr.io
# answers 200 for it and the mirror ignores it, so the fallback works again from both ends.
ARG BREW_MIRROR=
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
# No USER juggling: this image already runs as `linuxbrew` (brew refuses to run as
# root), so the marker goes in that user's HOME rather than at / where it could
# not be written.
RUN set -eux; \
    [ -z "$BREW_MIRROR" ] || { export HOMEBREW_ARTIFACT_DOMAIN="$BREW_MIRROR"; export HOMEBREW_CURL_RETRIES=8; export HOMEBREW_DOCKER_REGISTRY_TOKEN=QQ==; }; \
    before=$(brew list --formula | grep -cE '^rust$|^llvm$|^pkgconf$' || true); \
    brew update --quiet >/dev/null 2>&1; \
    brew tap sisyphusmd/tap "$FORGE/SisyphusMD/homebrew-tap.git" >/dev/null 2>&1; \
    if brew commands 2>/dev/null | tr ' ' '\n' | grep -qx trust; then brew trust sisyphusmd/tap; fi; \
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
    /fetch /usr/local/bin/whiskerless "$DL/whiskerless-${V}-linux-${ARCH_BIN}"; \
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
#
# Two ends, the same way the deb and rpm channels carry a floor and a current: an .rpm that installs
# on Leap 16 can still fail on 15.6, and nothing else here would notice. Both stages below are
# identical apart from the base image. The sibling project runs the same pair, under the same names.
# renovate: datasource=docker depName=opensuse-leap-16-current packageName=opensuse/leap
FROM opensuse/leap:16.0@sha256:f239b4819f4dd322d99509f1b5b14f2107bf23857f9ccd3c14333f0928a2bcc6 AS zypper
ARG V PV DL ARCH_RPM FORGE
RUN set -eux; zypper --non-interactive install -y curl openssl >/dev/null; command -v openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
RUN set -eux; \
    rpm --import "$FORGE/SisyphusMD/whiskerless/raw/branch/main/packaging/sisyphusmd-signing-key.asc"; \
    /fetch /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    # Not --allow-unsigned-rpm: the imported key has to be what makes this work,
    # or the test proves nothing about the signature.
    zypper --non-interactive install /tmp/w.rpm >/dev/null; \
    rpm -qi whiskerless | grep -qi "cce50015d058e9bf"; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS zypper-result
COPY --from=zypper /passed /passed

# renovate: datasource=docker depName=opensuse-leap-15.6-compat packageName=opensuse/leap
FROM opensuse/leap:15.6@sha256:79be7751205ea84559990fb76b1bec71e38d6fad41c70a4f6c921b803b58f421 AS zypper-floor
ARG V PV DL ARCH_RPM FORGE
RUN set -eux; zypper --non-interactive install -y curl openssl >/dev/null; command -v openssl >/dev/null
COPY packaging/installed-smoke.sh /smoke.sh
COPY packaging/fetch.sh /fetch
RUN set -eux; \
    rpm --import "$FORGE/SisyphusMD/whiskerless/raw/branch/main/packaging/sisyphusmd-signing-key.asc"; \
    /fetch /tmp/w.rpm "$DL/whiskerless-${PV}.${ARCH_RPM}.rpm"; \
    # Not --allow-unsigned-rpm: the imported key has to be what makes this work,
    # or the test proves nothing about the signature.
    zypper --non-interactive install /tmp/w.rpm >/dev/null; \
    rpm -qi whiskerless | grep -qi "cce50015d058e9bf"; \
    bash /smoke.sh whiskerless "$V"; \
    touch /passed
FROM scratch AS zypper-floor-result
COPY --from=zypper-floor /passed /passed

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
    /fetch /usr/local/bin/whiskerless "$DL/whiskerless-${V}-linux-${ARCH_BIN}"; \
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

# --- the two modes where whiskerless does NOT hold the signing key ------------------
# The `provision` channel above only ever exercises `mutual`, which is the one mode
# that needs nothing handed to it. `supplied` and `anonymous` are the modes somebody
# reaches for BECAUSE their CA lives somewhere this machine cannot go, and they are
# reachable only through flags — so nothing but a channel like this proves the shipped
# binary can do them at all. Both the acceptances and the refusals are asserted: a
# mode that quietly accepts what it documents as contradictory is the failure the
# stored `auth` field exists to prevent.
FROM deb-base AS auth-modes
ARG V DL ARCH_BIN
RUN set -eux; \
    /fetch /usr/local/bin/whiskerless "$DL/whiskerless-${V}-linux-${ARCH_BIN}"; \
    chmod +x /usr/local/bin/whiskerless; \
    openssl req -x509 -newkey rsa:2048 -nodes -keyout /ca.key -out /ca.crt -days 2 \
      -subj "/CN=whiskerless auth smoke" >/dev/null 2>&1; \
    for who in client:whiskerless-cli robot:LR4C000000; do \
      name="${who%%:*}"; cn="${who##*:}"; \
      openssl req -newkey rsa:2048 -nodes -keyout "/$name.key" -out "/$name.csr" \
        -subj "/CN=$cn" >/dev/null 2>&1; \
      openssl x509 -req -in "/$name.csr" -CA /ca.crt -CAkey /ca.key -CAcreateserial \
        -out "/$name.crt" -days 1 >/dev/null 2>&1; \
    done; \
    # A robot certificate from an authority this store was never given.
    openssl req -x509 -newkey rsa:2048 -nodes -keyout /other.key -out /other.crt -days 2 \
      -subj "/CN=somebody else" >/dev/null 2>&1; \
    openssl req -newkey rsa:2048 -nodes -keyout /stray.key -out /stray.csr \
      -subj "/CN=LR4C000000" >/dev/null 2>&1; \
    openssl x509 -req -in /stray.csr -CA /other.crt -CAkey /other.key -CAcreateserial \
      -out /stray.crt -days 1 >/dev/null 2>&1; \
    \
    # --- supplied: identities are issued elsewhere and handed over ----------------
    export WHISKERLESS_HOME=/supplied; \
    whiskerless setup --host 192.0.2.1 --auth supplied --ca /ca.crt \
      --client-cert /client.crt --client-key /client.key </dev/null >/dev/null; \
    # The whole point of the mode: the signing key must not be on this machine.
    [ ! -f /supplied/ca/ca.key ] || { echo "supplied mode filed a signing key"; exit 1; }; \
    grep -q '"auth": "supplied"' /supplied/broker.json; \
    out=$(whiskerless provision --serial LR4C000000 --wifi-ssid ssid --wifi-pass pass \
            --robot-cert /robot.crt --robot-key /robot.key --dry-run --yes </dev/null 2>&1) \
            && rc=0 || rc=$?; \
    printf '%s\n' "$out"; \
    # Reaching the scan proves the supplied pair got through validation and the
    # frozen bundle carries the radio stack, exactly as in the `provision` channel.
    printf '%s' "$out" | grep -qi "scanning for robots over BLE"; \
    if printf '%s' "$out" | grep -q "Traceback"; then \
      echo "supplied-mode provisioning crashed instead of failing"; exit 1; fi; \
    [ "$rc" -ne 0 ] || { echo "no Bluetooth here, so this must not report success"; exit 1; }; \
    \
    # --- anonymous: the robot keeps the certificate it shipped with ---------------
    export WHISKERLESS_HOME=/anon; \
    whiskerless setup --host 192.0.2.1 --auth anonymous --ca /ca.crt </dev/null >/dev/null; \
    grep -q '"auth": "anonymous"' /anon/broker.json; \
    out=$(whiskerless provision --serial LR4C000000 --wifi-ssid ssid --wifi-pass pass \
            --dry-run --yes </dev/null 2>&1) && rc=0 || rc=$?; \
    printf '%s' "$out" | grep -qi "scanning for robots over BLE"; \
    # A crash exits non-zero too, so the status check alone would accept one.
    if printf '%s' "$out" | grep -q "Traceback"; then \
      echo "anonymous-mode provisioning crashed instead of failing"; exit 1; fi; \
    [ "$rc" -ne 0 ] || { echo "no Bluetooth here, so this must not report success"; exit 1; }; \
    \
    # --- and the refusals, which are the half a passing run can hide --------------
    export WHISKERLESS_HOME=/contradiction; \
    whiskerless setup --host 192.0.2.1 --auth supplied --ca /ca.crt --ca-key /ca.key \
      </dev/null >/tmp/o1 2>&1 && { echo "--ca-key was accepted in supplied mode"; exit 1; } || true; \
    grep -q "contradicts" /tmp/o1; \
    export WHISKERLESS_HOME=/anon; \
    whiskerless provision --serial LR4C000000 --wifi-ssid ssid --wifi-pass pass \
      --robot-cert /robot.crt --robot-key /robot.key --dry-run --yes \
      </dev/null >/tmp/o2 2>&1 && { echo "a robot certificate was accepted in anonymous mode"; exit 1; } || true; \
    grep -qi "anonymous" /tmp/o2; \
    export WHISKERLESS_HOME=/supplied; \
    whiskerless provision --serial LR4C000000 --wifi-ssid ssid --wifi-pass pass \
      --robot-cert /stray.crt --robot-key /stray.key --dry-run --yes \
      </dev/null >/tmp/o3 2>&1 && { echo "a foreign robot certificate was accepted"; exit 1; } || true; \
    grep -q "not signed by the CA" /tmp/o3; \
    touch /passed
FROM scratch AS auth-modes-result
COPY --from=auth-modes /passed /passed

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
