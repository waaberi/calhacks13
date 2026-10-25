# Simple collaboration in native Blender

The current human-authorized scope is shared **object move, rotate, scale, delete and host Undo/Redo**, using the existing Client work from PR173. Both computers run full Blender 5.2+. The Host keeps its original native document and tools. The Client uses ordinary G/R/S, transform gizmos and X on mirrored objects, with the Host accepting or refusing each request. Shared Edit Mode, modifiers, UVs, materials and rigs are outside this delivery.

The combined source retains the latest single-user preview input, direct controller tools, drawing, searchable Guide, voice/Gemini and room recovery. Collaboration is optional; LAN and Client write permission remain off by default. Enabling collaboration does not make two local Host/VR connections evidence of two people.

## Install and join

The new Client passes actual native keyboard/history tests against the unchanged v6 Host. Existing v6 users need no Host upgrade or new VR Player build for basic LAN sharing. Install the source-pinned extension ZIP on the second computer with Blender5.2 or newer; fresh installations may use the same ZIP on both machines. In a separate test session, open Preferences, Add-ons, Install from Disk and enable Spatial Modeling. A Client on the LAN needs no separate pip or Node installation.

On the Host, keep Role **Host**, enable **Let a Client-role Blender join over the LAN** and **Let the Client role edit (test only)**. Keep TLS enabled. Give the other user the Host address, port **8767** and the session token using a private channel. These preference changes restart connections; coordinate them with the runtime owner before using the current unsaved VR session. The test package does not replace or restart that live backend automatically; enabling the existing Host preferences is the only Host-side configuration needed for this path.

On the second machine, start a separate **unsaved, empty** Blender session. Delete the factory cube, camera and light; do not load a personal file. Select Role **Client**, enter the Host address, port, token and TLS, then choose **Connect**. After a fresh scene arrives, the objects become selectable if the Host permits editing. The sidebar at N > Spatial > Host edits shows request state.

Use G/R/S or the corresponding gizmos to transform an object; use X to delete. Ctrl+Z and Ctrl+Shift+Z route to the Host's history while the Client is connected. The Host remains authoritative: conflicts or refused requests restore its version. Escape cancels a transform; a concurrent Host change is then shown without sending the cancelled old transform back. Disconnect and a new document discard old drafts rather than replay them.

Only positive scale values from 0.001 through 1000 and positions within the existing Host coordinate limits are supported. Changes to mesh topology, modifier stacks or materials in the Client are not synchronized. The Host's evaluated geometry/basic colours are mirrored for viewing; this is not a second original native document.

Do not use the sample-creating integrated launcher to join as a Client or upgrade the current unsaved session. The sole headset/runtime owner coordinates any later live backend switch so the existing model and Undo history are preserved.

## Optional internet bridge

For separate networks, the existing explicit host/join bridge can relay the same TLS connection through SpacetimeDB. The add-on ZIP itself contains no bridge. The optional collaboration folder beside the ZIP includes its Windows Node runtime and locked production dependencies; use the sibling start_collaboration_bridge.ps1. Follow spacetime/README.md. Neither the normal add-on installation nor software tests claim a Maincloud session. The headset stays connected to the Host PC.

## Verification and limits

The current simple path passed 1,567 backend/P2.5 Python checks with 40 environment skips. Disposable real GUI Blenders passed 12 groups over direct TLS and private real SpacetimeDB direct/bridge routes: native transforms/deletion, actual modal G/Escape, concurrent Host movement, conflict rejection, no resend, Host Undo/Redo, reconnect and permission refusal. Initial failed attempts were retained and corrected before these passes. This is automated native event-loop evidence, not a physical keyboard, two-person or headset pass.

The free Ubuntu24.04/QEMU guest also runs the full Blender5.2.2 application. An X11 screen capture verifies its actual native interface; earlier black screenshots from Blender's own screenshot operator were insufficient evidence and are retained. Cross-OS direct/relay controlled-operator checks passed; the ordinary native object suite is separately recorded in the current software manifest.

The native test entry point is tests/backend/run_simple_native.py. Existing combined native-preview/direct/voice/lease/session checks remain required, including acknowledged same-user native-input release and genuine foreign-owner refusal. Asynchronous grants recheck connection, permission, document/session incarnation, target generation and linked coverage before publication.

No new Unity build is required to use the standalone Client with the current v6 Host. Optional VR collaboration presence/UI integration remains deferred: MultiUserIntegrationChecks is wired into that source but has not yet run, and the originating build owner retains its later complete VR package gate and sole headset runtime. Software delivery does not establish physical two-PC, different-home-network, room-fit or headset acceptance. No PR publication or main merge is authorized by this task.

## Deferred full native sharing

The earlier requirement for arbitrary native Edit Mode/modifier/material sharing was explicitly narrowed by the human to this existing simple version for the one-hour task. Full original-data synchronization remains deferred, not completed. Separate native file and Undo/Redo feasibility experiments do not change the Client's supported scope. Host/Client contract, automatic original-data transfer, full assets/history and concurrent editing require separate work with their existing owners.
