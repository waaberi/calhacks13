# Collaboration in the combined Blender VR build

The current single-user glass UI, local native input, direct controller tools, drawing, voice/Gemini, room recovery and acknowledged native-input handoff remain the baseline. Collaboration adds the published host/session/presence and optional bridge work from merge `4119970` (#165/#167, #156 and #169); it does not replace those newer features with an older app.

## Full native shared editing is required and not yet delivered

Both participants must use ordinary native Blender tools, including Edit Mode, modifiers and materials. The published Client's read-only evaluated mesh mirror and controlled requests do **not** meet that requirement. Full Blender binaries at both ends do not change the mirror's limitations.

Real Windows host to Ubuntu 24.04/QEMU Client tests passed six production request/receipt/ownership/cancel/disconnect/reconnect checks over direct TLS and six over the bridge. These establish the existing supported collaboration path only. They do not establish arbitrary native synchronization, two physical PCs, different home networks or headset acceptance.

Separate disposable feasibility checks preserve original quads, UVs, modifiers, shape keys and material nodes through a native copy and local atomic replacement with one Undo/Redo. A Windows to Linux native editing to Windows file round trip also preserves the tested data. These experiments are outside the production Client; they do not establish full data-type coverage, linked/external asset transfer or automatic synchronization. Initial replacement failures and Blender crash reports are retained. Corrected enumeration excludes aggregate bpy.data.all_ids so excluded UI/window data cannot re-enter the deletion set through it.

Remaining work: a reviewed Host/Client full-native state contract, acknowledged ownership and base-state fences, automatic original-data synchronization, conflict/stale/disconnect recovery, native history and asset fidelity tests. Unlocking the evaluated mirror would produce unsynchronized local edits. Existing component ownership is retained in #176/#106/#87/#115. Root retains sole final Unity/package/runtime ownership.

## Start with one user

Keep the host add-on in **Host** role and **SpacetimeDB: This PC**. LAN and Client edit permissions retain their existing opt-in defaults. With no local SpacetimeDB server, memory decides leases while the host continues to work. The collaboration panel stays hidden for the ordinary local Host + local VR pair. These are two connections to one workflow, not evidence of two people.

The host retains authority. Input ON reserves native preview input for its joined local VR writer. To switch that same user to a direct edit or voice, the existing client releases held helper input, awaits the native end acknowledgement and fresh empty ownership, rechecks session/document/generation, then sends one new edit. A separate writer's reservation or an unfinished native modal still blocks conflicting edits. This integration does not remove those checks or replay old rejected input.

## Add another Blender

On the host, deliberately enable the existing LAN listener and Client edit permission. A remote Blender uses **Client** role, the host's address/port and the session token. Keep TLS enabled. The existing controlled remote operator and draft/Apply/Cancel workflow remains the remote edit surface; the Client mirror is not a second authoritative Blender document. See `spacetime/README.md` and the Client workflow guide for the complete supported tool scope.

When a genuine foreign peer joins, VR shows session connections, writer names/reservations and activity. Foreign shared reservations label rendered target objects; an exclusive reservation names the whole document. Counts describe connections or writer actors, not inferred human identity. The panel keeps its initial world pose so looking around does not move it with the headset. Disconnect and a fresh welcome clear old presence/lease state; a previously collaborative stale scene is visibly marked and edits remain disabled until current.

## Optional internet bridge

**Maincloud** is explicit opt-in. Follow `spacetime/README.md` under “Across the internet”: both ends run the Node bridge, and the remote Client connects to its loopback bridge with TLS/session token. This does not move the headset off the host PC. No Maincloud session is claimed or started by normal package validation or by this integration's tests. Do not switch preferences on a running unsaved session merely to inspect the feature: preference changes deliberately restart the host connection and require a coordinated handoff.

A complete build includes matching Player, add-on, contracts, capture/helper, voice/native dependencies and optional compiled bridge/runtime support. A new Player alone does not upgrade the running native add-on. The sole runtime owner must plan any later backend switch while preserving the current model, Undo and all unsaved sessions. No launch is authorized by software delivery.

## Authority and regression evidence

Lease decisions run off Blender's main thread. Before announcing an asynchronous grant, the host rechecks connection/edit permission, session/host epoch, document/open epoch, target generations and linked coverage; stale reservations are released. Delayed replies cannot reinsert evicted deduplication entries. Existing command, recipe, selection and live-edit validation remains authoritative.

Focused native checks use two disposable factory Blenders and a private Windows SpacetimeDB server, not the running model. `tests/backend/run_p3_client.py --store URL DATABASE` verifies real mirrored-store decisions; `--relay URL DATABASE` also exercises both bridges. `tests/p25/native_collaboration_handoff_gate.py` verifies native preview end ACK → direct live native updates → atomic voice with foreign conflicts, one Undo/Redo and Cancel. `MultiUserIntegrationChecks` covers single-user UI, foreign presence and reconnect clearing inside the cumulative Unity build.

Same-PC software evidence is separate from two physical PCs, separate home networks, headset usability and phase acceptance. The integration remains unlaunched under the publication hold until the human explicitly requests a coordinated runtime switch.
