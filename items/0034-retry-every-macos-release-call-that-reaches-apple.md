# #34 Retry every macOS release call that reaches Apple

- Kind: pull, state: closed, by cody, created 2026-08-24T00:06:36-07:00
- Labels: none; milestone: none
- refs/pull/34/head -> main, merged: True

rc.43 died on `dist/whiskerless: A timestamp was expected but was not found` while signing the x86_64 pkg. arm64 signed fine on the same run, so it was a transient outage at Apple.

Every macOS release step reaches an Apple service on every invocation: `codesign` and `productsign` each request a trusted timestamp, `notarytool` uploads, and `stapler` downloads the ticket back. All four now go through `packaging/retry.sh` with a backoff that spans two and a half minutes.

Dropping the timestamp was never an option - it is what keeps the signature verifiable past the certificate expiry, and notarization refuses a build without one.

The invariant derives the covered window from the script and the workflow rather than restating it, so widening one without the other cannot pass quietly.
