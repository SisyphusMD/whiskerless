# #161 chore(deps): update goreleaser/nfpm docker tag to v2.49.0

- Kind: pull, state: closed, by renovate, created 2026-11-11T19:09:02-08:00
- Labels: none; milestone: none
- refs/pull/161/head -> main, merged: True

This PR contains the following updates:

| Package | Update | Change |
|---|---|---|
| [goreleaser/nfpm](https://github.com/goreleaser/nfpm) | minor | `v2.48.0` → `v2.49.0` |

---

### Release Notes

<details>
<summary>goreleaser/nfpm</summary>

### [`v2.49.0`](https://github.com/goreleaser/nfpm/releases/tag/v2.49.0)

[Compare Source](https://github.com/goreleaser/nfpm/compare/v2.48.0...v2.49.0)

#### Security

- [GHSA-cfgx-mprf-xh64](https://github.com/goreleaser/nfpm/security/advisories/GHSA-cfgx-mprf-xh64): Reserved metadata name collision leads to supply chain attack with root code execution and package identity spoofing
- [GHSA-839m-5qhj-w4rm](https://github.com/goreleaser/nfpm/security/advisories/GHSA-839m-5qhj-w4rm): Incorrect escaping in SRPM spec results in Arbitrary Code Execution

#### Changelog

##### New Features

- [`62f72a6`](https://github.com/goreleaser/nfpm/commit/62f72a6783dc2b2781a9ee0c47f2d0de05770121): feat(msix): default publisher from the signing certificate or vendor ([#&#8203;1135](https://github.com/goreleaser/nfpm/issues/1135)) ([@&#8203;djgilcrease](https://github.com/djgilcrease))
- [`edf3552`](https://github.com/goreleaser/nfpm/commit/edf35527203670398264204fdafb775ea9c11b9b): feat(rpm): add script_requires to require script interpreters ([#&#8203;1151](https://github.com/goreleaser/nfpm/issues/1151)) ([@&#8203;zehome](https://github.com/zehome))
- [`c953fe3`](https://github.com/goreleaser/nfpm/commit/c953fe3995c3b305d5e9c23c33bb47b4e145bc8d): feat: add msi support ([#&#8203;1097](https://github.com/goreleaser/nfpm/issues/1097)) ([@&#8203;djgilcrease](https://github.com/djgilcrease))

##### Bug fixes

- [`ff7e8cd`](https://github.com/goreleaser/nfpm/commit/ff7e8cd218eb61318a3378c4d275d1d947ad7cd9): fix(apk): Use the configured mtime for install scripts ([#&#8203;1169](https://github.com/goreleaser/nfpm/issues/1169)) ([@&#8203;somaz94](https://github.com/somaz94))
- [`1dc3fcc`](https://github.com/goreleaser/nfpm/commit/1dc3fccc6e11632579905d0108d3b616e80ac684): fix(ci): allow unsigned RPM acceptance fixtures ([#&#8203;1175](https://github.com/goreleaser/nfpm/issues/1175)) ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`d2d7180`](https://github.com/goreleaser/nfpm/commit/d2d7180294d4d68938e364bc9b4c92480be6026d): fix(ci): create generated update PRs with app token ([#&#8203;1176](https://github.com/goreleaser/nfpm/issues/1176)) ([@&#8203;caarlos0](https://github.com/caarlos0))

##### Dependency updates

- [`93d5ad1`](https://github.com/goreleaser/nfpm/commit/93d5ad163ae34ac03b1f24407a3b673b8a120030): fix(deps): bump alpine from 3.24.2 to 3.24.3 ([#&#8203;1166](https://github.com/goreleaser/nfpm/issues/1166)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`582a751`](https://github.com/goreleaser/nfpm/commit/582a7510d57278b1b54cded2718de00c6c81135a): fix(deps): bump alpine from 3.24.2 to 3.24.3 in /testdata/acceptance ([#&#8203;1167](https://github.com/goreleaser/nfpm/issues/1167)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])

##### Build process updates

- [`37cd27d`](https://github.com/goreleaser/nfpm/commit/37cd27d337af038a8a40b84eedbab648f768f1fb): ci(deps): bump the actions group with 5 updates ([#&#8203;1159](https://github.com/goreleaser/nfpm/issues/1159)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`6880989`](https://github.com/goreleaser/nfpm/commit/688098943e97f7e8374ace60322f22f5cce8f806): ci(deps): bump the actions group with 6 updates ([#&#8203;1162](https://github.com/goreleaser/nfpm/issues/1162)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`9b57a4e`](https://github.com/goreleaser/nfpm/commit/9b57a4e1742795da6c8a35ce73abd119838a40b2): ci(deps): bump the actions group with 6 updates ([#&#8203;1165](https://github.com/goreleaser/nfpm/issues/1165)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`eee2bc9`](https://github.com/goreleaser/nfpm/commit/eee2bc94ca1bbfdaf4f12c29ef962fc4ed613565): ci(deps): bump the actions group with 6 updates ([#&#8203;1173](https://github.com/goreleaser/nfpm/issues/1173)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`44ea002`](https://github.com/goreleaser/nfpm/commit/44ea002d6394aed93d4695d05add27915d6ba65d): ci: combine generation workflows and use GitHub App identity ([#&#8203;1180](https://github.com/goreleaser/nfpm/issues/1180)) ([@&#8203;caarlos0](https://github.com/caarlos0))

##### Other work

- [`f01bd40`](https://github.com/goreleaser/nfpm/commit/f01bd4039fd9997376836fb80ada8c69b23b6c4f): Merge commit from fork ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`7fd9e9b`](https://github.com/goreleaser/nfpm/commit/7fd9e9b8a57311155e93a1994891b9f71ca665fd): Merge commit from fork ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`b06214c`](https://github.com/goreleaser/nfpm/commit/b06214cfe8178e852566020aed2f4a4e3230f154): docs: align sponsors page with goreleaser's ([#&#8203;1163](https://github.com/goreleaser/nfpm/issues/1163)) ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`3871eb3`](https://github.com/goreleaser/nfpm/commit/3871eb339fbaf87dd214a57d4930d660107f1af5): docs: update Go and Hextra ([#&#8203;1172](https://github.com/goreleaser/nfpm/issues/1172)) ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`92ea769`](https://github.com/goreleaser/nfpm/commit/92ea769fdc2bdb13690dea86a2a73271f8c3d151): docs: update cmd docs ([#&#8203;1177](https://github.com/goreleaser/nfpm/issues/1177)) ([@&#8203;goreleaser](https://github.com/goreleaser)\[bot])

**Full Changelog**: <https://github.com/goreleaser/nfpm/compare/v2.48.0...v2.49.0>

#### Helping out

This release is only possible thanks to **all** the support of **awesome people**!

Want to be one of them?
You can [sponsor](https://goreleaser.com/sponsors/) or [contribute with code](https://goreleaser.com/contributing).

#### Where to go next?

- nFPM is a satellite project from GoReleaser. [Check it out](https://goreleaser.com)!
- Find examples and commented usage of all options in our [website](https://nfpm.goreleaser.com/).
- Reach out on [Discord](https://discord.gg/RGEBtg8vQ6) and [Twitter](https://twitter.com/goreleaser)!

<a href="https://goreleaser.com"><img src="https://raw.githubusercontent.com/goreleaser/artwork/master/opencollective-header.png" with="100%" alt="GoReleaser logo"></a>

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
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yMzUuMCIsInVwZGF0ZWRJblZlciI6IjQ0LjIzNS4wIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJtaW5vci11cGRhdGUiXX0=-->
