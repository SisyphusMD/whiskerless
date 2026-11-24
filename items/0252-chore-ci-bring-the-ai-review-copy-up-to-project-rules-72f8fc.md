# #252 chore(ci): bring the AI review copy up to project-rules 72f8fcc

- Kind: issue, state: closed, by cody, created 2026-11-23T21:03:35-08:00
- Labels: type:chore; milestone: none

Copy the AI review script from canonical SisyphusMD/project-rules 72f8fcc (SisyphusMD/project-rules#121, PR #122). An answer cut off at the output cap while still reasoning is asked once more under the answer schema, instead of failing the check. Before this, a small PR could spend the whole cap reasoning on every run and never get a review (seen on bryantserver/k8s#2688). The script will be byte-for-byte canonical, and ai-review.yml stays unchanged. Rollout tracked on SisyphusMD/project-rules#113. Cody approved the rollout on 2026-11-23.

## cody, 2026-11-23T22:05:19-08:00

Done: PR 253 merged at f0b565d4 and verified on main. ai-review.py is byte-for-byte canonical project-rules 72f8fcc, and ai-review.yml is unchanged. Its own AI review passed. Nothing left.
