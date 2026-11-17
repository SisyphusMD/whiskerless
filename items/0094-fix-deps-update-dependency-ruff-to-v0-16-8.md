# #94 fix(deps): update dependency ruff to v0.16.8

- Kind: pull, state: closed, by renovate, created 2026-09-10T21:11:40-07:00
- Labels: none; milestone: none
- refs/pull/94/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [ruff](https://docs.astral.sh/ruff) ([source](https://github.com/astral-sh/ruff), [changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)) | `==0.16.6` → `==0.16.8` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/ruff/0.16.8?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/ruff/0.16.6/0.16.8?slim=true) |

---

### Release Notes

<details>
<summary>astral-sh/ruff (ruff)</summary>

### [`v0.16.8`](https://github.com/astral-sh/ruff/blob/HEAD/CHANGELOG.md#0168)

[Compare Source](https://github.com/astral-sh/ruff/compare/0.16.7...0.16.8)

Released on 2026-09-16.

##### Bug fixes

- Visit functional `TypedDict` keyword arguments correctly ([#&#8203;28584](https://github.com/astral-sh/ruff/pull/28584))
- \[`flake8-simplify`] Detect nested `async with` under sync parent (`SIM117`) ([#&#8203;27821](https://github.com/astral-sh/ruff/pull/27821))
- \[`flake8-simplify`] Preserve operand order in `SIM109` fix ([#&#8203;27824](https://github.com/astral-sh/ruff/pull/27824))
- \[`pyupgrade`] Preserve required parentheses in multiline `UP040` fixes ([#&#8203;28164](https://github.com/astral-sh/ruff/pull/28164))
- \[`pyupgrade`] Skip `TypeVarTuple` and `ParamSpec` conversions with bounds or constraints (`UP040`, `UP046`, `UP047`) ([#&#8203;28505](https://github.com/astral-sh/ruff/pull/28505))

##### Rule changes

- Add support for `__lazy_modules__` ([#&#8203;28459](https://github.com/astral-sh/ruff/pull/28459))
- Recognize PEP-728 `TypedDict` class keywords ([#&#8203;28533](https://github.com/astral-sh/ruff/pull/28533))
- Recognize quoted types in `typing.TypeForm` ([#&#8203;28507](https://github.com/astral-sh/ruff/pull/28507))
- Support conditional assignment to `__lazy_modules__` ([#&#8203;28491](https://github.com/astral-sh/ruff/pull/28491))
- \[`flake8-type-checking`] Prefer lazy imports over `TYPE_CHECKING` on Python 3.15 and later (`TC001`, `TC002`, `TC003`) ([#&#8203;28541](https://github.com/astral-sh/ruff/pull/28541))
- \[`pyupgrade`] Make the fix for `UP040` always unsafe ([#&#8203;28526](https://github.com/astral-sh/ruff/pull/28526))
- \[`pyupgrade`] Stop recommending deprecated `ByteString` aliases (`UP035`) ([#&#8203;28498](https://github.com/astral-sh/ruff/pull/28498))
- \[`ruff`, `flake8-use-pathlib`] Recognize the `parent_mode` argument (`RUF064`, `PTH103`) ([#&#8203;28528](https://github.com/astral-sh/ruff/pull/28528))
- \[`ruff`] Detect `\Z` in `pytest.raises()` match patterns (`RUF043`) ([#&#8203;28598](https://github.com/astral-sh/ruff/pull/28598))

##### CLI

- Use rule name and code in formatter incompatibility warnings ([#&#8203;28571](https://github.com/astral-sh/ruff/pull/28571))

##### Configuration

- \[`flake8-tidy-imports`] Add `extend-banned-api` ([#&#8203;28644](https://github.com/astral-sh/ruff/pull/28644))

##### Contributors

- [@&#8203;VedantMadane](https://github.com/VedantMadane)
- [@&#8203;alzeph](https://github.com/alzeph)
- [@&#8203;charliermarsh](https://github.com/charliermarsh)
- [@&#8203;fredrikblau](https://github.com/fredrikblau)
- [@&#8203;ntBre](https://github.com/ntBre)
- [@&#8203;zsol](https://github.com/zsol)
- [@&#8203;Aniket-a14](https://github.com/Aniket-a14)
- [@&#8203;r-b-1](https://github.com/r-b-1)

### [`v0.16.7`](https://github.com/astral-sh/ruff/blob/HEAD/CHANGELOG.md#0167)

[Compare Source](https://github.com/astral-sh/ruff/compare/0.16.6...0.16.7)

Released on 2026-09-10.

##### Preview features

- \[`ruff`] Add rule for default values on method receivers (`RUF077`) ([#&#8203;26700](https://github.com/astral-sh/ruff/pull/26700))
- \[`ruff`] Recognize `re.prefixmatch` (`RUF039`, `RUF055`) ([#&#8203;28311](https://github.com/astral-sh/ruff/pull/28311))

##### Bug fixes

- Alternate nested quotes inside format spec interpolations ([#&#8203;28259](https://github.com/astral-sh/ruff/pull/28259))
- \[`flake8-implicit-str-concat`] Mark fix unsafe when it creates a docstring (`ISC003`) ([#&#8203;27981](https://github.com/astral-sh/ruff/pull/27981))
- \[`flake8-tidy-imports`] Skip fixes for multi-member imports (`TID254`) ([#&#8203;26584](https://github.com/astral-sh/ruff/pull/26584))
- \[`pylint`] Gate `ImportCycleError` on Python 3.15 (`PLW0133`) ([#&#8203;28310](https://github.com/astral-sh/ruff/pull/28310))

##### Rule changes

- Correct `D211` and `D203` rule conflict diagnostic ([#&#8203;28444](https://github.com/astral-sh/ruff/pull/28444))
- Recognize `slice` and `frozendict` generics ([#&#8203;28477](https://github.com/astral-sh/ruff/pull/28477))
- Stop defining `__cached__` for Python 3.15 ([#&#8203;28476](https://github.com/astral-sh/ruff/pull/28476))
- \[`pyupgrade`] Stop recommending removed `typing.no_type_check_decorator` (`UP035`) ([#&#8203;28475](https://github.com/astral-sh/ruff/pull/28475))

##### Performance

- Reuse parser name lookups when interning ([#&#8203;28399](https://github.com/astral-sh/ruff/pull/28399))
- Speed up inherited configuration resolution ([#&#8203;28299](https://github.com/astral-sh/ruff/pull/28299))

##### Documentation

- Fix `line-length` path in `--config` example ([#&#8203;28392](https://github.com/astral-sh/ruff/pull/28392))
- Remove the "Who’s Using Ruff?" list ([#&#8203;28455](https://github.com/astral-sh/ruff/pull/28455))

##### Other changes

- Embed archive checksums in the shell installer ([#&#8203;28281](https://github.com/astral-sh/ruff/pull/28281))

##### Contributors

- [@&#8203;The-Compiler](https://github.com/The-Compiler)
- [@&#8203;mdiniz97](https://github.com/mdiniz97)
- [@&#8203;zsol](https://github.com/zsol)
- [@&#8203;gorewilliams](https://github.com/gorewilliams)
- [@&#8203;RafaelJohn9](https://github.com/RafaelJohn9)
- [@&#8203;qatcod](https://github.com/qatcod)
- [@&#8203;zanieb](https://github.com/zanieb)
- [@&#8203;MichaReiser](https://github.com/MichaReiser)
- [@&#8203;ntBre](https://github.com/ntBre)
- [@&#8203;charliermarsh](https://github.com/charliermarsh)
- [@&#8203;nightt5879](https://github.com/nightt5879)
- [@&#8203;jonathandung](https://github.com/jonathandung)
- [@&#8203;jogo-openai](https://github.com/jogo-openai)

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
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC43OS42IiwidXBkYXRlZEluVmVyIjoiNDQuOTQuMCIsInRhcmdldEJyYW5jaCI6Im1haW4iLCJsYWJlbHMiOlsicGF0Y2gtdXBkYXRlIl19-->
