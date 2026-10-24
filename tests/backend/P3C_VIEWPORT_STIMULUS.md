# Owned C smoke viewport

Test harness only. Set `P3_SMOKE_CAD=1`, use the real pinned CAD dependency,
and set `P3_SMOKE_CAD_FRAME=1`. Add `P3_SMOKE_CAD_ORBIT=1` to allow bounded
motion. Default runs never import/construct this helper. Incorrect flag
combinations fail startup. No Session arguments or production modules change.

The helper binds this fresh factory-startup process's single window and largest
VIEW_3D/WINDOW region, recording pointers, PID and rectangle. It changes only
view location, distance, quaternion and perspective. Lens, clipping, shading,
overlays, selection, native geometry, Undo, leases and capture stay untouched.
Its orthographic frame derives from authoritative cached real sketch records,
their rigid plane, SI bounds, positive Unit Scale and region aspect. A stable
minimum 160 by 110 mm envelope prevents breathing during a 100->120 mm edit.
Empty sketches stay pending. A different/replaced region is an error.

Write `OUTPUT/viewport-control.json` atomically (temporary file then rename).
The closed grammar has an increasing integer `seq` in 1..2147483647, a 4096-byte
limit, and these requests:

```json
{"seq":1,"action":"frame","target":"420d772974c747ebb91283b7ff8d22a3"}
{"seq":2,"action":"orbit","duration_s":48}
{"seq":3,"action":"stop"}
{"seq":4,"action":"restore"}
```

Frame's optional explicit sketch UUID pins that target. Without it, the latest
applied sketch command supplies the target (create uses its returned sketch ID).
Orbit requires opt-in, a framed existing sketch, and a finite duration of 4..60
seconds in complete four-second cycles. It starts only on a new control seq.
Monotonic time drives sinusoidal yaw +/-15 degrees and pitch +/-8 degrees.
Expiry/stop restores the static framed pose. Restore disables automatic framing
and restores the original view; host shutdown also restores the original view.
Restoration errors still stop the owned server through finally and fail the run.

`report.json.viewport` records original/framed/current poses, target/bounds,
owned surface, control history, timing, samples and restoration deltas. The
report also records the helper hash. This does not select a capture HWND, run a
Player, lower image quality, prove live capture, establish frame rate or certify
physical acceptance. A screenshot/decoded-frame check is required to establish
actual useful occupancy and changing video.

At source publication: control validation has 19 passing tests; Ruff passes.
Actual Blender framing, native-state/Undo preservation, pixel change and normal
cleanup remain pending the coordinator's native gate grant and real GUI run.
