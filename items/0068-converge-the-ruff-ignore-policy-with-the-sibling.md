# #68 Converge the ruff ignore policy with the sibling

- Kind: pull, state: closed, by cody, created 2026-08-28T00:11:16-07:00
- Labels: none; milestone: none
- refs/pull/68/head -> main, merged: True

Drops the E501 ignore no selected rule can trigger, and replaces the blanket RUF001-3 mute with an allowlist naming the two confusables actually used (EN DASH, MULTIPLICATION SIGN), so the rules stay live for everything else.
