# Builds the self-contained whiskerless binary for the NATIVE platform, then exports just that
# binary. Driven by build-linux-arch.sh through buildx, which both forges call: amd64 on Forgejo,
# arm64 on GitHub's native arm runner. `--platform` names the architecture the host already is and
# that script refuses the mismatch, so this never runs under emulation. buildx rather than
# `docker run` because the Forgejo job is itself containerised and a bind mount of the workspace
# does not reach the daemon. nfpm packages the exported binary into the .deb/.rpm OUTSIDE this
# build (nfpm is arch-independent and stays on its own pinned-image path).
#
# CPython is built from source with --enable-shared rather than taken from /opt/python. manylinux
# ships only STATIC interpreters — Py_ENABLE_SHARED is 0 for every one of 3.9 through 3.15 — and
# PyInstaller refuses to freeze without a shared libpython. Using the bundled ones is what broke
# v0.2.0-rc.4 and rc.5.
ARG PYTHON_BUILD_IMAGE=scratch
FROM ${PYTHON_BUILD_IMAGE} AS build
ARG PYINSTALLER
ARG PYTHON_VERSION
ARG PYTHON_SHA256
ENV PATH="/opt/whiskerless-python/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/whiskerless-python/lib" \
    PIP_ROOT_USER_ACTION=ignore
# CI points dnf at the NAS artifact cache; empty keeps the image's own mirrorlists. This stage
# is discarded after export, so the repo files need no restoring.
ARG DNF_MIRROR=
RUN if [ -n "$DNF_MIRROR" ]; then \
      sed -i -e 's|^mirrorlist=|#mirrorlist=|' \
        -e "s|^# *baseurl=https://repo.almalinux.org|baseurl=${DNF_MIRROR}/repo.almalinux.org|" /etc/yum.repos.d/almalinux*.repo \
   && sed -i -e 's|^metalink=|#metalink=|' \
        -e "s|^#baseurl=https://download.example/pub/epel|baseurl=${DNF_MIRROR}/dl.fedoraproject.org/pub/epel|" /etc/yum.repos.d/epel*.repo; \
    fi \
 && dnf install -y -q make zlib-devel openssl-devel bzip2-devel libffi-devel xz-devel \
      sqlite-devel readline-devel ncurses-devel \
 && dnf clean all
# Retried in the shell rather than with curl --retry, for the reason packaging/fetch.sh gives:
# --retry classifies neither a name-resolution failure nor a reset mid-transfer as transient,
# and those are the shapes this actually fails in. The digest check below is unchanged, so no
# repeat can smuggle in different bytes; the partial file is removed so it cannot be reused.
RUN attempt=1; \
    until curl -fsSL --connect-timeout 10 --max-time 600 \
          "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz" \
          -o /tmp/python.tar.xz; do \
      [ "$attempt" -ge 5 ] && { echo "python.org unreachable after $attempt attempts" >&2; exit 1; }; \
      rm -f /tmp/python.tar.xz; sleep $((attempt * 3)); attempt=$((attempt + 1)); \
    done \
 && printf '%s  %s\n' "$PYTHON_SHA256" /tmp/python.tar.xz | sha256sum -c - \
 && tar -xJf /tmp/python.tar.xz -C /tmp \
 && cd "/tmp/Python-${PYTHON_VERSION}" \
 && ./configure --prefix=/opt/whiskerless-python --enable-shared --with-ensurepip=install \
 && make -j4 \
 && make install \
 && test "$(/opt/whiskerless-python/bin/python3 -c 'import platform; print(platform.python_version())')" \
      = "$PYTHON_VERSION"
# CI points this at the NAS artifact cache; the default keeps the image buildable anywhere.
ARG PIP_INDEX_URL=https://pypi.org/simple/
RUN python3 -m pip install --quiet "pyinstaller==${PYINSTALLER}"
WORKDIR /w
COPY . /w
# --collect-all for both radio/broker libraries: PyInstaller's static analysis misses bleak's
# per-platform backend imports and aiomqtt's paho plumbing, and a missing hidden import fails at
# run time rather than build time. The --help calls below are what catch that: they exercise the
# whole import graph the CLI touches on startup, on the architecture the binary is actually for.
RUN python3 -m pip install --quiet ".[ble]" \
 && python3 -m PyInstaller --onefile --name whiskerless \
      --collect-all bleak --collect-all aiomqtt packaging/launcher.py \
 && python3 packaging/check-glibc-floor.py "$(cat packaging/glibc-floor.txt)" /w/dist/whiskerless \
 && /w/dist/whiskerless --help > /dev/null \
 && /w/dist/whiskerless send --help > /dev/null

# Export stage: BuildKit writes just the native binary to the --output dir (a client-side stream,
# so it is not subject to the DinD workspace-visibility problem either).
FROM scratch AS export
COPY --from=build /w/dist/whiskerless /whiskerless
