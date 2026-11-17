# #23 Size the PyPI wait against a queued forge

- Kind: pull, state: closed, by cody, created 2026-08-23T02:36:55-07:00
- Labels: none; milestone: none
- refs/pull/23/head -> main, merged: True

The GitHub arm64 and macOS release workflows are triggered by the mirrored tag, which arrives within seconds. The Forgejo pipeline that actually uploads to PyPI can sit behind unrelated jobs far longer than the upload takes.

On rc.36 the arm64 job waited its ten minutes and gave up at 08:30; the upload then succeeded normally at 08:47. Every downstream job that needed the arm64 assets failed as a result.

The window is now sized against how long a busy forge can defer a job, and is overridable.
