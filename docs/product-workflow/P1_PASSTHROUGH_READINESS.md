# Product passthrough readiness

The ordinary app must not create its Meta manager merely because OpenXR lists
`XR_FB_passthrough`. The observed inactive-eye diagnostic v23 exhausted OpenXR
reference spaces while the shared path created `OVRManager` with eye0x0. V24's
profile-only skip allowed a controlled software comparison; it did not fix the
ordinary app or establish the complete native crash cause.

`WorkspacePassthrough` now waits without changing the camera until all real
inputs are ready: OpenXR runtime, the passthrough extension, a running XR display,
positive eye width and height, and the main camera. No profiler flag selects
this behavior. Waiting is polled every250ms and has no permanent startup timeout,
so a headset becoming ready later can initialize without restarting the app.

The active-eye setup retains the existing manager passthrough flag, underlay,
opacity, initialization timeout, alpha-bearing/LDR camera settings and presented
layer diagnostics. No SDK/package, tracking-origin setting, controller/aim code,
render asset or capture code changes. Capability alone is not displayed as an
active room view.

A readiness epoch permits one initialization attempt. A native initialization
failure leaves an honest opaque failure state instead of rapidly recreating SDK
objects; a real loss/return of readiness or component re-enable permits retry.
Readiness loss, disable or cancellation hides/deactivates the owned layer,
disables only a manager created by this component, and restores saved camera
clear/background/HDR/postprocessing settings. An existing external manager is
never disabled by this component. Owned objects are reused for retries and
destroyed with the component. The user's room-view toggle preference survives.

Enable/disable generation tickets prevent an old pending coroutine from claiming
or rearming a new attempt. Readiness lost between admission and initialization,
during native initialization, or after the first rendered frame explicitly
rearms only the next valid readiness epoch.

Source-only checks exercise the actual pure gate and are called from
`WorkspaceChecks.Run`: missing runtime/capability/display/camera, zero/invalid eye
dimensions, delayed readiness, one attempt per epoch, readiness-cycle retry,
disable cancellation, re-enable and stale-ticket isolation. They do not create
Unity/Meta objects or certify SDK lifecycle behavior.

Required later software evidence is a Windows product build with ordinary
arguments, no `--p1-profile` skip: zero-eye startup/wait/normal close and relaunch,
absence of repeated app-space churn, opaque camera preservation, actual Unity
readiness/disable checks and existing capture/interaction gates. A real active
headset is needed to verify late activation, room visibility and active-eye
shutdown; those physical checks remain pending and do not prevent source
implementation or ordinary inactive-XR validation. No phase, compositor rate or
physical acceptance follows from the pure checks.
