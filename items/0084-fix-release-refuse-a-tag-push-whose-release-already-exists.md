# #84 fix(release): refuse a tag push whose release already exists

- Kind: pull, state: closed, by cody, created 2026-08-29T18:19:33-07:00
- Labels: none; milestone: none
- refs/pull/84/head -> main, merged: True

Rewriting history moves every tag at once, and publish.yml fires on tag pushes, so one rewrite queues one publish run per tag. That happened here today: 35 runs, each rebuilding an already-shipped rc for roughly twenty minutes before the immutable-asset policy refused it on all three hosts.

Nothing was overwritten - that guard did its job - but the refusal is knowable in seconds. This checks whether the tag already has a release before any build starts.

Scoped to `push`, because a dispatch is the documented way to FINISH a partial publish and every helper it runs is idempotent. Read unauthenticated from the mirror, so it needs no secret in a job that deliberately checks out without credentials. Inconclusive answers do not block: a rate-limited probe refusing a legitimate release would be worse than a wasted build, and the immutable-asset refusal is still the backstop.

Exercised against the live API on all four branches - an existing release refuses, an unknown tag proceeds, a stubbed 5xx warns and continues.
