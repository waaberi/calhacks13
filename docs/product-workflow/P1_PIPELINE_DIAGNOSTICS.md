# Unpromoted P1 pipeline comparison

This diagnostic branch combines diagnostic `5815af5` with published P1 `3c1bdad` through merge `d78a8020b33080da578eeeadc277131d8a7fdc2b`. The merge changes only capture helper/tests and the throughput report; the diagnostic Unity source is unchanged. The product-only request-claim proposal is `1526ec8`; its corresponding diagnostic implementation was cherry-picked as `98c17c6`, with timing hooks retained. The original product commit is not an ancestor merely because its implementation is present.

The reconciliation itself did not run a new build or runtime trial. The later authorized trials below used separate, recorded artifacts. The product proposal is not integrated into the published P1 phase branch or cumulative C by these diagnostic results.

## Actual v23 failure and diagnostic-only followup

After runtime release, v23 built from78db8e0 with all real P1 gates and zero errors. The first40-second legacy run exited0. The first claim run crashed at about35 profile seconds with `xrCreateReferenceSpace: XR_ERROR_LIMIT_REACHED`, native UnityOpenXR stack and Windows exit0xE06D7363; the sequence stopped before the remaining runs. Both modes had eye0×0. Legacy logged8372 app-space changes; claim logged9987 before failure. This does not establish HTTP claims as the crash cause.

The followup skips creation of the Meta passthrough manager only when `--p1-profile` is present and eye buffers are zero. The installed manager's origin-setting path calls Unity's tracking-origin setter and refreshes its recenter space; inactive-eye churn is the working lead. Ordinary product and active-eye paths retain their existing code. The guard changes the software diagnostic setup and requires a new build plus repeated real observations; it is not an XR/product fix or proof of physical passthrough. Do not promote this diagnostic-only reference into the product-only request proposal. Source/render assets and full-resolution capture remain unchanged.

## Source and preserved guards

Before the guard, the diagnostic app difference was six files: modified `BlenderScreen.cs` and `WorkspaceChecks.cs`, new `CaptureRequestLanes.cs` and `P1PipelineProfile.cs`, plus their metadata. The guard adds the seventh file, `WorkspacePassthrough.cs`. Capture uses the existing two HTTP slots. Claims reserve a fresh ETag/captured-time pair, reject duplicate/invalidated bodies and retain actual-pixel freshness checks. Diagnostic flags select the port, duration and legacy policy; traces are bounded to4096 requests and emitted in128-row chunks. Available engine texture counters are recorded without assuming unsupported markers exist.

The interaction, controller poses/bindings, stabilizer, settled startup placement, native/view separation, ordinary passthrough path, shutdown and render assets are unchanged from P1. The diagnostic zero-eye guard is the explicit passthrough exception. `WorkspaceInteraction.cs` working-byte SHA256 remains `c50f9fcc82958463f88586ca465c8a0a4f1652a1df1f2342e8fad62d925c3214`. Existing build gates remain mandatory; source equality does not replace a later Unity run or physical acceptance.

Exact helper working-byte SHA256 remains `a46c15b31039dd375226525c66622a07ed83717da43bdd0f418be34407262c09`, the source with22 passed capture/launcher tests and the recorded305-second proof. `CaptureRequestLanes.cs` Git/LF SHA256 is `eaaa0bfa568e33ab61867314cb57ecd188682b2c2d79bc9ee3e94c3ff781fcd3`; the class, actual16-assertion check method and freshness expression match the earlier pure-class run. Those unchanged checks were not repeated. Windows checkout line endings can change file-byte hashes; retain both byte and normalized hashes in local evidence.

## Same-binary comparison, only after explicit runtime release

Build one new diagnostic artifact after the authorized Editor/build slot, run all P1Build gates, and retain its source/assembly hashes. Use one full-quality, deliberately changing isolated native window and the exact final helper source. Existing human sessions must not be interrupted. Keep native data and view restoration evidence.

Run the same executable with these argument sets, alternating legacy/claim/claim/legacy for40 seconds each:

```text
--p1-profile --p1-profile-port=8876 --p1-profile-duration=40 --p1-profile-legacy-fetch
--p1-profile --p1-profile-port=8876 --p1-profile-duration=40
```

Legacy mode bypasses early-header admission and uses the displayed ETag. Both modes share diagnostics, freshness guards and cleanup code. Thus this isolates the claim policy within one binary; it is not the untouched production Player. Record early-header availability before request completion, duplicate/abort outcomes, HTTP200/304, actual unique texture assignments, pixel ages, stage timing, and texture counts/memory when available. Preserve missing counters, exceptions and failed samples. Discard startup intervals consistently; do not turn assignments or an inactive headset into compositor-displayed fps. Report full two-second rates and dips, not only peaks.

Exercise unavailable/recovery, stale304 rejection, disable/reenable, completed duplicate disposal, early abort, clean exit/relaunch and native/view invariance. Any gain must survive rebasing the product-only change into the current cumulative source, its full Unity/build/regression gates and the controlled physical test. Keep diagnostics out of product. No product propagation is authorized by a promising trace alone.

## Later bounded helper and resize experiments

An isolated followup harness may compare two versus three fixed encoder workers with one replaceable waiting snapshot, then separately compare the existing16ms capture hint with1ms using the final BGR copy. The three-worker hook is explicitly injected experimental behavior. Keep two clients, the same motion/file/window dimensions, full source resolution and JPEG95/4:4:4; record actual worker counts, timestamps, per-attempt failures, quality and native invariance. Repeat the baseline to detect workload/thermal drift. A promising experiment requires an actual production-source implementation, appropriate worker/race tests and exact-source reliability proof before promotion. Previous two-worker proof remains mean37.15fps/min30/max43: sustained40fps failed.

Resize requires a separately owned isolated window and genuine computer-use controls: maximize, restore, real size change, maximize. Record observed window/client bounds and decoded JPEG dimensions after each step; account for measured nonclient borders rather than assuming their sizes. Require a materially different observed size and fresh matching pixels. A requested resize or unchanged bounds fails. Keep the window below existing full-resolution caps; inspect JPEG95/4:4:4 and native invariance, then restore original window/view/selection. Do not use OS position/resize APIs or change security/XR settings.
