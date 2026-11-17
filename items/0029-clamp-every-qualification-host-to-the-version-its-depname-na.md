# #29 Clamp every qualification host to the version its depName names

- Kind: pull, state: closed, by cody, created 2026-08-23T17:58:20-07:00
- Labels: none; milestone: none
- refs/pull/29/head -> main, merged: True

Renovate was retrying two bumps forever because nothing held the qualification hosts to the version their depName names: `ubuntu-26.04-current` proposed 26.10 and `fedora-44-current` proposed 45, each failing and each retried. dreame already clamped all three; this copies them across.

Adds guards, mirrored into dreame, for the whole class:
- a depName that encodes a version must be clamped to it
- no annotation may sit in a file no custom manager scans
- no annotation may name a datasource its manager will not bind
- every digest-pinned image under packaging/ must be annotated
- the built-in dockerfile manager must stay off, so it cannot compete with the annotations
