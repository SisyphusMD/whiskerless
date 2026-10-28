# The .rpm half of the pre-publish gate. Same contract as package-smoke.Dockerfile: install the
# exact artifact that is about to ship and run it, for whichever platform buildx is pointed at.
#
# The current RPM-family release is the install-and-run check, and it is the SAME image the install
# matrix already qualifies against — one Renovate identity for one image, rather than a second that
# moves on its own schedule. This cannot prove the glibc floor: since the build moved to a
# manylinux_2_28 image, the build image IS the declared floor and no distro can sit between them —
# check-glibc-floor.py enforces the floor statically during the build.
# renovate: datasource=docker depName=rocky-10-current packageName=rockylinux/rockylinux
FROM rockylinux/rockylinux:10@sha256:827d37bc128288ccf160ee318bb3cb92d591164cb217e92f8bc61e3982ae1834 AS smoke

# The version the binary was frozen at; installed-smoke.sh checks the binary reports it.
ARG EXPECT_VERSION
COPY package-smoke.rpm /tmp/package-smoke.rpm
COPY packaging/test-linux-packages.sh /tmp/test-linux-packages.sh
COPY packaging/installed-smoke.sh /tmp/installed-smoke.sh

RUN test -n "$EXPECT_VERSION" \
 && /bin/bash /tmp/test-linux-packages.sh --inside-single dnf "$EXPECT_VERSION" /tmp/package-smoke.rpm \
 && touch /package-smoke-passed

FROM scratch AS result
COPY --from=smoke /package-smoke-passed /package-smoke-passed
