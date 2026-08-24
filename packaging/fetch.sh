#!/bin/sh
# Fetch a URL to a path, retrying every failure — a name-resolution error included.
#
# curl's own `--retry` does not cover exit 6 (could not resolve host); only `--retry-all-errors`
# does, and that option arrived in curl 7.71 while Rocky 8 ships 7.61 and rejects it outright. The
# install matrix runs on both, so the retry has to live in the shell rather than in curl's flags.
#
#   fetch.sh <output-path> <url>
set -eu

out="${1:?usage: fetch.sh <output-path> <url>}"
url="${2:?usage: fetch.sh <output-path> <url>}"

attempt=1
until curl -fsSL --connect-timeout 10 --max-time 300 -o "$out" "$url"; do
  if [ "$attempt" -ge 5 ]; then
    echo "fetch: giving up on $url after $attempt attempts" >&2
    exit 1
  fi
  # A partial file from the failed attempt would otherwise be handed to whatever reads it next.
  rm -f "$out"
  sleep $((attempt * 2))
  attempt=$((attempt + 1))
done
