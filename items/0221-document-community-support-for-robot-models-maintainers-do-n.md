# #221 Document community support for robot models maintainers do not own

- Kind: issue, state: open, by cody, created 2026-11-17T15:19:39-08:00
- Labels: status:ready, type:chore; milestone: none

Define community support for every robot model that the project maintainers do not own. Before listing a model as community-supported, name an owner of that hardware who agrees to reproduce device-specific issues and test future changes on a real unit. A preview can have a tester who tries builds before committing to ongoing support.

Document these responsibilities in `CONTRIBUTING.md` and identify community-supported models in the supported-models list. The project maintainer retains merge and release decisions. Changes to shared setup code still need hardware checks on affected models.

This policy applies across whiskerless, including the EVO proposal in #188.
