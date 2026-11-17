# #155 fix(deps): update dependency ruff to v0.17.4

- Kind: pull, state: closed, by renovate, created 2026-11-05T11:13:45-08:00
- Labels: none; milestone: none
- refs/pull/155/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [ruff](https://docs.astral.sh/ruff) ([source](https://github.com/astral-sh/ruff), [changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)) | `==0.17.3` → `==0.17.4` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/ruff/0.17.4?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/ruff/0.17.3/0.17.4?slim=true) |

---

### Release Notes

<details>
<summary>astral-sh/ruff (ruff)</summary>

### [`v0.17.4`](https://github.com/astral-sh/ruff/blob/HEAD/CHANGELOG.md#0174)

[Compare Source](https://github.com/astral-sh/ruff/compare/0.17.3...0.17.4)

Released on 2026-11-05.

##### Preview features

- \[`flake8-logging-format`] Avoid behavior changes and syntax errors in fixes (`G004`) ([#&#8203;27419](https://github.com/astral-sh/ruff/pull/27419))
- \[`security`] Implement `tarfile-ignore-zeros-true` ([#&#8203;28680](https://github.com/astral-sh/ruff/pull/28680))

##### Bug fixes

- Accept a bare raise before a semicolon ([#&#8203;29761](https://github.com/astral-sh/ruff/pull/29761))
- Allow match identifiers after a semicolon ([#&#8203;29760](https://github.com/astral-sh/ruff/pull/29760))
- Fix panic on BOM-prefixed files in diagnostic renderer ([#&#8203;30017](https://github.com/astral-sh/ruff/pull/30017))
- \[`flake8-simplify`] Report collapsible `elif` clauses after a multi-statement `if` branch (`SIM102`) ([#&#8203;29814](https://github.com/astral-sh/ruff/pull/29814))

##### Rule changes

- Show more nonprinting characters in diagnostic fix diffs ([#&#8203;30062](https://github.com/astral-sh/ruff/pull/30062))

##### Performance

- Coalesce source slices when formatting attributes ([#&#8203;29841](https://github.com/astral-sh/ruff/pull/29841))
- Collect return statements with a statement-only visitor ([#&#8203;29911](https://github.com/astral-sh/ruff/pull/29911))
- \[`pyflakes`] Defer value comparisons for repeated dictionary keys (`F601`, `F602`) ([#&#8203;29739](https://github.com/astral-sh/ruff/pull/29739))
- Format node fields directly when comment handling is unnecessary ([#&#8203;29853](https://github.com/astral-sh/ruff/pull/29853))
- Reduce formatter source-slice overhead ([#&#8203;29855](https://github.com/astral-sh/ruff/pull/29855))
- Reuse a callee's qualified name across lint rules ([#&#8203;29916](https://github.com/astral-sh/ruff/pull/29916))
- Skip invalid string character checks when the source contains none ([#&#8203;29883](https://github.com/astral-sh/ruff/pull/29883))
- Use a Bloom filter for formatter comment lookups ([#&#8203;29852](https://github.com/astral-sh/ruff/pull/29852))
- Use a concrete buffer for ordinary writes ([#&#8203;29819](https://github.com/astral-sh/ruff/pull/29819))

##### CLI

- Give `NO_COLOR` precedence in Ruff and ty diagnostics ([#&#8203;29898](https://github.com/astral-sh/ruff/pull/29898))
- Honor `CLICOLOR=0` in Ruff and ty diagnostics ([#&#8203;29910](https://github.com/astral-sh/ruff/pull/29910))

##### Documentation

- Correct the documented `version` and `src` defaults for `ruff-action` ([#&#8203;29880](https://github.com/astral-sh/ruff/pull/29880))
- \[`flake8-bugbear`] Make `B014` example error out-of-the-box ([#&#8203;29941](https://github.com/astral-sh/ruff/pull/29941))
- \[`flake8-no-pep420`] Document preview behavior (`INP001`) ([#&#8203;29764](https://github.com/astral-sh/ruff/pull/29764))
- \[`isort`] Expand `I001` documentation ([#&#8203;29843](https://github.com/astral-sh/ruff/pull/29843))

##### Other changes

- \[syntax-errors] Extend `__debug__` write check to attribute targets ([#&#8203;27908](https://github.com/astral-sh/ruff/pull/27908))

##### Contributors

- [@&#8203;fixfon](https://github.com/fixfon)
- [@&#8203;hirehamir](https://github.com/hirehamir)
- [@&#8203;MichaReiser](https://github.com/MichaReiser)
- [@&#8203;saberoueslati](https://github.com/saberoueslati)
- [@&#8203;mangod12](https://github.com/mangod12)
- [@&#8203;Sacrimento](https://github.com/Sacrimento)
- [@&#8203;AlexWaygood](https://github.com/AlexWaygood)
- [@&#8203;mulaihonglixihonglixi-web](https://github.com/mulaihonglixihonglixi-web)
- [@&#8203;adarrevah](https://github.com/adarrevah)
- [@&#8203;charliermarsh](https://github.com/charliermarsh)
- [@&#8203;shan3520](https://github.com/shan3520)
- [@&#8203;halcyon-past](https://github.com/halcyon-past)

</details>

---

### Configuration

📅 **Schedule**: (UTC)

- Branch creation
  - At any time (no schedule defined)
- Automerge
  - At any time (no schedule defined)

🚦 **Automerge**: Enabled.

♻ **Rebasing**: Whenever PR is behind base branch, or you tick the rebase/retry checkbox.

🔕 **Ignore**: Close this PR and you won't be reminded about this update again.

---

 - [ ] <!-- rebase-check -->If you want to rebase/retry this PR, check this box

---

This PR has been generated by [Mend Renovate CLI](https://github.com/renovatebot/renovate).
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yMjAuMCIsInVwZGF0ZWRJblZlciI6IjQ0LjIyMC4wIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJwYXRjaC11cGRhdGUiXX0=-->
