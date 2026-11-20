# #235 Take each robot model's provisioning profile in the shared BLE setup

- Kind: pull, state: open, by cody, created 2026-11-19T16:49:51-08:00
- Labels: none; milestone: none
- chore/217-ble-provisioning-profile -> main, merged: False

Closes #217

The BLE provisioning code in `ble/` assumed every robot was an LR4: it held the LR4 service UUID and advertised name, checked for LR4 serials and built `prod/LR4/...` topics. PR #188 extends those checks to accept the EVO as well, which would add one branch per model inside the shared sequence.

Now each model supplies a `ProvisioningProfile` (service UUID, advertised name, serial check, default topics). The LR4's profile lives in `devices/litter_robot_4/provisioning.py`, moved verbatim from `ble/`. `scan()`, `read_device_mac()` and `ProvisioningConfig` take it as a keyword argument, and `whiskerless provision` passes the LR4 profile. The command's prompts, serial validation, explicit `--address` selection and the check that the connected device exposes the LR4 provisioning service before the first write are unchanged.

New tests drive the shared sequence with a made-up model: they reject a scan that offers an LR4 when another model is being provisioned, a connection to an LR4 under that other profile, and any serial or topic that does not come from the profile. The existing LR4 discovery, explicit-address and provisioning tests now run through the LR4 profile.

Library callers of these three functions must pass `profile=`; the CHANGELOG says so. Splitting `cli.py` is #234.

Still to do before merge: provision a real LR4 with this branch and confirm it connects to the broker (#217).


## forgejo-actions, 2026-11-19T16:53:37-08:00

<!-- ai-review -->
**AI review** of `8a088d9dfe`: Clean extraction of model-specific provisioning details into a `ProvisioningProfile` interface, with the LR4 profile moved to `devices/litter_robot_4/provisioning.py`. The shared BLE code no longer names any model, the CLI passes the LR4 profile explicitly, and new tests verify cross-model rejection and profile-driven behaviour. Docs and CHANGELOG are updated in the same PR.

### Withdrawn

- **F1** (suggestion, `src/whiskerless/ble/provision.py:215`) Removed public `ProvisioningConfig.check_serial` without a deprecation shim: Cody's reply is correct: `ProvisioningConfig` lives in `whiskerless.ble.__all__`, which is neither `whiskerless.__all__` nor a `whiskerless.devices.<device>.__all__` submodule. CONTRIBUTING.md's compatibility promise explicitly says everything else 'is internal and may be renamed, moved or deleted without notice.' The bundled integration never imports `whiskerless.ble` (the invariant test would catch it). No shim is required, and adding one would reintroduce an LR4-specific rule into `ble/`, which is exactly what #217 removes.
  - Reviewer: Withdrawn. The compatibility promise does not cover `whiskerless.ble`; the removal is within the stated 'may be deleted without notice' scope.


Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W3siaWQiOiAiRjEiLCAiZmlsZSI6ICJzcmMvd2hpc2tlcmxlc3MvYmxlL3Byb3Zpc2lvbi5weSIsICJsaW5lIjogMjE1LCAic2V2ZXJpdHkiOiAic3VnZ2VzdGlvbiIsICJzdGF0dXMiOiAid2l0aGRyYXduIiwgInRpdGxlIjogIlJlbW92ZWQgcHVibGljIGBQcm92aXNpb25pbmdDb25maWcuY2hlY2tfc2VyaWFsYCB3aXRob3V0IGEgZGVwcmVjYXRpb24gc2hpbSIsICJkZXRhaWwiOiAiQ29keSdzIHJlcGx5IGlzIGNvcnJlY3Q6IGBQcm92aXNpb25pbmdDb25maWdgIGxpdmVzIGluIGB3aGlza2VybGVzcy5ibGUuX19hbGxfX2AsIHdoaWNoIGlzIG5laXRoZXIgYHdoaXNrZXJsZXNzLl9fYWxsX19gIG5vciBhIGB3aGlza2VybGVzcy5kZXZpY2VzLjxkZXZpY2U+Ll9fYWxsX19gIHN1Ym1vZHVsZS4gQ09OVFJJQlVUSU5HLm1kJ3MgY29tcGF0aWJpbGl0eSBwcm9taXNlIGV4cGxpY2l0bHkgc2F5cyBldmVyeXRoaW5nIGVsc2UgJ2lzIGludGVybmFsIGFuZCBtYXkgYmUgcmVuYW1lZCwgbW92ZWQgb3IgZGVsZXRlZCB3aXRob3V0IG5vdGljZS4nIFRoZSBidW5kbGVkIGludGVncmF0aW9uIG5ldmVyIGltcG9ydHMgYHdoaXNrZXJsZXNzLmJsZWAgKHRoZSBpbnZhcmlhbnQgdGVzdCB3b3VsZCBjYXRjaCBpdCkuIE5vIHNoaW0gaXMgcmVxdWlyZWQsIGFuZCBhZGRpbmcgb25lIHdvdWxkIHJlaW50cm9kdWNlIGFuIExSNC1zcGVjaWZpYyBydWxlIGludG8gYGJsZS9gLCB3aGljaCBpcyBleGFjdGx5IHdoYXQgIzIxNyByZW1vdmVzLiIsICJyZXNwb25zZSI6ICJXaXRoZHJhd24uIFRoZSBjb21wYXRpYmlsaXR5IHByb21pc2UgZG9lcyBub3QgY292ZXIgYHdoaXNrZXJsZXNzLmJsZWA7IHRoZSByZW1vdmFsIGlzIHdpdGhpbiB0aGUgc3RhdGVkICdtYXkgYmUgZGVsZXRlZCB3aXRob3V0IG5vdGljZScgc2NvcGUuIn1d -->

## cody, 2026-11-19T17:04:23-08:00

F1: no shim, because `whiskerless.ble` is outside the compatibility promise. CONTRIBUTING.md ("The Python API — a compatibility promise") covers only `whiskerless.__all__` and each `whiskerless.devices.<device>.__all__` with the submodules it re-exports; it says everything else "is internal and may be renamed, moved or deleted without notice". `ProvisioningConfig` is in `whiskerless.ble.__all__`, not in either promised surface, and the bundled integration never imports `whiskerless.ble` (the repo invariant test would fail if it did). The CHANGELOG entry is a courtesy for anyone driving the library directly, not a deprecation window. A shim on `ProvisioningConfig` would also put an LR4 rule back into `ble/`, which is what #217 removes.
