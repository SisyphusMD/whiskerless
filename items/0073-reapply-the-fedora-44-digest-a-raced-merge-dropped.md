# #73 Reapply the fedora-44 digest a raced merge dropped

- Kind: pull, state: closed, by cody, created 2026-08-28T12:40:16-07:00
- Labels: none; milestone: none
- refs/pull/73/head -> main, merged: True

PR #56 reports merged=true with merge commit a7a2d41f, but that commit is not an ancestor of main: the subsequent merge was computed against the pre-#56 tip and overwrote it. This is the documented Forgejo async-merge race, and the recovery is a new commit re-applying the diff rather than any history rewrite.

Restores the digest to 43b29f6, which is what dreame-valetudo already pins in both of its sites.
