# Final P2 and complete P2.5 integration

The integration branch `codex/talia-p2-p25-integration` starts at final P2's
`d3230cdbc8a93188d4c4f0e0bff4e1a6ac497cc4` and merges the complete P2.5 branch
`3ab38b2fb95b0b9cf84b93ba36953bb90c878149`. It includes the native command,
lease, receipt, sketch solver/history, helper and protocol foundations already
needed by P2.5. Voice and unrelated P3 work are outside this integration.

## Accepted baseline and overlap decisions

The rollback is the complete accepted final P2 Windows folder built from
`2e9ede306c075c74ed82d3e71e55e4d77fc17a09`; its managed assembly SHA256 is
`4c90429a36cce43da5e4b9dc88faa5d9921c5b56f03fa49592c365bc45953568`.
General physical acceptance was recorded on `115c5f4`, followed by the narrow
vertical-front correction. Integration requires its own physical acceptance.

| P2 behavior | Integration decision |
| --- | --- |
| Worn, VR-focused, tracked, settled shared startup; world anchoring | Retain current HostScene and placement lifecycle; add only P2.5 material access and desktop-key isolation |
| Room origin conversion, current-room safeguards, passthrough | Retain current P2 room/localization/geometry/passthrough sources unchanged |
| Settings gear, hidden-default geometry, independent planes, delete/Align, vertical-front creation | Retain final P2 implementation and final checks unchanged |
| Same-device grip/aim, both pose formats, aim-based movement, tracking-loss cleanup | Retain P2 paired reader and movement; route preview only after nearest P2 controls/planes; grip stays arrangement input |
| Controller replacement during preview editing | Also suspend P2.5 native input when P2 replaces a device, or detects loss before render; retain the release-acknowledgement barrier |
| Physical 1:1/inspection scaling, placement, pin/dock/recenter, menus | Retain current P2 scale and table code; suppress desktop shortcuts only while P2.5 owns native keyboard input |
| Clear live capture, magnify/pan, render/XR settings | Retain freshness/visual gates; add exact frame/window matching and isolate native scrolling from inspection pan |
| Native coordinates, units, geometry, Undo/Redo | Native commands/solver/history remain authoritative; viewer magnification does not alter numeric payloads |
| Desktop versus VR startup | Preserve `--desktop` opt-in. The VR launcher never supplies it |

There was no blanket file replacement or ours/theirs conflict resolution. The
three overlapping files merged additively; BlenderScreen carries the complete
P2.5 input/capture metadata changes. HostLink is retained from P2. The separate
VoiceCore trial's welcome-document tracking is not imported; P2's snapshot epoch
and new-document resets remain intact.

P2.5 retains whole-image pointer/drag/scroll, keyboard/modifiers, owned dialog and
popup following, nested return, window chooser/focus recovery, independent
process lifetimes, matching new frames, cleanup acknowledgements, no queued action
replay, modeling/numeric/shortcut tools and native line/circle/rectangle drawing.
The P2.5 launch flag and helper input opt-in are supplied by the assembled launcher.

## Verification and failed evidence

Run `P25Build.Windows` against this branch's final `P2Checks.Windows`, rather than
the older P2 checks in the P2.5 source branch. This includes final physical-scale,
independent-plane, Settings, placement, arrangement, paired-controller, P1 aim,
startup, visual/alpha, room-localization and capture-freshness checks. Keyboard
isolation remains last. Actual dialog HTTP, release HTTP and existing HTTP checks
run in separate Unity Editor processes. Supply final P2's exact private recorded
room and independent native-AppSpace fixtures using `CALHACKS_ROOM_REPLAY` and
`CALHACKS_ROOM_SPACE_REPLAY`.

The first integration run used a different room capture and failed the wall-normal
assertion. That failure is retained. Final-P2's exact paired recorded fixtures
must pass without assertion changes. SDK-generated first-import settings are
archived, inspected and restored; they are not product changes to commit.

Python reference: 904 passed / 36 skipped. Helper reference: 142 passed. The
integration adds five launcher-safety checks, so the expected helper total is 147.
Real background native preview/create/reopen, modeling and object/history checks
run at unit scales 1 and .001, plus the 60-assertion native panel/keymap check.
All source/build hashes, logs, initial failures and generated-settings archives
remain in the local integration evidence directory. Runtime input/capture and
headset acceptance cannot be inferred from software checks.

## Complete test folder and runtime handoff

Keep the whole assembled Windows folder together: EXE/data/runtime libraries,
`support`, matching `addon`, pinned `CAD_Sketcher`/solver, `python-deps`, disposable
`reference.blend`, `test-config.json`, `package-manifest.json`, and `rollback-p2`.
`Validate-Package.ps1` checks hashes without starting or inspecting applications.
`Start-Integrated-Test.ps1` is for the explicitly approved runtime handoff only.
It refuses any existing Player before starting a new private Blender or helper.
It never closes applications, stops services, changes the old capture selection,
opens the original document, or saves personal Blender work. It uses separate
native/capture ports, verifies the exact private host/window, and waits for fresh
matching pixels before launching the VR Player. New session records identify all
owned processes. Original P2 native/helper and personal Blender remain preserved.

The integration owner must recheck live process identities, coordinate the sole
P2 runtime owner, and obtain the human's go-ahead before replacing the accepted
Player. Rollback uses the bundled unchanged P2 binary with the retained original
P2 native/helper after cleanly releasing the integrated Player's runtime slot.
No PR change or main push/merge is authorized.

## Short focused physical trial

1. Wear the headset at startup: workspace in front, passthrough/room fit stable.
   Move/release the screen and model with each controller; briefly confirm scale,
   a vertical plane's front creation, and one existing room alignment. Do not
   repeat the accepted menu walkthrough.
2. Focus Blender. Use a real button, drag a native control, scroll a panel, type
   and modify a numeric field, and use a modifier shortcut. Watch a deliberately
   changing native viewport for live, clear capture.
3. Open a native menu and a dialog, then a nested chooser if available. Close or
   cancel them in reverse order; the preview must return to the parent/main
   window. Exercise Windows / dialogs and current-window focus recovery.
4. Interrupt a held native gesture with tracking/focus loss. Resume with a fresh
   gesture; no stuck mouse/modifier, queued edit replay, or leaked reservation.
   Check that normal P2 grip movement still works afterward.
5. Choose Draw in VR, create/select a native sketch, and draw a line, circle and
   rectangle. Confirm actual Blender solver geometry and native Undo/Redo.

Record exact build/hash and each observation. Stop and repair a P2 regression or
restore the rollback; software success is separate from physical acceptance.
