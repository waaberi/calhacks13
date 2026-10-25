# Current status — v20 targeted physical regressions accepted

Talia confirmed smooth screen/model aim dragging in v18, startup in front and both controllers smooth in v19, then restored live/clear Blender video in v20. V20 preserves the accepted movement/startup implementation and repairs false capture liveness: old pixels were served for over two hours behind a fresh heartbeat. Owned callback pixels, same-window capture recovery and independent actual-pixel expiry now guard helper and Player. See [WORKSPACE_INTERACTION.md](WORKSPACE_INTERACTION.md) and [regression history/checklist](DRAG_MOVEMENT_REGRESSION.md).

V20 Windows build0errors; Unity real ray/pose/startup/native-view/visual/freshness gates,11capture tests, Ruff and fresh-pixel smoke PASS. Controlled60s live check PASS6viewport changes/442samples/no unavailable/max pixel age2253ms,2564x1602 JPEG95/4:4:4. Initial unsynchronized observation with0qualifying changes remains FAILED in evidence. User's latest answer: "Yes, live and clear again". Sustained40fps is not independently certified. Room visibility was physically passed in combined-v2 and its alpha fix retained; no new room-toggle/reconnect/keyboard-readability pass is inferred.

Accepted binary `p1-capture-recovery-v20`, assembly SHA256 `385df5d667ec3f80160bdb780d54bba0a104bfbf6fdf4175fffde693b168abf5`. Source branch: [`codex/talia-p1-usb-screen`](https://github.com/waaberi/calhacks13/tree/codex/talia-p1-usb-screen), based on3a2e1d6. Talia authorized feature-branch publication after these tests; publication preserves the accepted runtime/source and does not merge newer main or change the build. Leave the accepted Player/helper running. Main integration, issue closure and full P1/P2 acceptance remain separate. Original wireless gate and remaining recovery/soak/team checks remain separate. Earlier results below describe historical builds and publication states.

# P1 USB capture and screen — 2026-10-24

## Readability follow-up — v4

The v3 physical live-update, right-A hide/show and ten-toggle checks passed. Its readability check FAILED: Talia reports pixelation, difficult icons and very hard-to-read text. She clarified that the separate connected/revision/recenter notification should be integrated into the Blender view. Original findings remain recorded on GitHub #26, comment6381206133.

V4 preserves native capture up to3840×2400 (current actual window2586×1613, previously served1920×1198), uses JPEG95 without chroma subsampling and mip filtering, enlarges/approaches the screen, adds bounded1×/1.5×/2× magnification/panning, and integrates host status into the screen with no separate notification. New Windows build passed with zero errors. Eight HTTP regressions and Ruff pass. Real-feed v4 smoke passed16frames/10toggles plus magnification/crop bounds; final frame age157ms. The physical readability/notification retest is PENDING. Earlier v3 passes are retained as evidence and do not automatically pass the revised layout.

Talia explicitly assigned Lee's capture/launcher and Jihyeon's P1 screen tasks to Codex for this local USB build. Branch: `codex/talia-p1-usb-screen`, based on the tested P0 fix candidate `3a2e1d6`. No push or merge. This does not certify newer main or pass the original wireless gate.

## Implemented

- Selected Blender window capture with Pillow/Win32, an explicit window picker and localhost-only latest-frame HTTP matching the existing contract.
- Live aspect-preserving world-space VR screen; A/X/F2 shortcut, visible button, gaze plus trigger selection and desktop mouse support. B/Y/R recenters the screen and model. No remote desktop input.
- Unavailable/minimized/stalled/closed-window handling: images disappear when stale and fresh images resume on recovery. Closing/reopening Blender requires explicit re-selection, avoiding accidental capture of another window.
- Launcher: native ping diagnostic, attachment to an existing host or a separate isolated Blender Host with the repository add-on, capture selection and Windows Player launch. It does not save source files or close other Blender windows.

## Observed checks

| Check | Result |
| --- | --- |
| Unity 6000.6.5f1 Windows development build | PASS, zero build errors |
| Real Blender 5.2.2 selected-window pixels | PASS; GPU viewport visible, not black |
| Native viewport angle change alters captured image | PASS; actual Front Orthographic change observed |
| Real minimize/restore | PASS; `minimized`/503 then fresh `capturing` frames |
| Capture helper stopped/restarted while Player running | PASS; unavailable state logged, fresh live frames resumed |
| HTTP/selection/freshness/port regression tests | 8 PASS |
| Ruff and whitespace checks | PASS |
| Player live-feed and ten-toggle smoke | PASS on pre-cleanup-fix build: 16 frames, 10 toggles, final frame age 181 ms |
| Launcher new isolated host -> ping -> Player | PASS; host LAN off, existing Blender windows preserved |
| Capture rate on test PC | About 7–8 fps at 1920×1198, varies with load |
| Latest sampled capture-to-HTTP age | 110–216 ms, mean 188.9 ms; not headset photon latency |
| Physical A/X, button, binocular readability, five-minute USB session | PENDING Talia observation |
| Actual close/reopen/reselect in Player | PENDING manual test |
| Air Link | DEFERRED for current USB target; not passed |

Final v3 runtime assembly SHA-256: `a346717aad5ad4b728a311707dea9dfbea71073b6d5ec3f5828e394b34761ef0`. Existing Unity-generated settings were preserved and used for the local build; they are outside the new source changes. Exact logs and runtime identities remain in local planning/evidence.

## Findings repaired during implementation

- First HTTP test run failed with `TypeError: 'HTTPConnection' object does not support the context manager protocol`. Corrected the test harness with `contextlib.closing`; product HTTP tests then passed.
- Windows permitted two initial HTTP helpers to share port 8766. Added exclusive socket binding and a regression test requiring the second bind to fail.
- Picker initially truncated the PID at the end of long duplicate window titles. Put PID first.
- Player smoke exit exposed `NullReferenceException` in `HostScene.Remove` during `OnDestroy`, because Unity can destroy scene children first. Added the destroyed-object guard. Final build succeeds; final shutdown log retest remains pending while physical testing uses the running Player.
- Initial lint findings were resolved; no failures remain in the helper checks.

No full P1 acceptance, `p1-pass` tag, physical controller pass or wireless pass is claimed by compilation or programmatic toggling.
