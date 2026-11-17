# #31 Link the donate page, and bound the install-matrix build cache

- Kind: pull, state: closed, by cody, created 2026-08-23T22:44:07-07:00
- Labels: none; milestone: none
- refs/pull/31/head -> main, merged: True

Links the Buy Me a Coffee page the PEAK mod already points at, worded to match it and adjusted per license.

Also bounds the buildx cache between install-matrix channels. Every channel pulls its own base image and layers onto a self-hosted runner with a finite disk, so unbounded the cache grows across the whole matrix and whichever channel runs last dies of it - which is how rc.23 failed, on `bottle-pour`, after every channel before it had passed. The prune flag is detected rather than assumed (`--keep-storage` was renamed `--max-used-space`), and a prune failure is reported instead of swallowed.
