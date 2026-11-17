# Project rules

These rules apply to every SisyphusMD repository, public or private, and to everyone who works in
one: the maintainer, agents working for the maintainer, and outside contributors. A repo's
`CONTRIBUTING.md` adds what is specific to it (how to run its tests, what counts as a test there,
its safety-critical code). It never loosens a rule; exceptions are listed at the end of this file
and nowhere else. How code, tests and docs are written is in [conventions/][conventions].

## Issues and decisions

1. **No work without an issue.** A request, idea or tangent becomes an issue, or a comment on
   an existing one, before anything is built. A request raised mid-task is filed, its number
   given, and the current task resumes.
2. **Decisions are issue comments**, one per comment: `Decision: <what>. Why: <why>.` then
   `Decided by: <who>, <YYYY-MM-DD>.` The maintainer decides (on a shared project, its named
   owners). Anyone may propose; an agent's own technical call is a comment labelled
   `Technical call:` so it is easy to revisit.
3. **Decisions that shape a whole system** also get a record in `docs/decisions/NNNN-*.md`
   linking its issue. A record is never edited after merge; a later one supersedes it.
4. **The roadmap is the issue list.** Ideas not ready to build carry `roadmap`; phases are
   milestones. Dependencies are explicit: `Depends on #n` in the body and `status:blocked`
   until it merges, then `status:ready`.
5. **One owner at a time.** Before starting an issue, set `status:in-progress` and comment who
   has it. Work starts from the open issues and their latest comments, never from memory, and
   ends with one status comment per issue it touched.

## Pull requests

6. **Every change lands as a pull request** into a protected `main`, and its description names
   its issue: `Closes #n`, or `Closes owner/repo#n` for an issue in another repo.
7. **One concern per PR.** Every hunk maps to the issue or to something the change cannot work
   without. Independently useful fixes, cleanups or speedups are separate PRs, even when they
   touch the same file. A list of audit findings is not one PR.
8. **The smallest correct diff.** Keep added and deleted lines both small: no unrelated
   cleanup, renaming, reformatting, new abstractions or drive-by refactors. Follow the repo's
   existing patterns over personal style. A PR over 400 changed lines, not counting tests
   and lockfiles, fails `Diff size` unless its description says `Large diff: <reason>`
   (generated code, for one), which the AI review judges.
9. **Describe the actual change.** Lead with the trigger, what went wrong and what happens
   now; say what the new test rejects, not how many tests passed. No stock intros, summaries
   or claims like "improves reliability" without the specific behaviour. **No AI attribution**:
   commit messages and trailers, PR titles and descriptions, and issue and PR comments carry no
   `Co-Authored-By` for an assistant, no "Generated with …" line, no 🤖 and no AI tool named as
   an author. Whoever submits the change is its author and answers for every line. The required
   AI review's own comments and a rule 2 `Technical call:` label are not attribution.
10. **Docs change in the same PR** as the behaviour they describe. Comments and docs state only
    what the code guarantees: limits as upper bounds, no timing the code does not enforce.
11. **Run the repo's declared checks before opening the PR**, plus the linter for each changed
    file type (actionlint for workflows, shellcheck for shell, markdownlint for docs).

## Tests

12. **Every feature or fix ships with tests.** A bug fix includes a test proven to fail
    without the fix: run it against the old code, then the new, and check the failure comes
    from the defect, not broken setup. Assert what the real code produces, not a value the
    test or its mock supplied. Pin time zones and env flags the test depends on. A check that
    has never been seen to fail is not evidence ([conventions/code.md][code]).
13. **Coverage stays at 99%** (branch coverage) overall and **100%** on the safety-critical
    code the repo's `CONTRIBUTING.md` names. `# pragma: no cover` needs a reason on its line.
    Where code can only be tested on real hardware, `CONTRIBUTING.md` says what counts as its
    test and how it runs.
14. **Check the bug classes reviews keep catching** wherever they apply: lease or claim expiry
    and overlapping runs, DST and time zones, route-prefix collisions, giving up after one
    transient failure, and the status codes and input validation of every endpoint touched.

## Review and merge

15. **Required checks**: `Issue link`, `Tests with code`, `Diff size`, `Lint`, `Secrets` and
    `AI review`, plus the repo's own tests and coverage. They run from `main`'s copy
    (`pull_request_target`), never run the PR's code, and fail closed, so a PR cannot weaken
    the check that judges it.
16. **AI review findings**: fix what is real and push. When a finding is wrong, reply on the PR
    with the reason (the code is correct, the case cannot occur, a decision requires it, or
    the cost outweighs the risk); it re-reviews. Taste and "temporary" are not reasons. A
    blocking finding it keeps goes to the maintainer; never route around it.
17. **Read the whole review** (every comment, finding and check) before reporting its outcome.
18. **Merge one PR at a time**, then clean up once `main` provably contains the PR's head:
    delete its branch on the server and locally, prune, fast-forward every local `main`
    checkout, remove the worktrees and scratch files the work used, move the issues it
    unblocked to `status:ready`, and leave the status comment on its issue. Never delete a
    branch `main` does not contain; ask instead.
19. **`main` is protected**: no direct pushes, admins included; the branch must be up to date;
    0 approvals, because the checks and the AI review are the gate.
20. **Break-glass.** When a required check cannot run (its model host or the runners are down),
    the maintainer removes only that check from `main`'s required list, merges what is urgent,
    puts it back, and comments on the issue what was merged without it. When the forge itself
    is down nothing merges at all.

## Every repo

21. **The primary is forgejo.bryantserver.com.** Each repo has a push mirror on the maintainer's
    backup forge, synced on every commit, and a nightly `issue-archive` branch that carries its
    issues and PRs there too, because mirrors carry git only. A public repo's GitHub copy is a
    read-only mirror: issues and pull requests are opened on Forgejo, and the mirror-lockdown
    workflow closes any pull request opened there with a pointer to Forgejo.
22. **A `CONTRIBUTING.md` and a `SECURITY.md`.** The first points here, from
    [templates/CONTRIBUTING.md][contributing-template]; the second is copied from
    `templates/SECURITY.md`, so vulnerabilities are reported privately. Plus a synced copy of this
    file at `.forgejo/RULES.md`, which the AI review reads.
23. **A public repo's checks never see private data.** Its CI reads other repos anonymously, so
    a linked private issue is reported as not found rather than quoted in a public log or
    review.

## Changing these rules

A PR to this repo that closes an issue here, with the maintainer's decision recorded on it.

## Exceptions

| Who or what | Exception | Decided |
| --- | --- | --- |
| Security fixes | Until the fix is released, the issue lives in a private repo (linked as `Closes owner/repo#n`, rule 23) and the PR describes the change, not how to exploit it | #62 |

<!-- Absolute, not relative: every repo carries this file as .forgejo/RULES.md, where a relative
     link points at nothing. tests/test_rules_links.py checks that this repo's targets exist. -->
[conventions]: https://forgejo.bryantserver.com/SisyphusMD/project-rules/src/branch/main/conventions/
[code]: https://forgejo.bryantserver.com/SisyphusMD/project-rules/src/branch/main/conventions/code.md
[contributing-template]: https://forgejo.bryantserver.com/SisyphusMD/project-rules/src/branch/main/templates/CONTRIBUTING.md
