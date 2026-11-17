# #47 Qualify the .rpm on Rocky 10 and dnf5

- Kind: pull, state: closed, by cody, created 2026-08-25T15:11:55-07:00
- Labels: none; milestone: none
- refs/pull/47/head -> main, merged: True

Rocky 10 is the current release of the RPM family and neither repo installed the shipped `.rpm` on it; Fedora's dnf5 is a reimplementation that parses `.repo` files in its own code, so the existing Rocky 9 dnf4 leg proved nothing about it. Adds `rpm-file-current` and `dnf5-repo` to the install matrix, and pins the dnf repofile fetch to the tag under test instead of `branch/main`, matching the sibling.
