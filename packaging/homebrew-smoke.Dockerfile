# Installs the rendered Homebrew formula from a local sdist inside linuxbrew and runs it, before
# the tap publishes anything (backlog #29 — the tap once published a formula no machine could
# install, and nothing noticed because nothing installed it). Same result-stage contract as the
# package smokes: the build fails unless the marker file exists.
#
# The build context must contain `formula-smoke-dist/` (holding the sdist under its real,
# versioned filename — Homebrew derives the formula version from the URL) beside `packaging/`.
# renovate: datasource=docker depName=homebrew/brew
FROM homebrew/brew:latest@sha256:b0072bfdebf5934ae24b93b44a1928a88057399b3283ffa0177bb86084fdedfd AS smoke

WORKDIR /work
COPY --chown=linuxbrew:linuxbrew packaging /work/packaging
COPY --chown=linuxbrew:linuxbrew formula-smoke-dist /work/dist
ARG TEST_TAG
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

RUN [ -z "$BREW_MIRROR" ] || { export HOMEBREW_ARTIFACT_DOMAIN="$BREW_MIRROR"; export HOMEBREW_CURL_RETRIES=8; export HOMEBREW_DOCKER_REGISTRY_TOKEN=QQ==; }; \
 brew update \
 && test -n "$TEST_TAG" \
 && bash packaging/test-homebrew-formula.sh "$TEST_TAG" /work/dist/whiskerless-*.tar.gz \
 && touch /home/linuxbrew/homebrew-smoke-passed

FROM scratch AS result
COPY --from=smoke /home/linuxbrew/homebrew-smoke-passed /homebrew-smoke-passed
