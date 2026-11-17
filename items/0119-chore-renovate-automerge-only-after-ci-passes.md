# #119 chore(renovate): automerge only after CI passes

- Kind: pull, state: closed, by cody, created 2026-10-09T07:32:50-07:00
- Labels: none; milestone: none
- refs/pull/119/head -> main, merged: True

platformAutomerge: false, so Renovate merges an automerge PR itself once its checks are green. With platform automerge Forgejo merged immediately when main required no checks: archiver #192 (an rclone bump) merged 3 seconds after opening and broke the image build. Cody approved this change across the bryantserver and SisyphusMD repos (2026-10-09).
