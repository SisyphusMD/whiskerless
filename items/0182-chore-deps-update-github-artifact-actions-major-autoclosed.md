# #182 chore(deps): update github artifact actions (major) - autoclosed

- Kind: pull, state: closed, by renovate, created 2026-11-17T00:08:10-08:00
- Labels: none; milestone: none
- refs/pull/182/head -> main, merged: False

This PR contains the following updates:

| Package | Type | Update | Change |
|---|---|---|---|
| [actions/download-artifact](https://github.com/actions/download-artifact) | action | major | `v3.1.0` → `v8.0.2` |
| [actions/upload-artifact](https://github.com/actions/upload-artifact) | action | major | `v3.2.2` → `v7.0.2` |

---

### Release Notes

<details>
<summary>actions/download-artifact</summary>

### [`v8.0.2`](https://github.com/actions/download-artifact/releases/tag/v8.0.2)

[Compare Source](https://github.com/actions/download-artifact/compare/v8.0.1...v8.0.2)

##### What's Changed

- Update the readme by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;473](https://github.com/actions/download-artifact/pull/473)
- Improves artifact download retries when the service returns HTTP 429 (rate limiting), including honoring valid Retry-After headers.
- Update [@&#8203;actions/artifact](https://github.com/actions/artifact) to 6.3.1 by [@&#8203;tunc-d](https://github.com/tunc-d) in [#&#8203;492](https://github.com/actions/download-artifact/pull/492)
- Prepare download-artifact v8.0.2 by [@&#8203;tunc-d](https://github.com/tunc-d) in [#&#8203;493](https://github.com/actions/download-artifact/pull/493)

##### New Contributors

- [@&#8203;tunc-d](https://github.com/tunc-d) made their first contribution in [#&#8203;492](https://github.com/actions/download-artifact/pull/492)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v8.0.1...v8.0.2>

### [`v8.0.1`](https://github.com/actions/download-artifact/releases/tag/v8.0.1)

[Compare Source](https://github.com/actions/download-artifact/compare/v8.0.0...v8.0.1)

##### What's Changed

- Support for CJK characters in the artifact name by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;471](https://github.com/actions/download-artifact/pull/471)
- Add a regression test for artifact name + content-type mismatches by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;472](https://github.com/actions/download-artifact/pull/472)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v8...v8.0.1>

### [`v8.0.0`](https://github.com/actions/download-artifact/releases/tag/v8.0.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v7.0.0...v8.0.0)

##### v8 - What's new

> \[!IMPORTANT]
> actions/download-artifact\@&#8203;v8 has been migrated to an ESM module. This should be transparent to the caller but forks might need to make significant changes.

> \[!IMPORTANT]
> Hash mismatches will now error by default. Users can override this behavior with a setting change (see below).

##### Direct downloads

To support direct uploads in `actions/upload-artifact`, the action will no longer attempt to unzip all downloaded files. Instead, the action checks the `Content-Type` header ahead of unzipping and skips non-zipped files. Callers wishing to download a zipped file as-is can also set the new `skip-decompress` parameter to `true`.

##### Enforced checks (breaking)

A previous release introduced digest checks on the download. If a download hash didn't match the expected hash from the server, the action would log a warning. Callers can now configure the behavior on mismatch with the `digest-mismatch` parameter. To be secure by default, we are now defaulting the behavior to `error` which will fail the workflow run.

##### ESM

To support new versions of the @&#8203;actions/\* packages, we've upgraded the package to ESM.

##### What's Changed

- Don't attempt to un-zip non-zipped downloads by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;460](https://github.com/actions/download-artifact/pull/460)
- Add a setting to specify what to do on hash mismatch and default it to `error` by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;461](https://github.com/actions/download-artifact/pull/461)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v7...v8.0.0>

### [`v7.0.0`](https://github.com/actions/download-artifact/releases/tag/v7.0.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v6.0.0...v7.0.0)

##### v7 - What's new

> \[!IMPORTANT]
> actions/download-artifact\@&#8203;v7 now runs on Node.js 24 (`runs.using: node24`) and requires a minimum Actions Runner version of 2.327.1. If you are using self-hosted runners, ensure they are updated before upgrading.

##### Node.js 24

This release updates the runtime to Node.js 24. v6 had preliminary support for Node 24, however this action was by default still running on Node.js 20. Now this action by default will run on Node.js 24.

##### What's Changed

- Update GHES guidance to include reference to Node 20 version by [@&#8203;patrikpolyak](https://github.com/patrikpolyak) in [#&#8203;440](https://github.com/actions/download-artifact/pull/440)
- Download Artifact Node24 support by [@&#8203;salmanmkc](https://github.com/salmanmkc) in [#&#8203;415](https://github.com/actions/download-artifact/pull/415)
- fix: update [@&#8203;actions/artifact](https://github.com/actions/artifact) to fix Node.js 24 punycode deprecation by [@&#8203;salmanmkc](https://github.com/salmanmkc) in [#&#8203;451](https://github.com/actions/download-artifact/pull/451)
- prepare release v7.0.0 for Node.js 24 support by [@&#8203;salmanmkc](https://github.com/salmanmkc) in [#&#8203;452](https://github.com/actions/download-artifact/pull/452)

##### New Contributors

- [@&#8203;patrikpolyak](https://github.com/patrikpolyak) made their first contribution in [#&#8203;440](https://github.com/actions/download-artifact/pull/440)
- [@&#8203;salmanmkc](https://github.com/salmanmkc) made their first contribution in [#&#8203;415](https://github.com/actions/download-artifact/pull/415)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v6.0.0...v7.0.0>

### [`v6.0.0`](https://github.com/actions/download-artifact/releases/tag/v6.0.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v5.0.0...v6.0.0)

##### What's Changed

**BREAKING CHANGE:** this update supports Node `v24.x`. This is not a breaking change per-se but we're treating it as such.

- Update README for download-artifact v5 changes by [@&#8203;yacaovsnc](https://github.com/yacaovsnc) in [#&#8203;417](https://github.com/actions/download-artifact/pull/417)
- Update README with artifact extraction details by [@&#8203;yacaovsnc](https://github.com/yacaovsnc) in [#&#8203;424](https://github.com/actions/download-artifact/pull/424)
- Readme: spell out the first use of GHES by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;431](https://github.com/actions/download-artifact/pull/431)
- Bump `@actions/artifact` to `v4.0.0`
- Prepare `v6.0.0` by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;438](https://github.com/actions/download-artifact/pull/438)

##### New Contributors

- [@&#8203;danwkennedy](https://github.com/danwkennedy) made their first contribution in [#&#8203;431](https://github.com/actions/download-artifact/pull/431)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v5...v6.0.0>

### [`v5.0.0`](https://github.com/actions/download-artifact/releases/tag/v5.0.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.3.0...v5.0.0)

##### What's Changed

- Update README.md by [@&#8203;nebuk89](https://github.com/nebuk89) in [#&#8203;407](https://github.com/actions/download-artifact/pull/407)
- BREAKING fix: inconsistent path behavior for single artifact downloads by ID by [@&#8203;GrantBirki](https://github.com/GrantBirki) in [#&#8203;416](https://github.com/actions/download-artifact/pull/416)

##### v5.0.0

##### 🚨 Breaking Change

This release fixes an inconsistency in path behavior for single artifact downloads by ID. **If you're downloading single artifacts by ID, the output path may change.**

##### What Changed

Previously, **single artifact downloads** behaved differently depending on how you specified the artifact:

- **By name**: `name: my-artifact` → extracted to `path/` (direct)
- **By ID**: `artifact-ids: 12345` → extracted to `path/my-artifact/` (nested)

Now both methods are consistent:

- **By name**: `name: my-artifact` → extracted to `path/` (unchanged)
- **By ID**: `artifact-ids: 12345` → extracted to `path/` (fixed - now direct)

##### Migration Guide

##### ✅ No Action Needed If:

- You download artifacts by **name**
- You download **multiple** artifacts by ID
- You already use `merge-multiple: true` as a workaround

##### ⚠️ Action Required If:

You download **single artifacts by ID** and your workflows expect the nested directory structure.

**Before v5 (nested structure):**

```yaml
- uses: actions/download-artifact@v4
  with:
    artifact-ids: 12345
    path: dist

# Files were in: dist/my-artifact/
```

> Where `my-artifact` is the name of the artifact you previously uploaded

**To maintain old behavior (if needed):**

```yaml
- uses: actions/download-artifact@v5
  with:
    artifact-ids: 12345
    path: dist/my-artifact  # Explicitly specify the nested path
```

##### New Contributors

- [@&#8203;nebuk89](https://github.com/nebuk89) made their first contribution in [#&#8203;407](https://github.com/actions/download-artifact/pull/407)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4...v5.0.0>

### [`v4.3.0`](https://github.com/actions/download-artifact/releases/tag/v4.3.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.2.1...v4.3.0)

##### What's Changed

- feat: implement new `artifact-ids` input by [@&#8203;GrantBirki](https://github.com/GrantBirki) in [#&#8203;401](https://github.com/actions/download-artifact/pull/401)
- Fix workflow example for downloading by artifact ID by [@&#8203;joshmgross](https://github.com/joshmgross) in [#&#8203;402](https://github.com/actions/download-artifact/pull/402)
- Prep for v4.3.0 release by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;404](https://github.com/actions/download-artifact/pull/404)

##### New Contributors

- [@&#8203;GrantBirki](https://github.com/GrantBirki) made their first contribution in [#&#8203;401](https://github.com/actions/download-artifact/pull/401)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.2.1...v4.3.0>

### [`v4.2.1`](https://github.com/actions/download-artifact/releases/tag/v4.2.1)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.2.0...v4.2.1)

##### What's Changed

- Add unit tests by [@&#8203;GhadimiR](https://github.com/GhadimiR) in [#&#8203;392](https://github.com/actions/download-artifact/pull/392)
- Fix bug introduced in 4.2.0 by [@&#8203;GhadimiR](https://github.com/GhadimiR) in [#&#8203;391](https://github.com/actions/download-artifact/pull/391)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.2.0...v4.2.1>

### [`v4.2.0`](https://github.com/actions/download-artifact/releases/tag/v4.2.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.9...v4.2.0)

##### What's Changed

- Update README.md by [@&#8203;lkfortuna](https://github.com/lkfortuna) in [#&#8203;384](https://github.com/actions/download-artifact/pull/384)
- Bump artifact version, do digest check by [@&#8203;GhadimiR](https://github.com/GhadimiR) in [#&#8203;383](https://github.com/actions/download-artifact/pull/383)

##### New Contributors

- [@&#8203;lkfortuna](https://github.com/lkfortuna) made their first contribution in [#&#8203;384](https://github.com/actions/download-artifact/pull/384)
- [@&#8203;GhadimiR](https://github.com/GhadimiR) made their first contribution in [#&#8203;383](https://github.com/actions/download-artifact/pull/383)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.1.9...v4.2.0>

### [`v4.1.9`](https://github.com/actions/download-artifact/releases/tag/v4.1.9)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.8...v4.1.9)

##### What's Changed

- Add workflow file for publishing releases to immutable action package by [@&#8203;Jcambass](https://github.com/Jcambass) in [#&#8203;354](https://github.com/actions/download-artifact/pull/354)
- docs: small migration fix by [@&#8203;froblesmartin](https://github.com/froblesmartin) in [#&#8203;370](https://github.com/actions/download-artifact/pull/370)
- Update MIGRATION.md by [@&#8203;andyfeller](https://github.com/andyfeller) in [#&#8203;372](https://github.com/actions/download-artifact/pull/372)
- Update artifact package to 2.2.2 by [@&#8203;yacaovsnc](https://github.com/yacaovsnc) in [#&#8203;380](https://github.com/actions/download-artifact/pull/380)

##### New Contributors

- [@&#8203;Jcambass](https://github.com/Jcambass) made their first contribution in [#&#8203;354](https://github.com/actions/download-artifact/pull/354)
- [@&#8203;froblesmartin](https://github.com/froblesmartin) made their first contribution in [#&#8203;370](https://github.com/actions/download-artifact/pull/370)
- [@&#8203;andyfeller](https://github.com/andyfeller) made their first contribution in [#&#8203;372](https://github.com/actions/download-artifact/pull/372)
- [@&#8203;yacaovsnc](https://github.com/yacaovsnc) made their first contribution in [#&#8203;380](https://github.com/actions/download-artifact/pull/380)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.1.8...v4.1.9>

### [`v4.1.8`](https://github.com/actions/download-artifact/releases/tag/v4.1.8)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.7...v4.1.8)

##### What's Changed

- Update [@&#8203;actions/artifact](https://github.com/actions/artifact) version, bump dependencies by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;341](https://github.com/actions/download-artifact/pull/341)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.1.7...v4.1.8>

### [`v4.1.7`](https://github.com/actions/download-artifact/releases/tag/v4.1.7)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.6...v4.1.7)

##### What's Changed

- Update [@&#8203;actions/artifact](https://github.com/actions/artifact) dependency by [@&#8203;bethanyj28](https://github.com/bethanyj28) in [#&#8203;325](https://github.com/actions/download-artifact/pull/325)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.1.6...v4.1.7>

### [`v4.1.6`](https://github.com/actions/download-artifact/releases/tag/v4.1.6)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.5...v4.1.6)

##### What's Changed

- updating `@actions/artifact` dependency to v2.1.6 by [@&#8203;eggyhead](https://github.com/eggyhead) in [#&#8203;324](https://github.com/actions/download-artifact/pull/324)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.1.5...v4.1.6>

### [`v4.1.5`](https://github.com/actions/download-artifact/releases/tag/v4.1.5)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.4...v4.1.5)

##### What's Changed

- Update readme with v3/v2/v1 deprecation notice by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;322](https://github.com/actions/download-artifact/pull/322)
- Update dependencies `@actions/core` to v1.10.1 and `@actions/artifact` to v2.1.5

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4.1.4...v4.1.5>

### [`v4.1.4`](https://github.com/actions/download-artifact/releases/tag/v4.1.4)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.3...v4.1.4)

##### What's Changed

- Update [@&#8203;actions/artifact](https://github.com/actions/artifact) by [@&#8203;bethanyj28](https://github.com/bethanyj28) in [#&#8203;307](https://github.com/actions/download-artifact/pull/307)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4...v4.1.4>

### [`v4.1.3`](https://github.com/actions/download-artifact/releases/tag/v4.1.3)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.2...v4.1.3)

##### What's Changed

- Update release-new-action-version.yml by [@&#8203;konradpabjan](https://github.com/konradpabjan) in [#&#8203;292](https://github.com/actions/download-artifact/pull/292)
- Update toolkit dependency with updated unzip logic by [@&#8203;bethanyj28](https://github.com/bethanyj28) in [#&#8203;299](https://github.com/actions/download-artifact/pull/299)
- Update [@&#8203;actions/artifact](https://github.com/actions/artifact) by [@&#8203;bethanyj28](https://github.com/bethanyj28) in [#&#8203;303](https://github.com/actions/download-artifact/pull/303)

##### New Contributors

- [@&#8203;bethanyj28](https://github.com/bethanyj28) made their first contribution in [#&#8203;299](https://github.com/actions/download-artifact/pull/299)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4...v4.1.3>

### [`v4.1.2`](https://github.com/actions/download-artifact/releases/tag/v4.1.2)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.1...v4.1.2)

- Bump [@&#8203;actions/artifacts](https://github.com/actions/artifacts) to latest version to include [updated GHES host check](https://github.com/actions/toolkit/pull/1648)

### [`v4.1.1`](https://github.com/actions/download-artifact/releases/tag/v4.1.1)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.1.0...v4.1.1)

- Fix transient request timeouts [#&#8203;249](https://github.com/actions/download-artifact/issues/249)
- Bump `@actions/artifacts` to latest version

### [`v4.1.0`](https://github.com/actions/download-artifact/releases/tag/v4.1.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v4.0.0...v4.1.0)

##### What's Changed

- Some cleanup by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;247](https://github.com/actions/download-artifact/pull/247)
- Fix default for run-id by [@&#8203;stchr](https://github.com/stchr) in [#&#8203;252](https://github.com/actions/download-artifact/pull/252)
- Support pattern matching to filter artifacts & merge to same directory by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;259](https://github.com/actions/download-artifact/pull/259)

##### New Contributors

- [@&#8203;stchr](https://github.com/stchr) made their first contribution in [#&#8203;252](https://github.com/actions/download-artifact/pull/252)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v4...v4.1.0>

### [`v4.0.0`](https://github.com/actions/download-artifact/releases/tag/v4.0.0)

[Compare Source](https://github.com/actions/download-artifact/compare/v3.1.0...v4.0.0)

##### What's Changed

The release of upload-artifact\@&#8203;v4 and download-artifact\@&#8203;v4 are major changes to the backend architecture of Artifacts. They have numerous performance and behavioral improvements.

ℹ️ However, this is a major update that includes breaking changes. Artifacts created with versions v3 and below are not compatible with the v4 actions. Uploads and downloads *must* use the same major actions versions. There are also key differences from previous versions that may require updates to your workflows.

For more information, please see:

1. The [changelog](https://github.blog/changelog/2023-12-14-github-actions-artifacts-v4-is-now-generally-available/) post.
2. The [migration documentation](https://github.com/actions/upload-artifact/blob/main/docs/MIGRATION.md).
3. As well as the underlying npm package, [@&#8203;actions/artifact](https://github.com/actions/toolkit/tree/main/packages/artifact) documentation.

##### Breaking Changes

1. download-artifact\@&#8203;v4+ is not currently supported on GitHub Enterprise Server (GHES) yet. If you are on GHES, you must use [v3](https://github.com/actions/download-artifact/releases/tag/v3) (Node 16) or [v3-node20](https://github.com/actions/download-artifact/releases/tag/v3-node20) (Node 20).
2. On self hosted runners, additional [firewall rules](https://github.com/actions/toolkit/tree/main/packages/artifact#breaking-changes) may be required.
3. Downloading artifacts that were created from `action/upload-artifact@v3` and below are not supported.

For assistance with breaking changes, see [MIGRATION.md](https://github.com/actions/upload-artifact/blob/main/docs/MIGRATION.md).

##### Improvements

1. Downloads are significantly faster, upwards of 90% improvement in worst case scenarios.
2. Artifacts can be downloaded from other workflow runs and repositories when supplied with a PAT.

##### New Contributors

- [@&#8203;bflad](https://github.com/bflad) made their first contribution in [#&#8203;194](https://github.com/actions/download-artifact/pull/194)

**Full Changelog**: <https://github.com/actions/download-artifact/compare/v3...v4.0.0>

</details>

<details>
<summary>actions/upload-artifact</summary>

### [`v7.0.2`](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)

[Compare Source](https://github.com/actions/upload-artifact/compare/v7.0.1...v7.0.2)

##### What's Changed

- Improves artifact download retries when the service returns HTTP 429 (rate limiting), including honoring valid Retry-After headers.
- Updates [@&#8203;actions/artifact](https://github.com/actions/artifact) to v6.3.1.

##### New Contributors

- [@&#8203;tunc-d](https://github.com/tunc-d) made their first contribution in [#&#8203;821](https://github.com/actions/upload-artifact/pull/821)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v7.0.1...v7.0.2>

### [`v7.0.1`](https://github.com/actions/upload-artifact/releases/tag/v7.0.1)

[Compare Source](https://github.com/actions/upload-artifact/compare/v7.0.0...v7.0.1)

##### What's Changed

- Update the readme with direct upload details by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;795](https://github.com/actions/upload-artifact/pull/795)
- Readme: bump all the example versions to v7 by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;796](https://github.com/actions/upload-artifact/pull/796)
- Include changes in typespec/ts-http-runtime 0.3.5 by [@&#8203;yacaovsnc](https://github.com/yacaovsnc) in [#&#8203;797](https://github.com/actions/upload-artifact/pull/797)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v7...v7.0.1>

### [`v7.0.0`](https://github.com/actions/upload-artifact/releases/tag/v7.0.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v6.0.0...v7.0.0)

##### v7 What's new

##### Direct Uploads

Adds support for uploading single files directly (unzipped). Callers can set the new `archive` parameter to `false` to skip zipping the file during upload. Right now, we only support single files. The action will fail if the glob passed resolves to multiple files. The `name` parameter is also ignored with this setting. Instead, the name of the artifact will be the name of the uploaded file.

##### ESM

To support new versions of the `@actions/*` packages, we've upgraded the package to ESM.

##### What's Changed

- Add proxy integration test by [@&#8203;Link-](https://github.com/Link-) in [#&#8203;754](https://github.com/actions/upload-artifact/pull/754)
- Upgrade the module to ESM and bump dependencies by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;762](https://github.com/actions/upload-artifact/pull/762)
- Support direct file uploads by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;764](https://github.com/actions/upload-artifact/pull/764)

##### New Contributors

- [@&#8203;Link-](https://github.com/Link-) made their first contribution in [#&#8203;754](https://github.com/actions/upload-artifact/pull/754)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v6...v7.0.0>

### [`v6.0.0`](https://github.com/actions/upload-artifact/releases/tag/v6.0.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v5.0.0...v6.0.0)

##### v6 - What's new

> \[!IMPORTANT]
> actions/upload-artifact\@&#8203;v6 now runs on Node.js 24 (`runs.using: node24`) and requires a minimum Actions Runner version of 2.327.1. If you are using self-hosted runners, ensure they are updated before upgrading.

##### Node.js 24

This release updates the runtime to Node.js 24. v5 had preliminary support for Node.js 24, however this action was by default still running on Node.js 20. Now this action by default will run on Node.js 24.

##### What's Changed

- Upload Artifact Node 24 support by [@&#8203;salmanmkc](https://github.com/salmanmkc) in [#&#8203;719](https://github.com/actions/upload-artifact/pull/719)
- fix: update [@&#8203;actions/artifact](https://github.com/actions/artifact) for Node.js 24 punycode deprecation by [@&#8203;salmanmkc](https://github.com/salmanmkc) in [#&#8203;744](https://github.com/actions/upload-artifact/pull/744)
- prepare release v6.0.0 for Node.js 24 support by [@&#8203;salmanmkc](https://github.com/salmanmkc) in [#&#8203;745](https://github.com/actions/upload-artifact/pull/745)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v5.0.0...v6.0.0>

### [`v5.0.0`](https://github.com/actions/upload-artifact/releases/tag/v5.0.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.6.2...v5.0.0)

##### What's Changed

**BREAKING CHANGE:** this update supports Node `v24.x`. This is not a breaking change per-se but we're treating it as such.

- Update README.md by [@&#8203;GhadimiR](https://github.com/GhadimiR) in [#&#8203;681](https://github.com/actions/upload-artifact/pull/681)
- Update README.md by [@&#8203;nebuk89](https://github.com/nebuk89) in [#&#8203;712](https://github.com/actions/upload-artifact/pull/712)
- Readme: spell out the first use of GHES by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;727](https://github.com/actions/upload-artifact/pull/727)
- Update GHES guidance to include reference to Node 20 version by [@&#8203;patrikpolyak](https://github.com/patrikpolyak) in [#&#8203;725](https://github.com/actions/upload-artifact/pull/725)
- Bump `@actions/artifact` to `v4.0.0`
- Prepare `v5.0.0` by [@&#8203;danwkennedy](https://github.com/danwkennedy) in [#&#8203;734](https://github.com/actions/upload-artifact/pull/734)

##### New Contributors

- [@&#8203;GhadimiR](https://github.com/GhadimiR) made their first contribution in [#&#8203;681](https://github.com/actions/upload-artifact/pull/681)
- [@&#8203;nebuk89](https://github.com/nebuk89) made their first contribution in [#&#8203;712](https://github.com/actions/upload-artifact/pull/712)
- [@&#8203;danwkennedy](https://github.com/danwkennedy) made their first contribution in [#&#8203;727](https://github.com/actions/upload-artifact/pull/727)
- [@&#8203;patrikpolyak](https://github.com/patrikpolyak) made their first contribution in [#&#8203;725](https://github.com/actions/upload-artifact/pull/725)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v5.0.0>

### [`v4.6.2`](https://github.com/actions/upload-artifact/releases/tag/v4.6.2)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.6.1...v4.6.2)

##### What's Changed

- Update to use artifact 2.3.2 package & prepare for new upload-artifact release by [@&#8203;salmanmkc](https://github.com/salmanmkc) in [#&#8203;685](https://github.com/actions/upload-artifact/pull/685)

##### New Contributors

- [@&#8203;salmanmkc](https://github.com/salmanmkc) made their first contribution in [#&#8203;685](https://github.com/actions/upload-artifact/pull/685)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v4.6.2>

### [`v4.6.1`](https://github.com/actions/upload-artifact/releases/tag/v4.6.1)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.6.0...v4.6.1)

##### What's Changed

- Update to use artifact 2.2.2 package by [@&#8203;yacaovsnc](https://github.com/yacaovsnc) in [#&#8203;673](https://github.com/actions/upload-artifact/pull/673)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v4.6.1>

### [`v4.6.0`](https://github.com/actions/upload-artifact/releases/tag/v4.6.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.5.0...v4.6.0)

##### What's Changed

- Expose env vars to control concurrency and timeout by [@&#8203;yacaovsnc](https://github.com/yacaovsnc) in [#&#8203;662](https://github.com/actions/upload-artifact/pull/662)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v4.6.0>

### [`v4.5.0`](https://github.com/actions/upload-artifact/releases/tag/v4.5.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.4.3...v4.5.0)

##### What's Changed

- fix: deprecated `Node.js` version in action by [@&#8203;hamirmahal](https://github.com/hamirmahal) in [#&#8203;578](https://github.com/actions/upload-artifact/pull/578)
- Add new `artifact-digest` output by [@&#8203;bdehamer](https://github.com/bdehamer) in [#&#8203;656](https://github.com/actions/upload-artifact/pull/656)

##### New Contributors

- [@&#8203;hamirmahal](https://github.com/hamirmahal) made their first contribution in [#&#8203;578](https://github.com/actions/upload-artifact/pull/578)
- [@&#8203;bdehamer](https://github.com/bdehamer) made their first contribution in [#&#8203;656](https://github.com/actions/upload-artifact/pull/656)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.4.3...v4.5.0>

### [`v4.4.3`](https://github.com/actions/upload-artifact/releases/tag/v4.4.3)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.4.2...v4.4.3)

##### What's Changed

- Undo indirect dependency updates from [#&#8203;627](https://github.com/actions/upload-artifact/issues/627) by [@&#8203;joshmgross](https://github.com/joshmgross) in [#&#8203;632](https://github.com/actions/upload-artifact/pull/632)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.4.2...v4.4.3>

### [`v4.4.2`](https://github.com/actions/upload-artifact/releases/tag/v4.4.2)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.4.1...v4.4.2)

##### What's Changed

- Bump `@actions/artifact` to 2.1.11 by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;627](https://github.com/actions/upload-artifact/pull/627)
  - Includes fix for relative symlinks not resolving properly

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.4.1...v4.4.2>

### [`v4.4.1`](https://github.com/actions/upload-artifact/releases/tag/v4.4.1)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.4.0...v4.4.1)

##### What's Changed

- Add a section about hidden files by [@&#8203;joshmgross](https://github.com/joshmgross) in [#&#8203;607](https://github.com/actions/upload-artifact/pull/607)
- Add workflow file for publishing releases to immutable action package by [@&#8203;Jcambass](https://github.com/Jcambass) in [#&#8203;621](https://github.com/actions/upload-artifact/pull/621)
- Update [@&#8203;actions/artifact](https://github.com/actions/artifact) to latest version, includes symlink and timeout fixes by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;625](https://github.com/actions/upload-artifact/pull/625)

##### New Contributors

- [@&#8203;Jcambass](https://github.com/Jcambass) made their first contribution in [#&#8203;621](https://github.com/actions/upload-artifact/pull/621)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.4.0...v4.4.1>

### [`v4.4.0`](https://github.com/actions/upload-artifact/releases/tag/v4.4.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.3.6...v4.4.0)

##### Notice: Breaking Changes :warning:

We will no longer include hidden files and folders by default in the `upload-artifact` action of this version. This reduces the risk that credentials are accidentally uploaded into artifacts. Customers who need to continue to upload these files can use a new option, `include-hidden-files`, to continue to do so.

See ["Notice of upcoming deprecations and breaking changes in GitHub Actions runners"](https://github.blog/changelog/2024-08-19-notice-of-upcoming-deprecations-and-breaking-changes-in-github-actions-runners/) changelog and [this issue](https://github.com/actions/upload-artifact/issues/602) for more details.

##### What's Changed

- Exclude hidden files by default by [@&#8203;joshmgross](https://github.com/joshmgross) in [#&#8203;598](https://github.com/actions/upload-artifact/pull/598)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.3.6...v4.4.0>

### [`v4.3.6`](https://github.com/actions/upload-artifact/releases/tag/v4.3.6)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.3.5...v4.3.6)

##### What's Changed

- Revert to [@&#8203;actions/artifact](https://github.com/actions/artifact) 2.1.8 by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;594](https://github.com/actions/upload-artifact/pull/594)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v4.3.6>

### [`v4.3.5`](https://github.com/actions/upload-artifact/releases/tag/v4.3.5)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.3.4...v4.3.5)

##### What's Changed

- Bump [@&#8203;actions/artifact](https://github.com/actions/artifact) to v2.1.9 by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;588](https://github.com/actions/upload-artifact/pull/588)
  - Fixed artifact upload chunk timeout logic [#&#8203;1774](https://github.com/actions/toolkit/pull/1774)
  - Use lazy stream to prevent issues with open file limits [#&#8203;1771](https://github.com/actions/toolkit/pull/1771)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.3.4...v4.3.5>

### [`v4.3.4`](https://github.com/actions/upload-artifact/releases/tag/v4.3.4)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.3.3...v4.3.4)

##### What's Changed

- Update [@&#8203;actions/artifact](https://github.com/actions/artifact) version, bump dependencies by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;584](https://github.com/actions/upload-artifact/pull/584)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.3.3...v4.3.4>

### [`v4.3.3`](https://github.com/actions/upload-artifact/releases/tag/v4.3.3)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.3.2...v4.3.3)

##### What's Changed

- updating `@actions/artifact` dependency to v2.1.6 by [@&#8203;eggyhead](https://github.com/eggyhead) in [#&#8203;565](https://github.com/actions/upload-artifact/pull/565)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.3.2...v4.3.3>

### [`v4.3.2`](https://github.com/actions/upload-artifact/releases/tag/v4.3.2)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.3.1...v4.3.2)

##### What's Changed

- Update release-new-action-version.yml by [@&#8203;konradpabjan](https://github.com/konradpabjan) in [#&#8203;516](https://github.com/actions/upload-artifact/pull/516)
- Minor fix to the migration readme by [@&#8203;andrewakim](https://github.com/andrewakim) in [#&#8203;523](https://github.com/actions/upload-artifact/pull/523)
- Update readme with v3/v2/v1 deprecation notice by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;561](https://github.com/actions/upload-artifact/pull/561)
- updating `@actions/artifact` dependency to v2.1.5 and `@actions/core` to v1.0.1 by [@&#8203;eggyhead](https://github.com/eggyhead) in [#&#8203;562](https://github.com/actions/upload-artifact/pull/562)

##### New Contributors

- [@&#8203;andrewakim](https://github.com/andrewakim) made their first contribution in [#&#8203;523](https://github.com/actions/upload-artifact/pull/523)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4.3.1...v4.3.2>

### [`v4.3.1`](https://github.com/actions/upload-artifact/releases/tag/v4.3.1)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.3.0...v4.3.1)

- Bump [@&#8203;actions/artifacts](https://github.com/actions/artifacts) to latest version to include [updated GHES host check](https://github.com/actions/toolkit/pull/1648)

### [`v4.3.0`](https://github.com/actions/upload-artifact/releases/tag/v4.3.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.2.0...v4.3.0)

##### What's Changed

- Reorganize upload code in prep for merge logic & add more tests by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;504](https://github.com/actions/upload-artifact/pull/504)
- Add sub-action to merge artifacts by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;505](https://github.com/actions/upload-artifact/pull/505)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v4.3.0>

### [`v4.2.0`](https://github.com/actions/upload-artifact/releases/tag/v4.2.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.1.0...v4.2.0)

##### What's Changed

- Ability to overwrite an Artifact by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;501](https://github.com/actions/upload-artifact/pull/501)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v4.2.0>

### [`v4.1.0`](https://github.com/actions/upload-artifact/releases/tag/v4.1.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v4.0.0...v4.1.0)

##### What's Changed

- Add migrations docs by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;482](https://github.com/actions/upload-artifact/pull/482)
- Update README.md by [@&#8203;samuelwine](https://github.com/samuelwine) in [#&#8203;492](https://github.com/actions/upload-artifact/pull/492)
- Support artifact-url output by [@&#8203;konradpabjan](https://github.com/konradpabjan) in [#&#8203;496](https://github.com/actions/upload-artifact/pull/496)
- Update readme to reflect new 500 artifact per job limit by [@&#8203;robherley](https://github.com/robherley) in [#&#8203;497](https://github.com/actions/upload-artifact/pull/497)

##### New Contributors

- [@&#8203;samuelwine](https://github.com/samuelwine) made their first contribution in [#&#8203;492](https://github.com/actions/upload-artifact/pull/492)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v4...v4.1.0>

### [`v4.0.0`](https://github.com/actions/upload-artifact/releases/tag/v4.0.0)

[Compare Source](https://github.com/actions/upload-artifact/compare/v3.2.2...v4.0.0)

##### What's Changed

The release of upload-artifact\@&#8203;v4 and download-artifact\@&#8203;v4 are major changes to the backend architecture of Artifacts. They have numerous performance and behavioral improvements.

ℹ️ However, this is a major update that includes breaking changes. Artifacts created with versions v3 and below are not compatible with the v4 actions. Uploads and downloads *must* use the same major actions versions. There are also key differences from previous versions that may require updates to your workflows.

For more information, please see:

1. The [changelog](https://github.blog/changelog/2023-12-14-github-actions-artifacts-v4-is-now-generally-available/) post.
2. The [README](https://github.com/actions/upload-artifact/blob/main/README.md).
3. The [migration documentation](https://github.com/actions/upload-artifact/blob/main/docs/MIGRATION.md).
4. As well as the underlying npm package, [@&#8203;actions/artifact](https://github.com/actions/toolkit/tree/main/packages/artifact) documentation.

##### New Contributors

- [@&#8203;vmjoseph](https://github.com/vmjoseph) made their first contribution in [#&#8203;464](https://github.com/actions/upload-artifact/pull/464)

**Full Changelog**: <https://github.com/actions/upload-artifact/compare/v3...v4.0.0>

</details>

---

### Configuration

📅 **Schedule**: (UTC)

- Branch creation
  - At any time (no schedule defined)
- Automerge
  - At any time (no schedule defined)

🚦 **Automerge**: Disabled by config. Please merge this manually once you are satisfied.

♻ **Rebasing**: Whenever PR is behind base branch, or you tick the rebase/retry checkbox.

👻 **Immortal**: This PR will be recreated if closed unmerged. Get [config help](https://github.com/renovatebot/renovate/discussions) if that's undesired.

---

 - [ ] <!-- rebase-check -->If you want to rebase/retry this PR, check this box

---

This PR has been generated by [Mend Renovate CLI](https://github.com/renovatebot/renovate).
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yNDcuMiIsInVwZGF0ZWRJblZlciI6IjQ0LjI0Ny4yIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJtYWpvci11cGRhdGUiXX0=-->
