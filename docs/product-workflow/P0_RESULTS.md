# Windows P0 verification — 2026-10-24

P0 remains in progress pending shared gate review and a passing source/tag. The local
test candidate uses baseline ca03e83 plus Talia's headset fixes; upstream main has
since advanced, so these results do not certify the newer upstream release.

| Check | Result and evidence |
| --- | --- |
| Native reference | Known 20 mm cube and diameter 10 mm, height 30 mm cylinder. Corrected v2 shader colors; 59 save/fresh-reopen checks. Oracle/report in acceptance/native-reference/. |
| Physical colors | Talia confirms blue cube and orange cylinder in Quest 3S via USB Link. |
| Windows Player | Unity 6000.6.5f1 build succeeds; actual wired headset view and tracking observed. |
| Initial placement/recenter | Former fixed world origin put objects behind Talia. Local fix waits for tracked head pose and places display in front. B/Y or R recenters. Talia confirms comfortable front placement and stable world position during head turns. |
| Live native translation | Cube-only X -20 to -10 mm and restore. Talia confirms both directions; cylinder and native dimensions unchanged. Unity logged scene.update revisions 4/5 and correct local transforms. Earlier no-visible-change observation is preserved in #52; not reproduced with explicit ready/trace retest, no transport bug established. |
| Headset connection warning | Former IMGUI status was monitor-only, leaving a silent stale scene in VR. Local world-space status panel is readable in both eyes, lowered per Talia's feedback. Talia confirms clear stale/disconnected warning, automatic reconnect and unchanged display placement. |
| Python backend | ca03e83: 733 passed, 34 skipped on Python 3.13.13 after two Windows test-timeout fixes. Both tests still require ConnectionRefusedError; allowance increases from 1 to 5 seconds. Optional native/external-tool skips are not acceptance passes. |
| Native add-on | ca03e83 isolated background Blender check passes lifecycle, main-thread ping, native commands, save/fresh reopen and role checks. Every captured message with a schema validates. Earlier c743da4 interactive GUI lifecycle result is separate evidence. |
| Native CAD dependency | CAD Sketcher 0.32.1/slvs 3.2: Talia-PC rectangle 100 x 60 to 120 x 60 mm, Undo/Redo, save/reopen and subsequent dimension editing confirmed. Stored native measurement and solver status checked. XZ workplane; not VR CAD acceptance. |
| Local TLS readiness | Blender Python 3.13.13, OpenSSL 3.5.6, HAS_PSK True; isolated native TLS checks passed. |
| Two-PC event network | BLOCKED: Lee unavailable tonight, explicitly confirmed by Talia. Owners Talia and Lee. No peer acceptance inferred; interactive host LAN stays off. |
| Architecture/versions | Talia explicitly reviewed and accepted the documented architecture and verified Windows versions. Other teammate approvals are not inferred. Version table is in README; message contract is contracts/README.md. |

Current physical build: `p0-headset-status-lower-ca03e83-local`, managed
Assembly-CSharp SHA-256
`485b184ca8cef7f6354eed2b21c0db6650ce535c2e4f760424bf07550fe7a735`.
The interactive host used d32ace5 with the v2 fixture; the separate native add-on
check used ca03e83. The build is not evidence of an untested same-revision combined
host/client release. No frame-time or latency acceptance was measured.

Canonical public reports: #4 (fixture), #5 (P0/backend/native), #9 (network blocker),
#12 (Windows/headset warning), #15 (Talia review), #45 (placement), #52 (movement).
Detailed logs and machine inventory stay local under planning/ and outside Git.
Air Link, full table-placement UI, add/delete sync, controller modeling, voice,
two-PC editing and release acceptance remain later or separate gates.
