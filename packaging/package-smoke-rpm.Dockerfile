# The .rpm half of the pre-publish gate. Same contract as package-smoke.Dockerfile: install the
# exact artifact that is about to ship and run it, for whichever platform buildx is pointed at.
#
# Rocky 9 is the RPM-family install-and-run check. It cannot prove the glibc floor: since the
# build moved to a manylinux_2_28 image, the build image IS the declared floor and no distro can
# sit between them — check-glibc-floor.py enforces the floor statically during the build.
# renovate: datasource=docker depName=rockylinux/rockylinux
FROM rockylinux/rockylinux:9.8.20260525.0@sha256:8101994123cf3d0a8fee517bee7f39e555c7d92bd2d9eb3303cc988a0eeed00f AS smoke

COPY package-smoke.rpm /tmp/package-smoke.rpm

RUN set -eux; \
    ldd --version | head -1; \
    dnf install -y -q /tmp/package-smoke.rpm >/dev/null; \
    whiskerless --help > /dev/null; \
    whiskerless send --help > /dev/null; \
    touch /package-smoke-passed

FROM scratch AS result
COPY --from=smoke /package-smoke-passed /package-smoke-passed
