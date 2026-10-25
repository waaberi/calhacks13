# Blender screen — P1 on Windows

Captures only the explicitly selected Blender window. The default Windows Graphics Capture backend uses `windows-capture==2.0.1`, owned pixel copies and one latest-only JPEG encoder. `--backend print` explicitly selects the slower PrintWindow/Pillow backend. No monitor/desktop fallback. Serves the existing [capture contract](../contracts/README.md#blender-screen) on **127.0.0.1:8766 only**. USB Link carries the Windows app to Quest; this helper does not use the LAN or provide Air Link.

## Start

Use Python 3.12 or 3.13 on Windows, with Tk support. In that interpreter:

```powershell
python -m pip install -r desktop-capture/requirements.txt
python desktop-capture/launch.py --player C:\path\to\SpatialModeling.exe --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --blend C:\path\to\reference-copy.blend
```

Use the absolute Python executable if Python is not on PATH. The launcher:

1. Tests the real add-on's localhost ping. If present, attaches without touching the open document.
2. Otherwise opens the supplied `.blend` in a separate Blender process with isolated preferences, installs the repository add-on there and starts its Host. LAN stays off. It never saves over the input file or closes any other Blender.
3. Opens the capture picker. Select the intended Blender window and click **Capture selected window**. Selection is restricted to actual Blender application windows, not arbitrary windows containing "Blender" in their title.
4. Waits for a real frame, then starts the supplied Windows EXE. Logs and launch identity go in a new temporary session directory; `--session-dir` can choose another directory outside the repo.

Close an earlier test Player before launching another. The launcher refuses an existing Player process, including one that has lost its window during shutdown. If capture is already running, the launcher attaches to it; confirm its selected window in the picker. An explicit `--window HWND` must match the helper's read-only `GET /selection` identity, otherwise launch stops with instructions to select the intended window. Older helpers without this endpoint must be restarted before an explicit-window attach. Closing the picker stops the helper, while Blender and the Player remain open. The launcher does not stop or save Blender when it exits. Supply `--diagnose` for a read-only report instead of launching; it needs no `--player`. `capture_helper.py --list` lists available identities. Only main Blender windows are offered: Blender's Preferences, Render, File View, Drivers and Info windows are left out.

## In VR

- A (right) / X (left): Show/Hide Blender. F2 is the desktop equivalent.
- The visible Show/Hide Blender button also responds to looking at it and pressing either controller trigger. A desktop mouse can click it in the Player.
- B / Y / R: Recenter the screen and model in front of the current heading.
- Click the right thumbstick (or Z on desktop) to cycle 1×, 1.5× and 2× magnification. Tilt that stick (or use desktop arrow keys) to pan while magnified. The visible Magnify button does the same. This magnifies the captured view only.
- Screen is view-only. It does not send mouse/keyboard input to Blender.
- Host/capture status is integrated into the screen, with a warning if the native host or capture is unavailable. No separate connected/revision/recenter notification covers the view. Frame dimensions/age remain in diagnostic logs rather than the product UI; capture age is not measured headset photon latency.
- Desktop Blender can keep focus while the VR feed continues. The Player has bounded two-request prefetch, deduplicates frames and does not accumulate an image queue.

## Failure/recovery behavior

Minimizing the selected Blender reports `minimized` and `/frame` returns 503; restoring resumes automatically. Closing it reports `no_window`. After reopening Blender, refresh the picker and explicitly select the reopened window: no automatic capture of a different window. A stalled capture expires after three seconds. The app removes an unavailable/stale image rather than presenting it as live. It retries a missing helper automatically. Re-selecting a different window discards any old in-flight image.

Graphics Capture callbacks copy mapped native pixels into owned CPU memory before handing them to the encoder. Session/generation guards discard frames from an obsolete selection or restarted capture. If no callback arrives for two seconds, reopen the same selected window to obtain an actual fresh snapshot; this also refreshes a genuinely static window. Window existence, a running capture-control object and HTTP requests must never refresh the pixel timestamp. Unity independently requires a recent `X-Captured-At` on both 200 and 304 responses, and hides expired pixels even if `X-Capture-Alive` is recent.

Capture preserves native pixels up to 3840×2400 while preserving aspect ratio; `--fps` defaults to a target of 60, not a guaranteed measured rate. JPEG quality 95 with no chroma subsampling preserves text/color edges. The VR screen is larger and closer than the initial P1 prototype, with mip filtering and optional magnification. Actual readability still depends on the headset and must be physically tested. GPU/window compatibility varies: black or unsupported captures report an error rather than falling back to a desktop capture. `PrintWindow` can block; it runs off the picker/HTTP thread and the freshness timeout prevents old images being served. A permanently blocked capture requires restarting the helper. The local GET service has no CORS or control endpoints and rejects non-local Host headers. It is a development helper, not a production Internet-facing service.

## Verification

```powershell
python -m unittest discover -s desktop-capture -p 'test_*.py' -v
```

The twenty-six capture/launcher tests exercise headers/304, unavailable states, stale expiry despite HTTP activity, window switching, latest-only retention, exclusive port binding, refresh timing, independent ownership of callback pixels, out-of-order rejection and explicit selection/process guards. Four run the real graphics capture and encoder threads against a fake `windows_capture` and check that an unexpected encoder error, a failed capture start, a failed stop or a capture that ended by itself are reported and recovered from instead of stopping capture until the helper restarts. CI runs them on Linux; the five tests that need Windows or the real `windows_capture` binding skip there. They are not GPU or headset acceptance. The Windows Player flag `--p1-smoke` requires real fresh pixels before and after ten panel toggles and magnification, then exits with a pass/fail code. A static window can pass this availability check; it cannot establish live motion.

For a separate live-motion check, run the following while deliberately orbiting the selected Blender viewport throughout the observation. Use a saved test copy, change the view only, and restore the angle afterward. If no motion was observed, keep that failed result and repeat with a synchronized stimulus; do not label a heartbeat or static image a live pass.

```powershell
python desktop-capture/verify_live.py --seconds 60 --player-log C:\path\to\player.log --output C:\path\to\live-gate.json
```

This requires at least five substantial viewport pixel changes, fresh capture timestamps, JPEG95/4:4:4 and new Player frame-rate log entries during the same interval. It is not a sustained 40fps benchmark. Physical controller, headset clarity and perceived motion checks remain necessary.

V20 acceptance: Talia confirmed "Yes, live and clear again" after the v19 frozen-feed regression. A controlled 60-second test with three reversible orbit/restore pairs observed six viewport changes, no unavailable samples and a maximum actual pixel age of 2253ms at2564×1602, JPEG95/4:4:4. The earlier observation with no qualifying changes remains recorded as failed. See [regression history](../docs/product-workflow/DRAG_MOVEMENT_REGRESSION.md).

For a development Windows build, set `CALHACKS_P1_BUILD_PATH` to an output EXE outside the repo, then run Unity with `-batchmode -quit -projectPath app -executeMethod P1Build.Windows -logFile <path>`. Build with the pinned Unity version from README.

## Talia's USB acceptance

Record the exact build and connection type. Observe a changing native Blender view inside our app, operate A/X and the visible button, toggle ten times, check text in both eyes, and run for five minutes. Minimize/restore Blender; close/reopen a saved test copy and reselect it. Confirm clear unavailable states and fresh recovery. Original wireless P1 acceptance stays deferred while using USB.
