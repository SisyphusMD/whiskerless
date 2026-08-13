# Installs the exact .deb that is about to be published and runs it, for whichever platform buildx
# is pointed at. The arm64 leg is the reason this is a buildx target rather than a `docker run`:
# BuildKit's builder carries QEMU and this runner's host binfmt does not.
#
# This proves install-and-run, not the glibc floor: since the build moved to a manylinux_2_28
# image, the build image IS the declared floor and no distro can sit between them. The floor is
# enforced statically by check-glibc-floor.py during the build instead.
# renovate: datasource=docker depName=ubuntu-26.04-current packageName=ubuntu
FROM ubuntu:26.04@sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03 AS smoke

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
