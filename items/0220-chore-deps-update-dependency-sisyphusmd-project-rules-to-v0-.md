# #220 chore(deps): update dependency sisyphusmd/project-rules to v0.3.1 - autoclosed

- Kind: pull, state: closed, by renovate, created 2026-11-17T15:09:25-08:00
- Labels: none; milestone: none
- refs/pull/220/head -> main, merged: False

This PR contains the following updates:

| Package | Update | Change |
|---|---|---|
| [SisyphusMD/project-rules](https://forgejo.bryantserver.com/SisyphusMD/project-rules) | patch | `0.3.0` → `0.3.1` |

`refresh-pins.sh` re-vendors the standard at this tag on this branch, so the files and the lock should already agree with the pin. If the drift check still fails, the re-vendor did not run - check the task's output rather than re-vendoring by hand, because a manual fix here hides a broken automation.

---

### Release Notes

<details>
<summary>SisyphusMD/project-rules</summary>

### [`v0.3.1`](https://forgejo.bryantserver.com/SisyphusMD/project-rules/compare/v0.3.0...v0.3.1)

[Compare Source](https://forgejo.bryantserver.com/SisyphusMD/project-rules/compare/v0.3.0...v0.3.1)

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

Refs #211: standing issue for dependency updates.

No tests: dependency pins and their generated files are checked by the existing build and test jobs.
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yNTEuMCIsInVwZGF0ZWRJblZlciI6IjQ0LjI1MS4wIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJwYXRjaC11cGRhdGUiXX0=-->


## forgejo-actions, 2026-11-17T15:09:49-08:00

<!-- ai-review -->
**AI review** of `da7f8c8d6c`: Straightforward Renovate re-vendor of project-rules v0.3.0→v0.3.1: updated STANDARD.lock hashes, comment rewording in several packaging scripts, a new --merged-commit mode in push-tag.sh, and a new verify-release-pr.py. All changes originate from the upstream tag; the existing sync check and build jobs cover them.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
