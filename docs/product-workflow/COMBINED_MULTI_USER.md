# Simple collaboration in native Blender

The current human-authorized scope is shared **object move, rotate, scale, delete and host Undo/Redo**, using the existing Client work from PR173. Both computers run full Blender 5.2+. The Host keeps its original native document and tools. The Client uses ordinary G/R/S, transform gizmos and X on mirrored objects, with the Host accepting or refusing each request. Shared Edit Mode, modifiers, UVs, materials and rigs are outside this delivery.

The combined source retains the latest single-user preview input, direct controller tools, drawing, searchable Guide, voice/Gemini and room recovery. Collaboration is optional; LAN and Client write permission remain off by default. Enabling collaboration does not make two local Host/VR connections evidence of two people.

## Connect across the internet — default path

Both computers use ordinary Blender 5.2+. The second user installs the provided Client extension ZIP (Install from Disk, enable Spatial Modeling) and opens a separate empty, unsaved Blender session. The new Client has passed compatibility tests against the unchanged v6 Host; the relay connection needs no new VR Player build or Host replacement.

On the Host, enable **Let a Client-role Blender join** and Client editing, with TLS on. Older builds call the first option **Let a Client-role Blender join over the LAN**; it enables port8767 for the local bridge and does not require the users to share a LAN. Changing these preferences restarts connections, so coordinate this setting with the sole runtime owner and preserve the active model/history.

Run the bundled bridge launcher in **host** mode on the Host PC and **join** mode on the second PC, using the same session token. Both default to SpacetimeDB Maincloud at https://maincloud.spacetimedb.com, database calhacks13-spatial-modeling. On the second PC, select Client role and connect Blender to **127.0.0.1**, port **8767**, with the same token and TLS enabled. That address is the local join bridge; the two computers need no shared Wi-Fi, LAN address, VPN or inbound port forwarding.

The optional collaboration folder beside the add-on ZIP contains the Windows Node runtime and locked bridge dependencies; use its sibling start_collaboration_bridge.ps1. The ZIP itself contains only the add-on. Node does not need a separate installation when using this bundle. Host and join modes ask for the session token; do not put it in a shared document or command arguments.

The real demo Host may select its Maincloud SpacetimeDB preference when the runtime owner enables cloud lease authority. Disposable test Hosts must remain on This PC/in-memory or a private server: the cloud authority has one claim_host slot. The relay works with either lease store and uses token-scoped rooms, so an isolated relay test does not need to claim that slot. No public database reset, republish or demo-slot claim is part of this Client package.

The reference commands and connection diagram are in spacetime/README.md under Across the internet. That is the default remote-user path. If both PCs happen to share a reachable LAN, they can instead connect directly to the Host address:8767 with TLS/token and omit both bridges.

## Use the shared object tools

After the fresh scene arrives, the objects become selectable if the Host permits editing. The sidebar at N > Spatial > Host edits shows request state. Use G/R/S or the corresponding gizmos to transform an object; use X to delete. Ctrl+Z and Ctrl+Shift+Z route to the Host's history while the Client is connected. The Host remains authoritative: conflicts or refused requests restore its version. Escape cancels a transform; a concurrent Host change is then shown without sending the cancelled old transform back. Disconnect and a new document discard old drafts rather than replay them.

Only positive scale values from0.001 through1000 and positions within the existing Host coordinate limits are supported by the current object request protocol. Mesh topology, modifier-stack and material edits in the Client are not synchronized by this implementation. All normal Blender tools remain part of the full Blender installation; tool availability and replication coverage are separate. Waaberi and the Client owner are being asked to reconcile the reported unrestricted-native-sharing requirement with the published implementation; do not claim arbitrary native edits synchronize until verified.

Do not use the sample-creating integrated launcher to join as a Client or upgrade the current unsaved session. The sole headset/runtime owner coordinates any live settings/backend switch so the existing model and Undo history are preserved. The headset stays at the Host PC.

## Verification and limits

The current simple path passed 1,567 backend/P2.5 Python checks with 40 environment skips. Disposable real GUI Blenders passed 12 groups over direct TLS and private real SpacetimeDB direct/bridge routes: native transforms/deletion, actual modal G/Escape, concurrent Host movement, conflict rejection, no resend, Host Undo/Redo, reconnect and permission refusal. Initial failed attempts were retained and corrected before these passes. This is automated native event-loop evidence, not a physical keyboard, two-person or headset pass.

The free Ubuntu24.04/QEMU guest also runs the full Blender5.2.2 application. An X11 screen capture verifies its actual native interface; earlier black screenshots from Blender's own screenshot operator were insufficient evidence and are retained. Cross-OS direct/relay controlled-operator checks passed; the ordinary native object suite is separately recorded in the current software manifest.

The native test entry point is tests/backend/run_simple_native.py. Existing combined native-preview/direct/voice/lease/session checks remain required, including acknowledged same-user native-input release and genuine foreign-owner refusal. Asynchronous grants recheck connection, permission, document/session incarnation, target generation and linked coverage before publication.

No new Unity build is required to use the standalone Client with the current v6 Host. Optional VR collaboration presence/UI integration remains deferred: MultiUserIntegrationChecks is wired into that source but has not yet run, and the originating build owner retains its later complete VR package gate and sole headset runtime. Software delivery does not establish physical two-PC, different-home-network, room-fit or headset acceptance. No PR publication or main merge is authorized by this task.

## Deferred full native sharing

The earlier requirement for arbitrary native Edit Mode/modifier/material sharing was explicitly narrowed by the human to this existing simple version for the one-hour task. Full original-data synchronization remains deferred, not completed. Separate native file and Undo/Redo feasibility experiments do not change the Client's supported scope. Host/Client contract, automatic original-data transfer, full assets/history and concurrent editing require separate work with their existing owners.
