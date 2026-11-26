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
**AI review** of `417df2f59f`: Single-line Renovate dependency bump of the manylinux_2_28 Docker image tag and digest in packaging/release-pins.env. The change is minimal, correctly updates both the tag and the SHA-256 digest, and is exercised by the existing CI build jobs. No correctness, security, or data-loss issues found.

### Open

- **F1** (suggestion, `packaging/release-pins.env:35`) Issue link syntax does not match rule 6: The PR description uses `Refs #211`, but RULES.md rule 6 specifies the form `Closes #n`. For a standing issue that must stay open, `Closes` would be wrong, so the project should either record a decision/exception (rule 2) permitting `Refs` for standing Renovate issues, or configure Renovate to use a form the issue-link gate accepts without closing the standing issue. Until that decision exists, the description does not satisfy rule 6 as written.
  - Reviewer: The standing issue #211 itself says 'Each generated PR references this issue so the issue-link gate can verify its scope. Keep this issue open for future updates,' which makes the practical intent clear. However, rule 6 prescribes `Closes #n` and rule 2 requires a recorded decision for exceptions. A one-line decision comment on #211 (e.g. `Decision: Renovate PRs use Refs #211 rather than Closes, because the issue is standing. Why: Closes would close the standing issue. Decided by: <maintainer>, <date>.`) would close this gap cleanly. Not blocking because the gate evidently accepts the form and the behaviour is correct, but the rule text and the practice should be reconciled.


Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W3siaWQiOiAiRjEiLCAiZmlsZSI6ICJwYWNrYWdpbmcvcmVsZWFzZS1waW5zLmVudiIsICJsaW5lIjogMzUsICJzZXZlcml0eSI6ICJzdWdnZXN0aW9uIiwgInN0YXR1cyI6ICJvcGVuIiwgInRpdGxlIjogIklzc3VlIGxpbmsgc3ludGF4IGRvZXMgbm90IG1hdGNoIHJ1bGUgNiIsICJkZXRhaWwiOiAiVGhlIFBSIGRlc2NyaXB0aW9uIHVzZXMgYFJlZnMgIzIxMWAsIGJ1dCBSVUxFUy5tZCBydWxlIDYgc3BlY2lmaWVzIHRoZSBmb3JtIGBDbG9zZXMgI25gLiBGb3IgYSBzdGFuZGluZyBpc3N1ZSB0aGF0IG11c3Qgc3RheSBvcGVuLCBgQ2xvc2VzYCB3b3VsZCBiZSB3cm9uZywgc28gdGhlIHByb2plY3Qgc2hvdWxkIGVpdGhlciByZWNvcmQgYSBkZWNpc2lvbi9leGNlcHRpb24gKHJ1bGUgMikgcGVybWl0dGluZyBgUmVmc2AgZm9yIHN0YW5kaW5nIFJlbm92YXRlIGlzc3Vlcywgb3IgY29uZmlndXJlIFJlbm92YXRlIHRvIHVzZSBhIGZvcm0gdGhlIGlzc3VlLWxpbmsgZ2F0ZSBhY2NlcHRzIHdpdGhvdXQgY2xvc2luZyB0aGUgc3RhbmRpbmcgaXNzdWUuIFVudGlsIHRoYXQgZGVjaXNpb24gZXhpc3RzLCB0aGUgZGVzY3JpcHRpb24gZG9lcyBub3Qgc2F0aXNmeSBydWxlIDYgYXMgd3JpdHRlbi4iLCAicmVzcG9uc2UiOiAiVGhlIHN0YW5kaW5nIGlzc3VlICMyMTEgaXRzZWxmIHNheXMgJ0VhY2ggZ2VuZXJhdGVkIFBSIHJlZmVyZW5jZXMgdGhpcyBpc3N1ZSBzbyB0aGUgaXNzdWUtbGluayBnYXRlIGNhbiB2ZXJpZnkgaXRzIHNjb3BlLiBLZWVwIHRoaXMgaXNzdWUgb3BlbiBmb3IgZnV0dXJlIHVwZGF0ZXMsJyB3aGljaCBtYWtlcyB0aGUgcHJhY3RpY2FsIGludGVudCBjbGVhci4gSG93ZXZlciwgcnVsZSA2IHByZXNjcmliZXMgYENsb3NlcyAjbmAgYW5kIHJ1bGUgMiByZXF1aXJlcyBhIHJlY29yZGVkIGRlY2lzaW9uIGZvciBleGNlcHRpb25zLiBBIG9uZS1saW5lIGRlY2lzaW9uIGNvbW1lbnQgb24gIzIxMSAoZS5nLiBgRGVjaXNpb246IFJlbm92YXRlIFBScyB1c2UgUmVmcyAjMjExIHJhdGhlciB0aGFuIENsb3NlcywgYmVjYXVzZSB0aGUgaXNzdWUgaXMgc3RhbmRpbmcuIFdoeTogQ2xvc2VzIHdvdWxkIGNsb3NlIHRoZSBzdGFuZGluZyBpc3N1ZS4gRGVjaWRlZCBieTogPG1haW50YWluZXI+LCA8ZGF0ZT4uYCkgd291bGQgY2xvc2UgdGhpcyBnYXAgY2xlYW5seS4gTm90IGJsb2NraW5nIGJlY2F1c2UgdGhlIGdhdGUgZXZpZGVudGx5IGFjY2VwdHMgdGhlIGZvcm0gYW5kIHRoZSBiZWhhdmlvdXIgaXMgY29ycmVjdCwgYnV0IHRoZSBydWxlIHRleHQgYW5kIHRoZSBwcmFjdGljZSBzaG91bGQgYmUgcmVjb25jaWxlZC4ifV0= -->
