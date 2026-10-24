# Cumulative P3B software checkpoint

Predecessor: tested/published P3A `ec407ab1e0f58a28078baefaa95f3d1aea23bd9c`, containing P2 `4ad4247` and P1 `3c1bdad`. No main changes, phase-pass tag, physical acceptance or real second-PC claim.

## Implementation and boundaries

The cumulative branch adds exclusive/shared native reservations, immediate bypass reconciliation ordering and ownership cache safety; real participant names/pink ownership overlays in native Blender and VR; Client presence; conflicting-edit warnings; explicit release, stale ownership clear/recovery and lock-free inspection/selection/table movement. Native overlays preserve saved materials/object colors. All A remote operators and stale/unknown-outcome warnings remain; ownership unregisters before the retained remote UI/mirror. P2 metadata, startup/currentness and table behavior remain. Accepted aim dragging, no-snap pickup, both pose bindings, front placement and image settings were not replaced.

Compiled app source: `5e1e3bd56ccdbc9c19fd1925b4352a07133673b6`.
Windows artifact: `artifacts/p3b-ownership-v3/SpatialModeling.exe` (local generated output, not committed).
Assembly-CSharp SHA256: `9c7dff4d6e0de77bc6e365f389e381c6a12c23874b6d4f34d4b584c0f6eb81fb`.

## Verified evidence

- Root full backend at `4d1c052`: **865 passed, 40 skipped**, 61.84s. Skips explicitly cover optional Blender/runtime/CLI dependencies. The only subsequent source changes are the opt-in Unity ownership smoke; native/contracts/capture source is byte-identical.
- Exact immutable B focused native/contract suite: **316 passed, zero skips**, 27.46s; six actual GUI/native cases completed with clean exits. Installed add-on and before/after source hashes match frozen B. **104 recorded received messages** validate against actual B schemas.
- Actual input matrix: **57 routes**, comprising 37 prevented before mutation, 15 independent/unlocked allowed, one next-tick mode recovery and **four actual unrestricted mutations, strict FAIL**.
- Actual native ownership image has pink bounds and real names for linked objects; both draw callbacks ran15 times, no GPU error, unchanged saved material assignments/object colors. Release/disconnect/unregister clear overlays.
- Reconcile success delivered a fresh complete snapshot before the next native apply/update/result. Injected snapshot failure refused the next unrelated command, kept its object unchanged and froze commands. The original bypass mutation remains a failure.
- During real native10mm application, owner socket close at0.052s and actual unchanged six-second timeout at6.011s did not release reservations through the commit/Undo boundary or interleave the queued competing acquire. Fresh peers queried the applied lost receipt; exactly one native application, no replay, X=0.009999999776482582m.
- Root production Client operator tests at meter and millimeter native scales passed against exact B: flag-off sends no command; one leased10mm edit is host-confirmed and mirrored; Cancel/disconnect/reconnect do not duplicate it; real participant/lease overlays and release retain geometry/material state. All four isolated Blender processes exit0; source hashes unchanged.
- Actual Windows build passed0errors and cumulative P2/native/menu/hand/panel/P1 movement at72/90/120, controller/startup/freshness/render checks.
- Actual B Player with a second local participant passed Pin/Hold software pose, native owner label/pink camera image, controlled component stale-clear/recovery, denied conflicting Apply, inspection/selection/table movement without lock, release, Shared/Exclusive callbacks and real10mm native receipt. Negative smoke exits3; success Player0/host0. The controlled stale component transition is explicitly separate from a transport-loss test.
- Same B binary passed A's actual14-step menu regression, independent10mm/90deg native readbacks and Arrange/reset/fresh-pose/Place callbacks; normal Player/host exits0.
- Same-binary P2/live regression passed17 checks: actual native inspection/Undo invariance/10mm/add/delete/stale+fresh reconnect;45s changing viewport254changes/255samples,0unavailable,max pixel age150ms,2560x1600 JPEG95/4:4:4. Peak34.3 textureFPS is not sustained40. Normal close exits0; same binary relaunch passes10toggles/magnification/fresh-pixel smoke and exits0. Own host finishes normally; view-only motion restored, helper selection unchanged. The production inspection Player sent only hello/ping, no edit/lease. Raw indexes: p3b-ownership-v1/v2/v3-build, p3b-ownership-runtime-v1/v2, p3b-a-menu-runtime-v1 and p3b-p2-runtime-v1; preserve all failed predecessors.

## Preserved failures and limits

First actual build failed CS1061 because LineRenderer has no isActiveAndEnabled; test-only `bbb9387` uses enabled plus activeInHierarchy. The next actual Player exposed the test peer's app.version=1, rejected by production semantic-version validation; Pin/Hold had already passed, failed Player exited2/host0, negative test3. Test-only `5e1e3bd` uses Application.version and retains peer diagnostics. Failed build/runtime logs remain. No production protocol guard was weakened.

The unrestricted Python/RNA location write, unwrapped modifier operator, scripted leased-child deletion and scripted bpy.ops.ed.undo() really changed protected state. Detection, stale refusal, freeze and reread are recovery, not prevention. Header/F3/custom mappings/scripts/other add-ons are outside the bounded supported input gate. **Strict universal native locking has not passed.**

Two local participants/Blender processes do not establish real second-PC/network acceptance. Actual camera images are software rendering, not binocular/active-XR/comfort/controller acceptance. In A/B runtime evidence the video source is a separate explicitly selected isolated changing Blender viewport, not the native transaction host; C's coupled viewport evidence remains separate. JPEG95/4:4:4/full pixels/renderScale1/MSAA4/alpha guards stay required. Sustained40fps has not passed; exact helper quiet measurement37.153 mean changed-publicationFPS and B peak34.3 textures are not a40fps minimum. Active-XR normal shutdown remains pending#125. The accepted v20 rollback stays preserved.
