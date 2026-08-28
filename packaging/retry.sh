#!/bin/sh
# Run a command, retrying with backoff.
#
#   retry.sh <attempts> <command> [args...]
#
# Shared rather than per-consumer because build-bottles.sh calls it: a vendored script may not
# depend on a file the standard neither ships nor locks, or the lock stops describing what it
# takes to run.
#
# For the release steps that reach a network service on every invocation and take the whole release
# down when it does not answer. `codesign` and `productsign` each request a trusted timestamp from
# Apple, and `notarytool` uploads the package. A missing timestamp fails with "A timestamp was
# expected but was not found", and dropping the timestamp is not an option: it is what keeps the
# signature verifiable past the certificate's expiry, and notarization refuses a build without one.
set -eu

attempts="${1:?usage: retry.sh <attempts> <command> [args...]}"
shift
[ "$#" -gt 0 ] || { echo "retry: no command given" >&2; exit 1; }

n=1
until "$@"; do
  if [ "$n" -ge "$attempts" ]; then
    echo "retry: giving up on '$1' after $n attempts" >&2
    exit 1
  fi
  # 15s steps: 15+30+45+60 is two and a half minutes across five attempts. The signing
  # calls themselves take seconds, so waiting longer between them costs almost nothing,
  # and a service that is briefly unreachable is usually unreachable for more than 50s.
  sleep $((n * 15))
  n=$((n + 1))
done
