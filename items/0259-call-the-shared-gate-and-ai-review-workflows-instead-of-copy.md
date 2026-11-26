# #259 Call the shared gate and AI review workflows instead of copying them

- Kind: issue, state: closed, by cody, created 2026-11-25T21:28:48-08:00
- Labels: status:in-progress, type:chore; milestone: none

Part of SisyphusMD/project-rules#78: this repo's ci.yml and ai-review.yml become small callers of project-rules main's gate.yml, gate-lint.yml and review.yml, proven in SisyphusMD/homebrew-tap#34, so the jobs stop being copies here. Check names stay the same.

Claude has this.

## cody, 2026-11-25T22:20:06-08:00

Done in #260: ci.yml and ai-review.yml now call project-rules main's shared gate and review jobs, so only the small callers are copied here. Its workflow-security test now excuses the calling jobs instead of the copied ones. Check names are unchanged; the next PR here is the first to run on the callers. Nothing left on this issue.
