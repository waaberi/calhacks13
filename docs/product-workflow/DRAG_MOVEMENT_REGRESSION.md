# Far-ray dragging: failures, current fix and regression gates

## Current visual pointer/depth correction, 2026-10-25

The wearer rejected pointer lag behind the cylinders, then physically rejected
the v10 raw-pointer replacement as very shaky/skipping while grabbed objects
remained smooth. That raw visual behavior is a retained failure. The current
correction uses the existing stabilized aim for logical UI hits and the displayed
cylinder/ray together. After the unchanged held-object pose update, the pointer
ends at the exact held local contact; unrelated surfaces cannot shorten or
redirect it. The cylinder is derived from that same displayed ray after filtering,
preventing a one-frame mismatch. Free pointers use stabilized nearest intersections
with moved colliders synchronized. No extra world filter or object-motion change
is introduced. The raw same-device sample remains the stabilizer input; pickup,
origin conversion, aim-based position and preserved model orientation remain.

Holding the depth stick integrates continuously in either direction without the
old -0.5..2 metre offset cap. Dead zone and explicit surface-contact behavior
remain. Production routing tests cover already extended positive/negative holds,
and extended integration verifies continued movement without release/reselect.
Both concrete pose formats, both hands, recenter and loss-release are exercised;
the new physical behavior still needs confirmation on the replacement binary.

## Required behavior

Grip selects the live screen or model at a distance. While held, changing controller aim must move the item through the environment, as with a desktop panel in Meta Link. Physical hand translation and stick depth/size also remain available. Release leaves the item where shown. The same behavior applies to the screen, whole build and individual parts without editing native Blender objects.

P2 surface-test correction, 2026-10-24: the human rejected model tilt while grip-moving
and after surface alignment. New Arrange-space model/part/manual-level grips keep
the captured orientation while retaining the accepted far-ray POSITION displacement.
Stick and two hands deliberately rotate; alignment and two-hand handoff rebase that
held orientation. Panel/menu behavior and the generic FollowRay remain unchanged.
Do not restore wrist pitch/roll on these model grips or remove aim-based positional
movement. The complete pickup/move/rebase path now has regression checks; testing
the contact helper alone missed the physically rejected interaction.

## What happened

