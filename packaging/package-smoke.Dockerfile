# Installs the exact .deb that is about to be published and runs it, on the architecture the runner
# already is — amd64 on Forgejo, arm64 on GitHub's native arm runner. A buildx target rather than a
# `docker run` because the Forgejo job is itself containerised, so a bind mount of the workspace
# never reaches the daemon.
#
# This proves install-and-run, not the glibc floor: since the build moved to a manylinux_2_28
# image, the build image IS the declared floor and no distro can sit between them. The floor is
# enforced statically by check-glibc-floor.py during the build instead.
# renovate: datasource=docker depName=ubuntu-26.04-current packageName=ubuntu
FROM ubuntu:26.04@sha256:513c074113a871b51a8d16ab445c88779d6452d937a164fb5cc479f32668a41d AS smoke

COPY package-smoke.deb /tmp/package-smoke.deb

RUN set -eux; \
    ldd --version | head -1; \
    apt-get update -qq >/dev/null; \
    apt-get install -y -qq /tmp/package-smoke.deb >/dev/null; \
    whiskerless --help > /dev/null; \
    whiskerless send --help > /dev/null; \
    touch /package-smoke-passed

FROM scratch AS result
COPY --from=smoke /package-smoke-passed /package-smoke-passed
