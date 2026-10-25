# Combined P2 / P2.5 / P3 Windows candidate

This candidate starts from complete P2/P2.5 `96f1093`, merges P3 `1635668`,
and reconciles the newer `db0dc24` selection toggle and its existing reviewed
voice/HostLink/Client dependencies. It preserves the entire integration history;
it does not substitute the older original P2.5 branch. No new voice commands,
curvature, WAN/store implementation, FPS work, PR changes or main changes.

## Deliberate overlap decisions

| Area | Combined behavior |
| --- | --- |
| Editing surface | P3's native Blender tools, sketches, numeric fields, constraints, Undo/Redo and file menus; duplicate VR modeling palettes stay retired. Generic basic/full keyboard and modifiers retain access to shortcuts. |
| Controller/lock/feedback | Latest Quest front-left/locked-side-right/stick-wheel/pressed-stick-pan, explicit lock in preview and Settings, mouse fallback, button pulse, persistent toggles and actionable input state retained. |
| Pointer hand | P3's persistent Settings selection releases input before handoff; Settings displays the current hand. |
| Selection | Stabilized controller mesh rays select/deselect actual 3D UUIDs without dragging. Preview/UI/plane occlusion wins. Grip movement and alignment remain separate. Named voice targets retain precedence over "it". |
| Gesture ownership | A hand already holding a workspace target, or placing the table, cannot inject Blender input when its ray crosses a locked image. The actual held-stick state reaches the preview; temporary Shift/middle releases balance and wheel events are excluded during pan. |
| Host identity | New HostScene command/voice events keep welcome document/open epochs separate from applied snapshot identity. The latest P2 readiness/recenter and desktop-keyboard isolation remain intact. Stable request IDs, native revisions/generations, receipt and lease checks remain authoritative. |
| Capture | Input-aware owned-dialog/window lifetime and matching-frame geometry retained; reviewed upstream encoder exception/recovery logging reconciled around that path. JPEG100/4:4:4, private UI1.5 and reviewed texture sampling retained. Non-P2.5 defaults retained. |
| Ownership/Client | P3's actual-writer presentation retained without changing native reservation. Newer reviewed Client request/result/receipt paths preserved rather than replacing them with older P3 files. |
| P2 environment | Startup/world anchoring, room conversion/current-room safeguards, passthrough, independent planes, vertical-front placement, aim dragging and actual size retained. Exact final P2 fixtures and34 frozen Standalone XR flags remain mandatory. |

## Acceptance limits

Strict production prevention #87/RC16 remains **FAIL**. The isolated authority
prototype is diagnostic, not enabled in production: it does not map arbitrary
native mesh/modifier/Outliner/script/CAD-tool edits to validated commands. The
software prototype does not establish full native GUI authority or OS isolation.
Separately merged upstream #165 local SpacetimeDB work does not resolve that
restriction and is not silently imported as a new architecture here.

Existing physical failures are retained: repeated input activation loss;
subsequent narrow15-second activation stability only; ineffective controls and
missing feedback; unaccepted headset clarity; prior inaccurate room guides.
Latest controller-v11 was never launched. The separate selection-toggle and
visible45-degree rotation pass on `db0dc24` is narrow and does not physically
accept this combination. Real GUI/live same-document capture, controller drawing,
readability, two-PC and full phase acceptance remain separate gates.

## Complete package and handoff

Use the whole packaged folder; do not copy DLLs between builds.
`Validate-Package.ps1` checks the manifest without launching applications.
`Start-Integrated-Test.ps1` creates a new disposable native document/profile,
matching helper and VR Player on isolated ports after explicit owner/human
handoff. It refuses an existing Player and never closes or saves another session.
VR launch has no desktop-camera fallback. `--desktop` inspection is separate.

The package contains unchanged final P2 application rollback (`2e9ede3`, DLL
`4c90429a36cce43da5e4b9dc88faa5d9921c5b56f03fa49592c365bc45953568`),
matching historical native/helper sources, dependencies and restoration notes.
The runtime owner must recheck current process/window identities and restore the
retained original P2 host/helper selection before the rollback launcher is used.
Historical PIDs alone never authorize a stop or replacement. Unsaved private and
personal Blender documents remain open; no save/reset/reopen is required.

Do not launch this candidate while the other chat owns the headset. Software
success and physical acceptance must be reported separately. Exact final hashes
and gate results accompany the package and its local evidence manifest.
