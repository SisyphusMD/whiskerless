# #100 feat(ci): retry a run the runner's resolver failed inside one of our steps

- Kind: pull, state: closed, by cody, created 2026-09-16T07:51:53-07:00
- Labels: none; milestone: none
- refs/pull/100/head -> main, merged: True

GitHub run 35055059591 stayed red: `brew test` bootstrapped Homebrew's Ruby harness and the x86_64 macOS runner could not resolve rubygems.org. The failure landed in our named step, so the step-name rule refused the retry.

Vendors project-standard v0.1.25, whose discriminator now reads each failed job's log and retries only when the failed step's own closing lines carry an exact resolver-failure spelling and name a host CI is known to reach. The workflow downloads one log per failed job (`gh api --allow-escape-sequences`, without which `gh` refuses ANSI-coloured bodies) and passes the directory through. The invariant test pins the fetch and the flag, and the sibling's `the triage is the shared one` test is mirrored here, which whiskerless had been missing.

Same change lands in dreame-valetudo.