Talia reported shaky/skipping dragging through v11 and combined-v2. World-target filter tests passed, but did not test the actual distant-ray mapping or required interaction. Moving pose updates to before-render did not establish a physical fix. V13 also assumed all poses were Input System PoseState; Meta Touch Plus exposed legacy OpenXR Pose. That separate compatibility regression is fixed by reading the actual control type (#126).

Combined-v2's sampled drag had actual elapsed cadence around72Hz, max14.2ms and no intervals over25ms. Desired target steps were88.2–101.3mm, grip-position steps3.2–7.7mm and wrist changes4.61–5.68degrees. These are maxima per interval, not a fully correlated raw trace or GPU/compositor measurement. The controller-to-item offset magnifies angular variation:5.68degrees at1.02m is about101mm. That leverage is also how intended far-ray positioning works; removing it is not an acceptable fix.

**V17 FAILED physical acceptance.** Its one-to-one translation/object-center rotation eliminated the angular position response. Talia reported the screen stayed in place and only rotated when pointing. The v17 software regression incorrectly asserted that wrist rotation should never move the item's center. It tested a different interaction from the one required. Do not restore that mapping or those expectations. The user's physical result overrides the software pass.

## V18 implementation

Use the installed Unity XR Interaction Toolkit's public `XRTransformStabilizer.ApplyStabilization` implementation with an endpoint target, before transforming the distant item. Use the same default position/angle stabilization values and distance multiplier as Unity's InteractionAttachController. The raw aim, stabilized aim and held pose remain distinct. Map the held target relative to the stabilized aim captured at pickup, so aim changes still move the item. The custom adaptive world-target filter is no longer in this interaction path; do not apply competing filters/writers to the held target.

Both hover/hit testing and the visible ray use the stabilized ray. Hold updates run once just before rendering with actual elapsed time. Pickup preserves the displayed target; release and tracking loss freeze it, and fresh tracking initializes the ray. The pointer contact stays attached to the held item. Native geometry, scales and Undo are untouched.

Primary reference: [Unity XRTransformStabilizer API](https://docs.unity.cn/Packages/com.unity.xr.interaction.toolkit%403.1/api/UnityEngine.XR.Interaction.Toolkit.Inputs.XRTransformStabilizer.html). The installed3.6.1 package source under Runtime/Inputs/XRTransformStabilizer.cs and Runtime/Interaction/Attachment/InteractionAttachController.cs is the implementation reference. Microsoft documents center rotation as a different manipulation mode; v17 incorrectly substituted that mode for the requested ray drag.

## Automated gates

`P1Build.Windows` calls the real implementation through WorkspaceChecks before building.

- Aim-based displacement is mandatory: at distances0.25/1.02/2/4m, a20degree aim change moves the item through space; the actual Unity stabilizer reaches at least90percent of the intended displacement within the test's1second interval. This prevents the v17 stuck-screen regression.
- Test the actual Unity ray stabilizer, not a stand-alone substitute filter. At72/90/120Hz, a simulated24Hz wrist/position variation has displayed-step RMS ratios0.046/0.042/0.040 versus raw target steps; max displayed steps3.56/3.79/2.61mm. These are synthetic checks, not physical acceptance.
- Preserve pickup without snapping, depth/tracking-origin mapping, rigid whole-build spacing, native/view separation, current-native reset, both concrete pose formats and grip/Pointer bindings with tracking loss checks.
- Protect the accepted render baseline: render scale1,MSAA4, framebuffer alpha and URP alpha processing. The build fails on baseline regression. Retain the physically passed combined-v2 room-view fix.

Future intentional behavior/baseline changes require updated requirements, regression cases and physical evidence. Passing a test for the wrong interaction is not acceptance.

## Physical acceptance

**V18: USER PASSED screen and model smoothness.** Talia answered "yes both are smooth but the set up started behind me". **V19 startup and both controllers: USER PASSED**, exact answer "Yes, in front and smooth". Its live-feed/clarity check FAILED. **V20 restored live feed and clarity: USER PASSED**, exact answer "Yes, live and clear again" after a real viewport-motion trial. Movement source SHA256 remains `c50f9fcc82958463f88586ca465c8a0a4f1652a1df1f2342e8fad62d925c3214`; v20 runtime assembly SHA256 is `385df5d667ec3f80160bdb780d54bba0a104bfbf6fdf4175fffde693b168abf5`. V17 remains failed. These are separate, specific subchecks; no full P1/P2 or sustained40fps pass is inferred.

Use the exact single build after background builds finish. Test slow/fast aim-driven screen movement, whole build and individual parts, both controllers, release/regrab and placement. Confirm room visibility, controller operation, text/icon clarity and the previously accepted live motion. Record build/hash, user answer and runtime log. Do not restart another chat's test without coordinating.

WORKSPACE_DRAG_TIMING logs real cadence, raw/displayed target steps and pose-control switches. The first interval's grip maxima may include the initial aim-to-grip offset; do not read that artifact as actual controller jitter. P1_DISPLAY_QUALITY logs source/eye resolution and render scales. Unity unscaledDeltaTime alone is not real frame/compositor timing. Current capture bytes remain2564x1602, JPEG95 quantization and4:4:4; eye1824x1872, render scale1/MSAA4. Source settings alone cannot establish headset clarity; Talia's v20 answer establishes restored clarity for this run.

Reports: [movement #45](https://github.com/waaberi/calhacks13/issues/45), [screen/quality #26](https://github.com/waaberi/calhacks13/issues/26), [room visibility #124](https://github.com/waaberi/calhacks13/issues/124), [controller types #126](https://github.com/waaberi/calhacks13/issues/126), [separate shutdown problem #125](https://github.com/waaberi/calhacks13/issues/125).

## Startup-placement regression

V18 could choose the initial camera pose independently for screen/model while the wearer put on the headset. Its recorded initial gaze pointed substantially down. V19 reads the actual tracked headset pose, waits0.5seconds of generally-forward stable facing, then shares one placement pose between both displays. A pure gate test rejects downward, untracked and turning samples, accepts stable facing, and resets on tracking loss. B/Y explicit recenter skips the startup delay. Existing arranged placements never follow later head motion or reconnect. The movement source is unchanged from the user-accepted v18.

## Frozen capture hidden by false health — v20 repair

V19's physical video check failed even though source resolution/compression had not been reduced. The long-lived capture helper was still serving frame2146 with capture timestamp1792827411663, more than7,337,864ms old in the observation, while advertising a fresh heartbeat1792834749527. Restarting only the Player retained this bad helper. Its monitor refreshed health from the selected window/control's existence without receiving pixels. Unity and the earlier static-image smoke trusted that heartbeat, so their pass could conceal frozen video. This liveness/acceptance defect is established; the underlying native backend stall cause is not proven. Do not attribute the perceived clarity change to a proven compression or eye-resolution reduction.

The callback also retained a native mapped frame buffer across the encoding thread. V20 copies pixels into owned CPU memory before callback return, uses a bounded latest slot and rejects obsolete sessions. After two seconds without callbacks, it reopens the same explicitly selected window to obtain a genuine new snapshot, including for static content. Actual pixel age expires after three seconds; a window check or HTTP request cannot renew it. No fallback to another window or desktop is allowed.

Unity checks actual captured timestamps independently of the server heartbeat on200/304 responses and during display/smoke. A fresh heartbeat with old pixels fails. The build exercises stale/future/legitimate fresh/static timestamps. Eleven capture tests pass, including owned-buffer independence, actual stale expiry despite HTTP activity and refresh timing. Fresh-frame smoke passes ten toggles/magnification with974ms final pixel age; build succeeds with zero errors. Earlier v19 compilation CS0136 local shadowing was corrected before the successful build; its failed log is preserved. Native shutdown crash #125 reproduced closingv18 and remains a separate unresolved issue.

Live motion is a separate gate. The first45s monitor run recorded zero qualifying viewport changes and FAILED; whether the user's motion overlapped that observation was not established. Keep that result. A synchronized60s test applied three reversible view-only orbit/restore pairs and PASSED:6substantial pixel changes,442samples,0unavailable,max actual pixel age2253ms,2564x1602 JPEG95/4:4:4, new decoded-Player frame activity. The original viewport angle was restored; no native objects or files were edited. Talia independently confirmed live/clear video. Neither this sparse stimulus nor static refresh cadence is a sustained40fps benchmark.

## Replacement-build checklist

1. Read this failure history and preserve the accepted aim-driven interaction, startup pose, both pose formats, room alpha and full image baseline.
2. Run P1Build's real Unity intent/jitter/controller/startup/native-view/visual/freshness gates and the capture tests. Never accept substitute-filter math as proof of the integrated interaction.
3. Run fresh-pixel static smoke for availability/toggles, then `desktop-capture/verify_live.py` with deliberately synchronized viewport motion. Preserve failed observations and exact build/source hashes.
4. Coordinate one headset Player with the authorized passthrough chat. Confirm replacement movement and perceived live clarity in the exact build; do not carry a prior hardware pass over changed code without evidence.
5. Keep specific passes separate from full phase acceptance and preserve the last accepted binary/runtime. Do not rebuild or restart it merely for notes. Pixel expiry prevents a silent frozen-live state; it cannot guarantee that hardware or native capture will never fail again.
