# #86 fix(release): require a credential on every GitHub call, and refuse a tag already published anywhere

- Kind: pull, state: closed, by cody, created 2026-08-30T09:59:04-07:00
- Labels: none; milestone: none
- refs/pull/86/head -> main, merged: True

Vendors project-standard v0.1.24 and lands the workflow half.

**No unauthenticated GitHub calls.** Unauthenticated github.com allows 60 requests an hour per IP and every runner, mirror probe and CI poller shares one. Several helpers treated their token as optional, so once that budget was gone they did not fail - they answered 403, and the checks built on them stopped deciding anything while still reporting success. push-tag.sh, check-mirror-ci.sh, check-rc-install-matrix.sh, reconcile-releases.sh, github-release.sh and wait-for-release.sh now all make the token mandatory; reconcile also authenticates the asset download, which was going out bare.

push-tag.sh asserts before `git push --atomic`, and prerelease.yml asserts in the push step rather than the mirror step two steps later, because discovering it afterwards leaves the tag published and the run failed.

**The republish guard.** A history rewrite moves every tag at once and publish.yml fires on tag pushes, so one rewrite queues one publish run per tag - 35 of them here, each rebuilding a shipped rc for ~20 minutes before the immutable-asset policy refused it. The guard now checks BOTH publication targets before any build: checking only the source of truth would answer 404 for a partial publish that reached GitHub alone, and let a rewritten tag write new bytes to Forgejo and the NAS before GitHub refused them. It retries a non-definitive answer and then fails closed, since that is precisely when the inconsistency happens; a dispatch with the tag as the ref remains the escape, and is still the way to finish a partial publish.

Exercised against the live forge and mirror: a published tag refuses, an unknown tag proceeds, an unreachable forge and a bad credential both refuse.
