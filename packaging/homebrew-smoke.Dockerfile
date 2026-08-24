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

RUN brew update \
 && test -n "$TEST_TAG" \
 && bash packaging/test-homebrew-formula.sh "$TEST_TAG" /work/dist/whiskerless-*.tar.gz \
 && touch /home/linuxbrew/homebrew-smoke-passed

FROM scratch AS result
COPY --from=smoke /home/linuxbrew/homebrew-smoke-passed /homebrew-smoke-passed
