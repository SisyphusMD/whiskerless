# #50 Let apt retry a dropped mirror fetch

- Kind: pull, state: closed, by cody, created 2026-08-25T18:13:29-07:00
- Labels: none; milestone: none
- refs/pull/50/head -> main, merged: True

A mirror that drops a connection mid-fetch is not this project failing, but apt treats it as fatal and the whole install leg goes red for it — observed on `ports.ubuntu.com` during the rc.48 arm64 matrix, where `deb-file-ubuntu` and `deb-file-ubuntu-floor` both died on `Failed to fetch`.

Retries are set as apt POLICY (`Acquire::Retries "3"` in `/etc/apt/apt.conf.d/`) in every stage that runs `apt-get update`, so all derived stages inherit it and a new leg cannot forget.

Deliberately NOT done by widening `triage-infra-failure.py`: that script only treats runner-phase failures as infrastructure, and its own reasoning is that broadening it would become a way to launder flaky tests into green builds. Making the fetch survive the network is a different thing from excusing a failure — a package that genuinely does not install still fails.

Verified in a real ubuntu:22.04 arm64 container (`apt-config dump` shows the policy active, install succeeds). The new invariant asserts no `apt-get update` exists without the policy, and refuses to pass if its own scan finds nothing.
