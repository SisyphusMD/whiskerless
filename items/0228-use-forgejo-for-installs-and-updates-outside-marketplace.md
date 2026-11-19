# #228 Use Forgejo for installs and updates outside Marketplace

- Kind: issue, state: open, by cody, created 2026-11-18T06:33:50-08:00
- Labels: status:blocked, type:chore; milestone: none

Default the Homebrew tap, standalone blueprint, CLI release checks, project help and package metadata to the primary. Retain the public GitHub integration repository for Marketplace/HACS and the full mirror.

## cody, 2026-11-18T06:53:22-08:00

The local patch uses Forgejo for the tap, CLI lookups, help and notification blueprint. The GitHub mirror still supplies the Home Assistant integration for Marketplace and HACS. The notification blueprint passes all eight tests on Home Assistant 2026.11.2. The three v0.2.0-rc.78 bottles on the primary match the formula. Stable v0.1.3 predates the first stable formula. Landing waits for successful public tap access and artifact downloads, which currently return HTTP 500.
