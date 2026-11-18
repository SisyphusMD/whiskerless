# #224 Publish Homebrew Tap updates through pull requests

- Kind: issue, state: closed, by cody, created 2026-11-17T18:50:19-08:00
- Labels: status:in-progress, type:chore; milestone: none

Part of SisyphusMD/homebrew-tap#3. Isolate formula rendering from the tap write credential, submit the formula and bottles as normal pull requests, and wait until the intended files land before downstream install verification or pruning. Keep the existing manual bottle repair path.

Depends on SisyphusMD/homebrew-tap#7.

## cody, 2026-11-17T20:17:28-08:00

PR #227 settled at 903e4d20c622907b490f952ca0035782cac540b6. All exact-head native and shared checks passed and both mirrors match. The first real Tap publisher proof is tracked under homebrew-tap #3 and requires the separately approved v0.2.0-rc.78.
