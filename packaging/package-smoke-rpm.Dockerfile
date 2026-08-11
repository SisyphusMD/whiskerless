# The .rpm half of the pre-publish gate. Same contract as package-smoke.Dockerfile: install the
# exact artifact that is about to ship and run it, for whichever platform buildx is pointed at.
#
# Rocky 9 is the distro this is proved on because its glibc sits above the declared 2.28 floor and
# below the build image's — the window where a binary frozen against the wrong libc installs
# cleanly and then refuses to start.
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
