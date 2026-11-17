# #163 fix(deps): update dependency ruff to v0.17.5

- Kind: pull, state: closed, by renovate, created 2026-11-12T10:08:52-08:00
- Labels: none; milestone: none
- refs/pull/163/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [ruff](https://docs.astral.sh/ruff) ([source](https://github.com/astral-sh/ruff), [changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)) | `==0.17.4` → `==0.17.5` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/ruff/0.17.5?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/ruff/0.17.4/0.17.5?slim=true) |

---

### Release Notes

<details>
<summary>astral-sh/ruff (ruff)</summary>

### [`v0.17.5`](https://github.com/astral-sh/ruff/blob/HEAD/CHANGELOG.md#0175)

[Compare Source](https://github.com/astral-sh/ruff/compare/0.17.4...0.17.5)

Released on 2026-11-12.

##### Preview features

- Redirect renamed rules ([#&#8203;30081](https://github.com/astral-sh/ruff/pull/30081))
- \[`flake8-async`] Implement `pytest-raises-exception-group` (`ASYNC401`) ([#&#8203;28772](https://github.com/astral-sh/ruff/pull/28772))
- \[`flake8-logging-format`] Mark `G004` fix as unsafe ([#&#8203;30087](https://github.com/astral-sh/ruff/pull/30087))
- \[`pylint`] Implement `no-method-argument` (`PLE0211`) ([#&#8203;29748](https://github.com/astral-sh/ruff/pull/29748))
- \[`refurb`] Do not offer fix when `write` is nested in an expression (`FURB103`) ([#&#8203;29789](https://github.com/astral-sh/ruff/pull/29789))
- \[`ruff`] Add `renamed-rule` (`RUF202`) ([#&#8203;30079](https://github.com/astral-sh/ruff/pull/30079))
- \[`ruff`] Expand `redirected-noqa` to other suppression comments (`RUF101`) ([#&#8203;30078](https://github.com/astral-sh/ruff/pull/30078))

##### Bug fixes

- Avoid crashing when Ruff logs to a closed stderr pipe ([#&#8203;30209](https://github.com/astral-sh/ruff/pull/30209))
- Fix fixes that add or remove a keyword argument with a parenthesized value ([#&#8203;30189](https://github.com/astral-sh/ruff/pull/30189))
- \[`flake8-import-conventions`] Avoid shadowing names when fixing import aliases (`ICN001`) ([#&#8203;30035](https://github.com/astral-sh/ruff/pull/30035))
- \[`flake8-bugbear`] Fix `B010` autofix for parenthesized `setattr` calls ([#&#8203;30168](https://github.com/astral-sh/ruff/pull/30168))
- \[`flake8-pyi`] Fix `PYI034` autofix for parenthesized `self` annotations ([#&#8203;30173](https://github.com/astral-sh/ruff/pull/30173))
- \[`pyupgrade`] Fix `UP031` duplicating closing parentheses around the format string ([#&#8203;30172](https://github.com/astral-sh/ruff/pull/30172))

##### Rule changes

- \[`flake8-bugbear`] Ignore frozen dataclass instantiations (`B008`) ([#&#8203;29231](https://github.com/astral-sh/ruff/pull/29231))

##### Performance

- Various performance improvements ([#&#8203;30375](https://github.com/astral-sh/ruff/pull/30375), [#&#8203;30211](https://github.com/astral-sh/ruff/pull/30211), [#&#8203;30368](https://github.com/astral-sh/ruff/pull/30368), [#&#8203;30259](https://github.com/astral-sh/ruff/pull/30259), [#&#8203;30354](https://github.com/astral-sh/ruff/pull/30354), [#&#8203;30115](https://github.com/astral-sh/ruff/pull/30115), [#&#8203;30133](https://github.com/astral-sh/ruff/pull/30133), [#&#8203;30132](https://github.com/astral-sh/ruff/pull/30132), [#&#8203;30358](https://github.com/astral-sh/ruff/pull/30358), [#&#8203;30135](https://github.com/astral-sh/ruff/pull/30135), [#&#8203;30369](https://github.com/astral-sh/ruff/pull/30369), [#&#8203;30351](https://github.com/astral-sh/ruff/pull/30351), [#&#8203;30352](https://github.com/astral-sh/ruff/pull/30352), [#&#8203;30347](https://github.com/astral-sh/ruff/pull/30347), [#&#8203;30379](https://github.com/astral-sh/ruff/pull/30379), [#&#8203;30328](https://github.com/astral-sh/ruff/pull/30328), [#&#8203;30329](https://github.com/astral-sh/ruff/pull/30329), [#&#8203;29446](https://github.com/astral-sh/ruff/pull/29446))

##### Other changes

- Fix FreeBSD source builds with libc 0.2.190 ([#&#8203;30176](https://github.com/astral-sh/ruff/pull/30176))

##### Contributors

- [@&#8203;rajveer3x](https://github.com/rajveer3x)
- [@&#8203;tjkuson](https://github.com/tjkuson)
- [@&#8203;hugehoo](https://github.com/hugehoo)
- [@&#8203;hector2394](https://github.com/hector2394)
- [@&#8203;ansh-rohilla](https://github.com/ansh-rohilla)
- [@&#8203;mati-caliz](https://github.com/mati-caliz)
- [@&#8203;yxshee](https://github.com/yxshee)
- [@&#8203;charliermarsh](https://github.com/charliermarsh)
- [@&#8203;MichaReiser](https://github.com/MichaReiser)
- [@&#8203;GeorgiaPreda](https://github.com/GeorgiaPreda)
- [@&#8203;G26karthik](https://github.com/G26karthik)
- [@&#8203;ntBre](https://github.com/ntBre)
- [@&#8203;s-cork](https://github.com/s-cork)

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
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yMzYuMiIsInVwZGF0ZWRJblZlciI6IjQ0LjIzNi4yIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJwYXRjaC11cGRhdGUiXX0=-->
