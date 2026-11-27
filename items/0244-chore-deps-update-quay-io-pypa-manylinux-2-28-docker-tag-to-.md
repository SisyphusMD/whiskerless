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
**AI review** of `649d4917d8`: Single-line Renovate bump of the manylinux_2_28 build image (tag + digest). The change is correct, minimal, and exercised by existing CI build jobs. The only open item is the pre-existing suggestion about `Refs` vs `Closes` syntax for standing issues.

### Open

- **F1** (suggestion, `packaging/release-pins.env:35`) Issue link syntax does not match rule 6: The PR description uses `Refs #211`, but RULES.md rule 6 specifies the form `Closes #n`. For a standing issue that must stay open, `Closes` would be wrong, so the project should either record a decision/exception (rule 2) permitting `Refs` for standing Renovate issues, or configure Renovate to use a form the issue-link gate accepts without closing the standing issue. Until that decision exists, the description does not satisfy rule 6 as written.
  - Reviewer: No new reply on the PR addresses this. The finding stands as a suggestion: a one-line `Decision:` comment on #211 recording that Renovate PRs use `Refs` rather than `Closes` (because the issue is standing) would reconcile the rule text with the practice and close the gap permanently.


Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W3siaWQiOiAiRjEiLCAiZmlsZSI6ICJwYWNrYWdpbmcvcmVsZWFzZS1waW5zLmVudiIsICJsaW5lIjogMzUsICJzZXZlcml0eSI6ICJzdWdnZXN0aW9uIiwgInN0YXR1cyI6ICJvcGVuIiwgInRpdGxlIjogIklzc3VlIGxpbmsgc3ludGF4IGRvZXMgbm90IG1hdGNoIHJ1bGUgNiIsICJkZXRhaWwiOiAiVGhlIFBSIGRlc2NyaXB0aW9uIHVzZXMgYFJlZnMgIzIxMWAsIGJ1dCBSVUxFUy5tZCBydWxlIDYgc3BlY2lmaWVzIHRoZSBmb3JtIGBDbG9zZXMgI25gLiBGb3IgYSBzdGFuZGluZyBpc3N1ZSB0aGF0IG11c3Qgc3RheSBvcGVuLCBgQ2xvc2VzYCB3b3VsZCBiZSB3cm9uZywgc28gdGhlIHByb2plY3Qgc2hvdWxkIGVpdGhlciByZWNvcmQgYSBkZWNpc2lvbi9leGNlcHRpb24gKHJ1bGUgMikgcGVybWl0dGluZyBgUmVmc2AgZm9yIHN0YW5kaW5nIFJlbm92YXRlIGlzc3Vlcywgb3IgY29uZmlndXJlIFJlbm92YXRlIHRvIHVzZSBhIGZvcm0gdGhlIGlzc3VlLWxpbmsgZ2F0ZSBhY2NlcHRzIHdpdGhvdXQgY2xvc2luZyB0aGUgc3RhbmRpbmcgaXNzdWUuIFVudGlsIHRoYXQgZGVjaXNpb24gZXhpc3RzLCB0aGUgZGVzY3JpcHRpb24gZG9lcyBub3Qgc2F0aXNmeSBydWxlIDYgYXMgd3JpdHRlbi4iLCAicmVzcG9uc2UiOiAiTm8gbmV3IHJlcGx5IG9uIHRoZSBQUiBhZGRyZXNzZXMgdGhpcy4gVGhlIGZpbmRpbmcgc3RhbmRzIGFzIGEgc3VnZ2VzdGlvbjogYSBvbmUtbGluZSBgRGVjaXNpb246YCBjb21tZW50IG9uICMyMTEgcmVjb3JkaW5nIHRoYXQgUmVub3ZhdGUgUFJzIHVzZSBgUmVmc2AgcmF0aGVyIHRoYW4gYENsb3Nlc2AgKGJlY2F1c2UgdGhlIGlzc3VlIGlzIHN0YW5kaW5nKSB3b3VsZCByZWNvbmNpbGUgdGhlIHJ1bGUgdGV4dCB3aXRoIHRoZSBwcmFjdGljZSBhbmQgY2xvc2UgdGhlIGdhcCBwZXJtYW5lbnRseS4ifV0= -->
