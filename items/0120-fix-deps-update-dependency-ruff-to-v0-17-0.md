# #120 fix(deps): update dependency ruff to v0.17.0

- Kind: pull, state: closed, by renovate, created 2026-10-09T13:10:19-07:00
- Labels: none; milestone: none
- refs/pull/120/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [ruff](https://docs.astral.sh/ruff) ([source](https://github.com/astral-sh/ruff), [changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)) | `==0.16.10` → `==0.17.0` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/ruff/0.17.0?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/ruff/0.16.10/0.17.0?slim=true) |

---

### Release Notes

<details>
<summary>astral-sh/ruff (ruff)</summary>

### [`v0.17.0`](https://github.com/astral-sh/ruff/blob/HEAD/CHANGELOG.md#0170)

[Compare Source](https://github.com/astral-sh/ruff/compare/0.16.10...0.17.0)

Released on 2026-10-09.

The executables in our macOS and Windows release archives and `ruff` wheels are now code-signed.
macOS executables are signed with an Apple Developer ID certificate and notarized by Apple. Windows
executables have timestamped Authenticode signatures from Azure Artifact Signing. This enables
verification of the release publisher and binary integrity, supports publisher-based allowlisting,
and should reduce security warnings and antivirus false positives.

##### Breaking changes

- Update the default and latest Python versions for 3.15 ([#&#8203;28792](https://github.com/astral-sh/ruff/pull/28792))

  Ruff now defaults to Python 3.11 instead of 3.10 when no Python version is configured through
  [`target-version`](https://docs.astral.sh/ruff/settings/#target-version) or
  [`requires-python`](https://docs.astral.sh/ruff/configuration/#inferring-the-python-version). When
  checking for syntax errors without a configured Python version, Ruff now defaults to Python 3.15
  instead of 3.14.

- Update the default rule set ([#&#8203;28786](https://github.com/astral-sh/ruff/pull/28786))

  Several of the `flake8-datetimez` rules
  ([`DTZ001`](https://docs.astral.sh/ruff/rules/call-datetime-without-tzinfo/),
  [`DTZ005`](https://docs.astral.sh/ruff/rules/call-datetime-now-without-tzinfo/),
  [`DTZ006`](https://docs.astral.sh/ruff/rules/call-datetime-fromtimestamp/),
  [`DTZ007`](https://docs.astral.sh/ruff/rules/call-datetime-strptime-without-zone/),
  [`DTZ011`](https://docs.astral.sh/ruff/rules/call-date-today/),
  [`DTZ012`](https://docs.astral.sh/ruff/rules/call-date-fromtimestamp/), and
  [`DTZ901`](https://docs.astral.sh/ruff/rules/datetime-min-max/)) are no longer enabled by default,
  while [`undefined-local-with-nested-import-star-usage`](https://docs.astral.sh/ruff/rules/undefined-local-with-nested-import-star-usage/)
  (`F406`), which corresponds to a syntax error, is now enabled by default.

- Update Rust crate quick-junit to 0.8.0 ([#&#8203;27295](https://github.com/astral-sh/ruff/pull/27295))

  JUnit output now uses a `skipped` attribute instead of `disabled` on `<testsuite>` elements and
  includes a `skipped` attribute on the root `<testsuites>` element.

- \[`flake8-import-conventions`] Add `datetime as dt` as a conventional alias (`ICN001`) ([#&#8203;28790](https://github.com/astral-sh/ruff/pull/28790))

- Support Unicode dummy variable names ([#&#8203;28722](https://github.com/astral-sh/ruff/pull/28722))

  The default [`lint.dummy-variable-rgx`](https://docs.astral.sh/ruff/settings/#lint_dummy-variable-rgx)
  now recognizes underscore-prefixed Unicode names, such as `_次`, as dummy variables.

- Update to Unicode 17 ([#&#8203;21229](https://github.com/astral-sh/ruff/pull/21229), [#&#8203;28784](https://github.com/astral-sh/ruff/pull/28784))

  Ruff now uses Unicode 17 data for identifier normalization and named character escapes (`"\N{...}"`).

- Always show unsafe and display-only fixes in the CLI ([#&#8203;27810](https://github.com/astral-sh/ruff/pull/27810))

  The default `full` output format now shows unsafe fixes and suggestions requiring manual review,
  regardless of the [`unsafe-fixes`](https://docs.astral.sh/ruff/settings/#unsafe-fixes) setting.
  Actually applying unsafe fixes still requires explicit opt-in.

- Remove the Python dependency from conda-forge builds ([conda-forge/ruff-feedstock#361](https://github.com/conda-forge/ruff-feedstock/pull/361))

  The conda-forge build no longer depends on Python, now supports linux-riscv64, win-arm64, and
  linux-ppc64le platforms, and now includes shell completions. However, no longer depending on
  Python means that `python -m ruff` and `import ruff` will no longer work. Use `ruff` directly from
  `PATH` instead. PyPI installations and those from the standalone installer are unaffected.

- Remove support for ruff-lsp ([#&#8203;28750](https://github.com/astral-sh/ruff/pull/28750))

  Support for `ruff-lsp`, the legacy Python language server [deprecated in Ruff
  v0.9.5](https://github.com/astral-sh/ruff/releases/tag/0.9.5), has been removed. The Ruff VS Code
  extension now always uses the native language server; `ruff.nativeServer` is deprecated and
  ignored. See the [migration guide](https://docs.astral.sh/ruff/editors/migration/).

##### Stabilization

The following rules have been stabilized and are no longer in preview:

- [`lazy-import-mismatch`](https://docs.astral.sh/ruff/rules/lazy-import-mismatch) (`TID254`)
- [`lazy-import-immediately-resolved`](https://docs.astral.sh/ruff/rules/lazy-import-immediately-resolved)
  (`TID255`)
- [`os-path-commonprefix`](https://docs.astral.sh/ruff/rules/os-path-commonprefix) (`RUF071`)

The following behaviors have been stabilized:

- The formatter, [`unsorted-imports`](https://docs.astral.sh/ruff/rules/unsorted-imports/) (`I001`),
  [`line-too-long`](https://docs.astral.sh/ruff/rules/line-too-long/) (`E501`), and
  [`doc-line-too-long`](https://docs.astral.sh/ruff/rules/doc-line-too-long/) (`W505`) now
  consistently ignore trailing pragma comments when computing line length. This resolved several
  bugs involving interactions between these rules
  ([#&#8203;27313](https://github.com/astral-sh/ruff/pull/27313)) but may also cause existing imports to be
  reformatted and was thus classified as a breaking change.

##### Preview features

- \[`flake8-bugbear`] Report the method name and a more precise range (`B005`) ([#&#8203;27050](https://github.com/astral-sh/ruff/pull/27050))
- \[`refurb`] Mark fix unsafe and move to `suspicious` (`FURB152`) ([#&#8203;28405](https://github.com/astral-sh/ruff/pull/28405))
- \[`ruff`] Allow docstrings in strict mode (`RUF067`) ([#&#8203;28679](https://github.com/astral-sh/ruff/pull/28679))

##### Bug fixes

- \[`flake8-builtins`] Expand checks in class scopes (`A001`) ([#&#8203;29076](https://github.com/astral-sh/ruff/pull/29076))
- \[`flake8-self`] Allow private access on `object.__new__(cls)` instances (`SLF001`) ([#&#8203;29001](https://github.com/astral-sh/ruff/pull/29001))
- \[`flake8-tidy-imports`] Skip `lazy-import-mismatch` in stubs (`TID254`) ([#&#8203;29095](https://github.com/astral-sh/ruff/pull/29095))
- \[`flake8-type-checking`] Add the notion of runtime-ambiguous references ([#&#8203;26508](https://github.com/astral-sh/ruff/pull/26508))
- \[`flake8-type-checking`] Never flag annotations in function scopes ([#&#8203;29183](https://github.com/astral-sh/ruff/pull/29183))
- \[`pyflakes`] Mark the fix as unsafe when it creates a docstring (`F541`) ([#&#8203;28258](https://github.com/astral-sh/ruff/pull/28258))
- \[`pylint`] Preserve trailing comments in `useless-return` fix (`PLR1711`) ([#&#8203;29180](https://github.com/astral-sh/ruff/pull/29180))
- \[`ruff`] Avoid false positive when `pytest.raises` is used in a `with` statement (`RUF061`) ([#&#8203;28186](https://github.com/astral-sh/ruff/pull/28186))

##### Rule changes

- \[`pyupgrade`] Suggest `typing.TypeForm` on Python 3.15 (`UP035`) ([#&#8203;29084](https://github.com/astral-sh/ruff/pull/29084))

##### Contributors

- [@&#8203;DeviousCardi](https://github.com/DeviousCardi)
- [@&#8203;hugehoo](https://github.com/hugehoo)
- [@&#8203;nekomario28](https://github.com/nekomario28)
- [@&#8203;Daverball](https://github.com/Daverball)
- [@&#8203;Viicos](https://github.com/Viicos)
- [@&#8203;DebadityaHait](https://github.com/DebadityaHait)
- [@&#8203;saberoueslati](https://github.com/saberoueslati)
- [@&#8203;baltasarblanco](https://github.com/baltasarblanco)
- [@&#8203;yxshee](https://github.com/yxshee)
- [@&#8203;lognd](https://github.com/lognd)
- [@&#8203;dor-sr](https://github.com/dor-sr)

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
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4xNDYuMyIsInVwZGF0ZWRJblZlciI6IjQ0LjE0Ni4zIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJtaW5vci11cGRhdGUiXX0=-->
