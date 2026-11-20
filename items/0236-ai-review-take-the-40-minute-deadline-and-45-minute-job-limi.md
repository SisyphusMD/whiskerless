# #236 AI review: take the 40-minute deadline and 45-minute job limit from project-rules

- Kind: issue, state: closed, by cody, created 2026-11-19T17:41:24-08:00
- Labels: status:in-progress, type:bug; milestone: none

Copy of the canonical AI review from SisyphusMD/project-rules#108 (issue SisyphusMD/project-rules#55). Reviews at the 40,000-token cap could outlast the 20-minute job, which was then killed with the required check left pending. Now a 40-minute deadline ends the review with an error status, inside a 45-minute job. Cody approved the 45-minute limit on 2026-11-19.
