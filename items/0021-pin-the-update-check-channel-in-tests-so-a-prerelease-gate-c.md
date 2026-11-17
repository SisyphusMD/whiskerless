# #21 Pin the update-check channel in tests, so a prerelease gate can run them

- Kind: pull, state: closed, by cody, created 2026-08-23T00:39:58-07:00
- Labels: none; milestone: none
- refs/pull/21/head -> main, merged: True

The marker filename is derived from `__version__`. These tests spelled the stable marker literally, so they passed only while the checkout carried a stable version.

Every prerelease gate stamps an rc BEFORE running the suite, so the next rc cut was guaranteed to fail on them. It did: run 5843.

The fixture pins the channel and runs each affected test on both, so the channel split is now covered rather than incidentally satisfied.
