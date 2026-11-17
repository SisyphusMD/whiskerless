# #165 fix(deps): update dependency aiohasupervisor to v0.11.0

- Kind: pull, state: closed, by renovate, created 2026-11-13T14:09:34-08:00
- Labels: none; milestone: none
- refs/pull/165/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [aiohasupervisor](https://github.com/home-assistant-libs/python-supervisor-client) | `==0.8.1` → `==0.11.0` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/aiohasupervisor/0.11.0?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/aiohasupervisor/0.8.1/0.11.0?slim=true) |

---

### Release Notes

<details>
<summary>home-assistant-libs/python-supervisor-client (aiohasupervisor)</summary>

### [`v0.11.0`](https://github.com/home-assistant-libs/python-supervisor-client/releases/tag/0.11.0)

[Compare Source](https://github.com/home-assistant-libs/python-supervisor-client/compare/0.10.0...0.11.0)

#### :sparkles: New Features

- [#&#8203;463](https://github.com/home-assistant-libs/python-supervisor-client/issues/463) Add plugin log endpoints [@&#8203;agners](https://github.com/agners)
- [#&#8203;466](https://github.com/home-assistant-libs/python-supervisor-client/issues/466) Add a read timeout option to the log endpoints [@&#8203;agners](https://github.com/agners)

#### :arrow_up: Dependency Updates

<details>
<summary>2 changes</summary>

- [#&#8203;465](https://github.com/home-assistant-libs/python-supervisor-client/issues/465) Bump coverage from 7.17.0 to 7.17.2 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;464](https://github.com/home-assistant-libs/python-supervisor-client/issues/464) Bump ruff from 0.17.3 to 0.17.4 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)

</details>

### [`v0.10.0`](https://github.com/home-assistant-libs/python-supervisor-client/releases/tag/0.10.0)

[Compare Source](https://github.com/home-assistant-libs/python-supervisor-client/compare/0.9.0...0.10.0)

#### :sparkles: New Features

- [#&#8203;455](https://github.com/home-assistant-libs/python-supervisor-client/issues/455) Add deprecated_tcp_api_request issue type [@&#8203;mdegat01](https://github.com/mdegat01)
- [#&#8203;454](https://github.com/home-assistant-libs/python-supervisor-client/issues/454) Add journal log endpoints [@&#8203;agners](https://github.com/agners)

#### :green_heart: CI

- [#&#8203;460](https://github.com/home-assistant-libs/python-supervisor-client/issues/460) Rebuild Python venv in CI jobs on cache miss [@&#8203;agners](https://github.com/agners)

#### :arrow_up: Dependency Updates

<details>
<summary>5 changes</summary>

- [#&#8203;456](https://github.com/home-assistant-libs/python-supervisor-client/issues/456) Bump ruff from 0.17.2 to 0.17.3 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;453](https://github.com/home-assistant-libs/python-supervisor-client/issues/453) Bump pytest-asyncio from 1.4.0 to 1.4.1 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;458](https://github.com/home-assistant-libs/python-supervisor-client/issues/458) Bump mypy from 2.4.0 to 2.4.1 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;457](https://github.com/home-assistant-libs/python-supervisor-client/issues/457) Bump pytest from 9.1.1 to 9.2.0 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;462](https://github.com/home-assistant-libs/python-supervisor-client/issues/462) Bump pytest-asyncio from 1.4.1 to 1.4.1.post1 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)

</details>

### [`v0.9.0`](https://github.com/home-assistant-libs/python-supervisor-client/releases/tag/0.9.0)

[Compare Source](https://github.com/home-assistant-libs/python-supervisor-client/compare/0.8.1...0.9.0)

#### :sparkles: New Features

- [#&#8203;449](https://github.com/home-assistant-libs/python-supervisor-client/issues/449) Add option to connect to Supervisor over a Unix socket [@&#8203;mdegat01](https://github.com/mdegat01)
- [#&#8203;446](https://github.com/home-assistant-libs/python-supervisor-client/issues/446) Add log_format field to InstalledAddonComplete [@&#8203;sairon](https://github.com/sairon)

#### :arrow_up: Dependency Updates

<details>
<summary>4 changes</summary>

- [#&#8203;448](https://github.com/home-assistant-libs/python-supervisor-client/issues/448) Update setuptools requirement from <84.1,>=68.0 to >=68.0,<84.3 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;450](https://github.com/home-assistant-libs/python-supervisor-client/issues/450) Bump actions/setup-python from 7.0.0 to 7.1.0 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;451](https://github.com/home-assistant-libs/python-supervisor-client/issues/451) Bump coverage from 7.16.2 to 7.17.0 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)
- [#&#8203;452](https://github.com/home-assistant-libs/python-supervisor-client/issues/452) Bump ruff from 0.17.1 to 0.17.2 @&#8203;[dependabot\[bot\]](https://github.com/apps/dependabot)

</details>

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
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yMzkuMSIsInVwZGF0ZWRJblZlciI6IjQ0LjIzOS4xIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJtaW5vci11cGRhdGUiXX0=-->
