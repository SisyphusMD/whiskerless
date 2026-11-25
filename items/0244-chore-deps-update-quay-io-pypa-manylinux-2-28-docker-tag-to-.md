# #244 chore(deps): update quay.io/pypa/manylinux_2_28 docker tag to v2026.11.21-1

- Kind: pull, state: open, by renovate, created 2026-11-20T23:08:45-08:00
- Labels: none; milestone: none
- renovate/quay.io-pypa-manylinux_2_28-2026.11.x -> main, merged: False

This PR contains the following updates:

| Package | Update | Change |
|---|---|---|
| quay.io/pypa/manylinux_2_28 | patch | `2026.11.14-1` → `2026.11.21-1` |

Held for hand review: the glibc floor check runs in CI, but no check encodes judgement about the toolchain change itself.

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
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yNTcuNiIsInVwZGF0ZWRJblZlciI6IjQ0LjI1Ny42IiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJwYXRjaC11cGRhdGUiXX0=-->


## forgejo-actions, 2026-11-20T23:09:02-08:00

<!-- ai-review -->
**AI review** of `33162679c0`: The one-line manylinux pin update is scoped to the standing Renovate issue and appears covered by existing CI; no correctness, safety, or test defects were found. The only note is that the PR description uses `Refs` rather than the rule-required `Closes` issue-link form.

### Open

- **F1** (suggestion, `packaging/release-pins.env:35`) Issue link syntax does not match rule 6: The PR description says `Refs #211`, but RULES.md rule 6 requires the description to name its issue as `Closes #n` (or `Closes owner/repo#n`). For a standing Renovate issue, either record a decision/exception allowing `Refs` or use the approved link form that satisfies the issue-link gate without closing the standing issue.


Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W3siaWQiOiAiRjEiLCAiZmlsZSI6ICJwYWNrYWdpbmcvcmVsZWFzZS1waW5zLmVudiIsICJsaW5lIjogMzUsICJzZXZlcml0eSI6ICJzdWdnZXN0aW9uIiwgInN0YXR1cyI6ICJvcGVuIiwgInRpdGxlIjogIklzc3VlIGxpbmsgc3ludGF4IGRvZXMgbm90IG1hdGNoIHJ1bGUgNiIsICJkZXRhaWwiOiAiVGhlIFBSIGRlc2NyaXB0aW9uIHNheXMgYFJlZnMgIzIxMWAsIGJ1dCBSVUxFUy5tZCBydWxlIDYgcmVxdWlyZXMgdGhlIGRlc2NyaXB0aW9uIHRvIG5hbWUgaXRzIGlzc3VlIGFzIGBDbG9zZXMgI25gIChvciBgQ2xvc2VzIG93bmVyL3JlcG8jbmApLiBGb3IgYSBzdGFuZGluZyBSZW5vdmF0ZSBpc3N1ZSwgZWl0aGVyIHJlY29yZCBhIGRlY2lzaW9uL2V4Y2VwdGlvbiBhbGxvd2luZyBgUmVmc2Agb3IgdXNlIHRoZSBhcHByb3ZlZCBsaW5rIGZvcm0gdGhhdCBzYXRpc2ZpZXMgdGhlIGlzc3VlLWxpbmsgZ2F0ZSB3aXRob3V0IGNsb3NpbmcgdGhlIHN0YW5kaW5nIGlzc3VlLiIsICJyZXNwb25zZSI6ICIifV0= -->
