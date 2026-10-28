# Installs the exact .deb that is about to be published and runs it, on the architecture the runner
# already is — amd64 on Forgejo, arm64 on GitHub's native arm runner. A buildx target rather than a
# `docker run` because the Forgejo job is itself containerised, so a bind mount of the workspace
# never reaches the daemon.
#
# This proves install-and-run, not the glibc floor: since the build moved to a manylinux_2_28
# image, the build image IS the declared floor and no distro can sit between them. The floor is
# enforced statically by check-glibc-floor.py during the build instead.
# renovate: datasource=docker depName=ubuntu-26.04-current packageName=ubuntu
FROM ubuntu:26.04@sha256:0e73b71479e7bc5f006bca872e25c3cd680dc052a0116f90d63ae363537db0dd AS smoke

# The version the binary was frozen at; installed-smoke.sh checks the binary reports it.
ARG EXPECT_VERSION
COPY package-smoke.deb /tmp/package-smoke.deb
COPY packaging/test-linux-packages.sh /tmp/test-linux-packages.sh
COPY packaging/installed-smoke.sh /tmp/installed-smoke.sh

RUN test -n "$EXPECT_VERSION" \
 && /bin/bash /tmp/test-linux-packages.sh --inside-single apt "$EXPECT_VERSION" /tmp/package-smoke.deb \
 && touch /package-smoke-passed

FROM scratch AS result
COPY --from=smoke /package-smoke-passed /package-smoke-passed
