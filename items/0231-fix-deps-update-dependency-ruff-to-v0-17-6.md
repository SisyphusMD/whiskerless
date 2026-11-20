# #231 fix(deps): update dependency ruff to v0.17.6

- Kind: pull, state: closed, by renovate, created 2026-11-19T08:09:22-08:00
- Labels: none; milestone: none
- refs/pull/231/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [ruff](https://docs.astral.sh/ruff) ([source](https://github.com/astral-sh/ruff), [changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)) | `==0.17.5` → `==0.17.6` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/ruff/0.17.6?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/ruff/0.17.5/0.17.6?slim=true) |

---

### Release Notes

<details>
<summary>astral-sh/ruff (ruff)</summary>

### [`v0.17.6`](https://github.com/astral-sh/ruff/blob/HEAD/CHANGELOG.md#0176)

[Compare Source](https://github.com/astral-sh/ruff/compare/0.17.5...0.17.6)

Released on 2026-11-19.

##### Preview features

- \[`flake8-type-checking`] Add a fix for `runtime-string-union` (`TC010`) ([#&#8203;15635](https://github.com/astral-sh/ruff/pull/15635))

##### Bug fixes

- Fix handling of parenthesized duplicate items (`B033`, `RUF068`) ([#&#8203;30493](https://github.com/astral-sh/ruff/pull/30493))
- \[`pyflakes`] Fix false negative when a name is assigned more than once (`F823`) ([#&#8203;30524](https://github.com/astral-sh/ruff/pull/30524))
- \[`pylint`] Avoid false positive when collection is modified in loop (`PLR1733`, `PLR1736`) ([#&#8203;30466](https://github.com/astral-sh/ruff/pull/30466))
- \[`ruff`] Avoid syntax error in `useless-finally` fix for inline `try` bodies (`RUF072`) ([#&#8203;30349](https://github.com/astral-sh/ruff/pull/30349))
- Treat relative imports from `.__future__` as ordinary imports ([#&#8203;30260](https://github.com/astral-sh/ruff/pull/30260))

##### Rule changes

- \[`flake8-simplify`] Avoid redundant `bool` wrappers in `SIM208` fixes ([#&#8203;30457](https://github.com/astral-sh/ruff/pull/30457))
- \[`pyflakes`] Ignore `__traceback_hide__` in `unused-variable` (`F841`) ([#&#8203;29600](https://github.com/astral-sh/ruff/pull/29600))

##### Performance

- Decode in-memory notebooks directly from their source string ([#&#8203;30385](https://github.com/astral-sh/ruff/pull/30385))
- Short-circuit exact qualified-name checks ([#&#8203;30058](https://github.com/astral-sh/ruff/pull/30058))
- Stream JSON diagnostics to the output writer ([#&#8203;30384](https://github.com/astral-sh/ruff/pull/30384))

##### Documentation

- Fix the multiline string example in Known Deviations from Black ([#&#8203;30447](https://github.com/astral-sh/ruff/pull/30447))
- Include the category in individual rule documentation pages ([#&#8203;30503](https://github.com/astral-sh/ruff/pull/30503))

##### Other changes

- Update Rust toolchain to 1.100 and MSRV to 1.98 ([#&#8203;30416](https://github.com/astral-sh/ruff/pull/30416))

##### Contributors

- [@&#8203;pseudo-usama](https://github.com/pseudo-usama)
- [@&#8203;G26karthik](https://github.com/G26karthik)
- [@&#8203;MichaReiser](https://github.com/MichaReiser)
- [@&#8203;apathydevil](https://github.com/apathydevil)
- [@&#8203;Shivansh-S17](https://github.com/Shivansh-S17)
- [@&#8203;charliermarsh](https://github.com/charliermarsh)
- [@&#8203;ntBre](https://github.com/ntBre)
- [@&#8203;anujdas](https://github.com/anujdas)
- [@&#8203;chammika](https://github.com/chammika)
- [@&#8203;imryanthedev](https://github.com/imryanthedev)
- [@&#8203;Daverball](https://github.com/Daverball)

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

Refs #211: standing issue for dependency updates.

No tests: dependency pins and their generated files are checked by the existing build and test jobs.
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yNTMuMiIsInVwZGF0ZWRJblZlciI6IjQ0LjI1My4yIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJwYXRjaC11cGRhdGUiXX0=-->


## forgejo-actions, 2026-11-19T08:09:30-08:00

<!-- ai-review -->
**AI review** of `6703471c34`: Single-line Renovate bump of ruff from 0.17.5 to 0.17.6, referencing the standing dependency-update issue #211. The diff is minimal, correctly scoped, and the 'No tests' justification is appropriate for a linter version pin.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
