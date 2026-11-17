# #125 chore(deps): update goreleaser/nfpm docker tag to v2.48.0

- Kind: pull, state: closed, by renovate, created 2026-10-12T12:09:47-07:00
- Labels: none; milestone: none
- refs/pull/125/head -> main, merged: True

This PR contains the following updates:

| Package | Update | Change |
|---|---|---|
| [goreleaser/nfpm](https://github.com/goreleaser/nfpm) | minor | `v2.47.0` → `v2.48.0` |

**CI cannot reach this.** Nothing in a pull request builds with this pin: `publish.yml` runs only on a tag, and the install matrix exercises artifacts that are already published. A green PR here says the code still lints and tests — it says nothing about whether the release still builds.

Clear it by cutting a release candidate with the bump in place, then merge.

---

### Release Notes

<details>
<summary>goreleaser/nfpm</summary>

### [`v2.48.0`](https://github.com/goreleaser/nfpm/releases/tag/v2.48.0)

[Compare Source](https://github.com/goreleaser/nfpm/compare/v2.47.0...v2.48.0)

#### Changelog

##### New Features

- [`6d71362`](https://github.com/goreleaser/nfpm/commit/6d713625670ecbac5fe97b041204cbe42cbbfdf2): feat(arch): map ppc64 and ppc64le to Arch Linux POWER names ([#&#8203;1138](https://github.com/goreleaser/nfpm/issues/1138)) ([@&#8203;abemedia](https://github.com/abemedia))
- [`f42c951`](https://github.com/goreleaser/nfpm/commit/f42c9510c89f6052a044457538e4e2c662a6b8d2): feat: Add "force_implicit_dirs" to dir/tree. ([#&#8203;948](https://github.com/goreleaser/nfpm/issues/948)) ([@&#8203;volkadav](https://github.com/volkadav))
- [`e1c7b33`](https://github.com/goreleaser/nfpm/commit/e1c7b33e10143cfcd43cfb467a570894596f4ace): feat: replace rpmpack with a more complete implementation ([#&#8203;1104](https://github.com/goreleaser/nfpm/issues/1104)) ([@&#8203;djgilcrease](https://github.com/djgilcrease))

##### Security updates

- [`84adf13`](https://github.com/goreleaser/nfpm/commit/84adf13b39dc39201c9bff117e1549caa7019543): sec(deps): bump golang.org/x/ ([#&#8203;1157](https://github.com/goreleaser/nfpm/issues/1157)) ([@&#8203;caarlos0](https://github.com/caarlos0))

##### Bug fixes

- [`c424623`](https://github.com/goreleaser/nfpm/commit/c42462355e5209488787a8eec00a2bc98d45c462): fix(apk): normalize file modes before writing tar headers ([#&#8203;1113](https://github.com/goreleaser/nfpm/issues/1113)) ([@&#8203;ychampion](https://github.com/ychampion))
- [`a72ab8f`](https://github.com/goreleaser/nfpm/commit/a72ab8f3ac34368071812c9a796c830eaaee469f): fix(ci): Separate PR checks from queue acceptance tests ([#&#8203;1158](https://github.com/goreleaser/nfpm/issues/1158)) ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`93cf82d`](https://github.com/goreleaser/nfpm/commit/93cf82dd375cddb0c2b39609eccf0aef9e61ef3a): fix(ipk): normalize file modes before writing tar headers ([#&#8203;1145](https://github.com/goreleaser/nfpm/issues/1145)) ([@&#8203;yunaremaia](https://github.com/yunaremaia))
- [`ae346b5`](https://github.com/goreleaser/nfpm/commit/ae346b54a3142aa993cbfd3202cfd6236caa8822): fix(rpm): emit ISA-qualified self provide ([#&#8203;1141](https://github.com/goreleaser/nfpm/issues/1141)) ([@&#8203;djgilcrease](https://github.com/djgilcrease))
- [`d20c0c9`](https://github.com/goreleaser/nfpm/commit/d20c0c9937ed37ff34fedf155468a739baa59cf1): fix(rpm): escape % in generated SRPM spec so scriptlets survive rebuild ([#&#8203;1109](https://github.com/goreleaser/nfpm/issues/1109)) ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`60154f1`](https://github.com/goreleaser/nfpm/commit/60154f160df7af2b2b405c7bf0fde93292909cb7): fix(rpm): set file colors on executable ELF files ([#&#8203;1155](https://github.com/goreleaser/nfpm/issues/1155)) ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`c2b0995`](https://github.com/goreleaser/nfpm/commit/c2b09957b40d5f4391d46b05263b199ad0370dca): fix: Include optional dependencies in Arch packages ([#&#8203;1131](https://github.com/goreleaser/nfpm/issues/1131)) ([@&#8203;fredrikblau](https://github.com/fredrikblau))
- [`db22372`](https://github.com/goreleaser/nfpm/commit/db22372bfbddb6b2968ff71e9c25e6bb1a2355c2): fix: add context to deb and rpm errors ([#&#8203;1088](https://github.com/goreleaser/nfpm/issues/1088)) ([@&#8203;otjdiepluong](https://github.com/otjdiepluong))
- [`5ec5501`](https://github.com/goreleaser/nfpm/commit/5ec5501425dc2cd4ff41b783095cff3e74ed2ebe): fix: don't panic in Config.Get on an empty override clause ([#&#8203;1114](https://github.com/goreleaser/nfpm/issues/1114)) ([@&#8203;arpitjain099](https://github.com/arpitjain099))
- [`ce81cb6`](https://github.com/goreleaser/nfpm/commit/ce81cb64a9e1d5abb252ee7a05e8ea897f4ee32d): fix: update to go-msix v1.0.0 ([#&#8203;1105](https://github.com/goreleaser/nfpm/issues/1105)) ([@&#8203;djgilcrease](https://github.com/djgilcrease))

##### Dependency updates

- [`9da52b4`](https://github.com/goreleaser/nfpm/commit/9da52b452d229bc65d872273a1c598e02b6ef4c2): fix(deps): bump alpine from 3.24.0 to 3.24.1 ([#&#8203;1101](https://github.com/goreleaser/nfpm/issues/1101)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`6e553ae`](https://github.com/goreleaser/nfpm/commit/6e553ae9843798642d3de64957f4d9ba2f0a9aaa): fix(deps): bump alpine from 3.24.0 to 3.24.1 in /testdata/acceptance ([#&#8203;1102](https://github.com/goreleaser/nfpm/issues/1102)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`551ed78`](https://github.com/goreleaser/nfpm/commit/551ed7880ba2dcd1101234f5d451826311c9284c): fix(deps): bump alpine from 3.24.1 to 3.24.2 ([#&#8203;1143](https://github.com/goreleaser/nfpm/issues/1143)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`f65c6cb`](https://github.com/goreleaser/nfpm/commit/f65c6cb7a4779d982e69947fd6d1f347b0c1d97c): fix(deps): bump alpine from 3.24.1 to 3.24.2 in /testdata/acceptance ([#&#8203;1144](https://github.com/goreleaser/nfpm/issues/1144)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`886e929`](https://github.com/goreleaser/nfpm/commit/886e9296b3ba2cf71fb185f9e7c1df1e6e52aaf1): fix(deps): bump fedora from 40 to 44 in /testdata/acceptance ([#&#8203;1084](https://github.com/goreleaser/nfpm/issues/1084)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])

##### Build process updates

- [`b55fa4d`](https://github.com/goreleaser/nfpm/commit/b55fa4da53b6100d70276f26778034f768ece26a): ci(deps): bump actions/checkout from 6.0.3 to 7.0.0 in the actions group ([#&#8203;1100](https://github.com/goreleaser/nfpm/issues/1100)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`bda9b3f`](https://github.com/goreleaser/nfpm/commit/bda9b3f9650b92c5e5aee63009b15f38b4311dfe): ci(deps): bump docker/setup-qemu-action in the actions group ([#&#8203;1134](https://github.com/goreleaser/nfpm/issues/1134)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`2263872`](https://github.com/goreleaser/nfpm/commit/2263872eee22aabe44a86e3a0d16e8e01fe12816): ci(deps): bump the actions group across 1 directory with 9 updates ([#&#8203;1120](https://github.com/goreleaser/nfpm/issues/1120)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`3ab9e89`](https://github.com/goreleaser/nfpm/commit/3ab9e89ab895ea8ba47690dd14304017dff55997): ci(deps): bump the actions group with 2 updates ([#&#8203;1107](https://github.com/goreleaser/nfpm/issues/1107)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`e788e82`](https://github.com/goreleaser/nfpm/commit/e788e822ccd700d8e6089c1041cb309201639399): ci(deps): bump the actions group with 4 updates ([#&#8203;1126](https://github.com/goreleaser/nfpm/issues/1126)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`42066c2`](https://github.com/goreleaser/nfpm/commit/42066c26933f91e8c5f90d6742b156e40db9c442): ci(deps): bump the actions group with 4 updates ([#&#8203;1137](https://github.com/goreleaser/nfpm/issues/1137)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`9215c15`](https://github.com/goreleaser/nfpm/commit/9215c15b82fb843e047a7685a2c45df45a7fcb62): ci(deps): bump the actions group with 5 updates ([#&#8203;1121](https://github.com/goreleaser/nfpm/issues/1121)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`bec8ffc`](https://github.com/goreleaser/nfpm/commit/bec8ffcdcabbf954933491129bad89e39a67163a): ci(deps): bump the actions group with 5 updates ([#&#8203;1130](https://github.com/goreleaser/nfpm/issues/1130)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`2c05c9e`](https://github.com/goreleaser/nfpm/commit/2c05c9e1a5cb7150520a92edf0f2bc9bfbc2d672): ci(deps): bump the actions group with 5 updates ([#&#8203;1148](https://github.com/goreleaser/nfpm/issues/1148)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`8ce4a3a`](https://github.com/goreleaser/nfpm/commit/8ce4a3a1026f24d145071d148a04b1362f9f4f6c): ci(deps): bump the actions group with 6 updates ([#&#8203;1115](https://github.com/goreleaser/nfpm/issues/1115)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`c6abdba`](https://github.com/goreleaser/nfpm/commit/c6abdbaa8b2ff40dcba6e4ec76545038cf264422): ci(deps): bump the actions group with 6 updates ([#&#8203;1128](https://github.com/goreleaser/nfpm/issues/1128)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`a32b892`](https://github.com/goreleaser/nfpm/commit/a32b89262e05e2574d82493c9fae378f6b7f00b7): ci(deps): bump the actions group with 6 updates ([#&#8203;1132](https://github.com/goreleaser/nfpm/issues/1132)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`962cc40`](https://github.com/goreleaser/nfpm/commit/962cc403408c60b44486ae7a7ca7728652cdebf4): ci(deps): bump the actions group with 7 updates ([#&#8203;1139](https://github.com/goreleaser/nfpm/issues/1139)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`6111766`](https://github.com/goreleaser/nfpm/commit/61117664ffea9fa95d8a2ce59e318a6fb34a90d5): ci(deps): bump the actions group with 9 updates ([#&#8203;1111](https://github.com/goreleaser/nfpm/issues/1111)) ([@&#8203;dependabot](https://github.com/dependabot)\[bot])
- [`b935cc6`](https://github.com/goreleaser/nfpm/commit/b935cc66813b70180524d6c69ab559957f3a18a5): ci: Enable merge queue checks ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`eb39b13`](https://github.com/goreleaser/nfpm/commit/eb39b13687a3c7ffb857e3316074b01dff400997): ci: remove ruleguard ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`70b7cb8`](https://github.com/goreleaser/nfpm/commit/70b7cb842063dd0da4e552297e2ee28fe3f3454f): ci: remove workflow dispatch ([@&#8203;caarlos0](https://github.com/caarlos0))

##### Other work

- [`5794bbd`](https://github.com/goreleaser/nfpm/commit/5794bbd723306c63e0464b5d66787c677f7e234b): docs: update cmd docs ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`4b02052`](https://github.com/goreleaser/nfpm/commit/4b020524fb3dd922065c6366826435ce771453d8): docs: update cmd docs ([@&#8203;caarlos0](https://github.com/caarlos0))
- [`b3fc46b`](https://github.com/goreleaser/nfpm/commit/b3fc46b36452a66c73aaee8ab50714f224bf58ed): test(rpm): Stabilize default compression comparison ([#&#8203;1156](https://github.com/goreleaser/nfpm/issues/1156)) ([@&#8203;caarlos0](https://github.com/caarlos0))

**Full Changelog**: <https://github.com/goreleaser/nfpm/compare/v2.47.0...v2.48.0>

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

🚦 **Automerge**: Disabled by config. Please merge this manually once you are satisfied.

♻ **Rebasing**: Whenever PR is behind base branch, or you tick the rebase/retry checkbox.

🔕 **Ignore**: Close this PR and you won't be reminded about this update again.

---

 - [ ] <!-- rebase-check -->If you want to rebase/retry this PR, check this box

---

This PR has been generated by [Mend Renovate CLI](https://github.com/renovatebot/renovate).
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4xNTEuMiIsInVwZGF0ZWRJblZlciI6IjQ0LjE1MS4yIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJtaW5vci11cGRhdGUiLCJyZWxlYXNlLXBhdGgiXX0=-->
