# Combined glass integration

## Current wearer-requested corrections

Input controls are a compact, captions-only two-row panel sharing the native
image's exact cylindrical surface. Undo placement, Recover workspace, Reset view,
Hide Blender and the BLENDER heading are removed from the surrounding frame;
other Arrange/Settings controls remain accessible. A nearby position-lock button keeps
the screen fixed and enables the side-grip native mouse action. The grip-menu
placement instruction is removed.

The left-hand menu also removes Select object, Pin menu here and Recover
workspace. Direct trigger selection and Clear selection remain available. Its
docked size is one third of the previous menu; gripping it restores the existing
full world-menu size. Returning to the hand shrinks it once, preserving fresh
tracking requirements and the accessibility size multiplier.

The v10 raw pointer was physically rejected as shaky/skipping while held objects
were smooth. Logical UI hits and the visible cylinder/ray now share the existing
stabilized aim. A held pointer ends at its actual smooth local contact and ignores
unrelated nearer surfaces; cylinder direction is derived after that pose update.
The object filter and manipulation path stay unchanged. Free-pointer queries
synchronize moved colliders without another click. Stick depth keeps no old cap.

Quick controls preserve native input ownership. Temporary pointer occlusion
discards the gesture, resynchronizes the same authoritative window and confirms
release before new input. Rejected actions are never replayed. VR drawing is a
separate mode, clearly labelled ON; native preview input yields its reservation.

Voice transcription and Selection popups are separate saved Settings toggles,
both OFF on first use. Actionable questions, confirmations and errors stay visible.
The separate larger sample has a 200mm cube and 100mm by 300mm cylinder; original
engineering fixture and accepted rollback are preserved.

Room reloads stage replacement data and retain valid anchors on empty replies.
Continued retries and private UUID references request fresh SDK localization;
old world poses are never replayed. Software checks, actual final room readback
and physical room fit remain separate evidence gates.

## Original appearance-integration record (historical)

Human requested the completed glass appearance on the current combined P2/P2.5/P3 application, preserving its controls and functionality. Base: f59f7ae7f6b0d59fd485f694c59ee94048174ae5. Appearance source: local 62dc3269e385c7480e0be0471564611bd73ba48d (compiled glass source 06c136a). Branch: codex/talia-combined-glass-ui.

Shared rounded glass panels, action states, typography, accessibility, curved screen/keyboard geometry and matching hit mapping are ported selectively. The native working image remains untinted. The private factory Blender companion theme changes supported widget colors and roundness without saving preferences or altering documents. Current window/dialog navigation, controller/mouse modes, screen lock, pointer choice, full keyboard, drawing, room/plane controls, object selection, native authority/history and release protections are preserved. All twelve preview actions are retained in a centered six-by-two grid; basic keyboard rows use one consistent thirteen-column grid with inset text.

Settings → Voice transcription starts OFF on first use. Its saved toggle shows/hides the passive microphone/target/heard/result overlay and recognized-speech feedback. Voice recognition remains enabled. Missing-field questions, option choices, delete confirmation, errors and selection feedback retain their existing behavior and use shared glass backing. The monitor's typed voice fallback remains available.

The source glass branch has older functional files. Its HostLink/HostScene command handling, scene voice component changes and raw-pointer controller routing are not imported. In particular, existing stabilized pointer/grab routing and the held-workspace exclusion/stick-state fixes remain intact. Separate voice command chaining (#171) and participant/SpacetimeDB changes are excluded.

Verification uses actual Unity rendering, inverse curved pixel mapping, both controller pose formats, cumulative P1/P2/P2.5 gates and voice selection. CombinedGlassChecks additionally exercises default-hidden transcription, the real Settings collider toggle, persisted reload, hidden transient transcripts, retained selection feedback, missing-field/delete prompts, complete Arrange/Settings controls and panel bounds. Rendered previews use labeled synthetic pixels and do not establish live capture or physical acceptance.

No Player launch, PR action, main update, old accepted menu retest or FPS work is authorized by these software results. The prior running combined session is preserved. The package SOFTWARE-RESULTS.json and acceptance manifest record the exact final hashes, checks and pending physical gates.


## Initial physical rejection and stability correction (historical)

The human physically rejected v4 as extremely choppy/glitching, with misaligned buttons and bugged controllers. The rejection remains authoritative. Stability correction removes unconditional idle/selected/hover geometry invalidation and repeated style resets; explicitly compiles the actual glass copy/blur/surface stereo variants; keeps controller bodies on current device aim independently of held-contact/ray stabilization; and aligns button grids without dropping actions. GlassStabilityChecks invokes actual dirty callbacks, real complete UI factories and D3D texture-array GPU readback for two distinct eye layers (copy, both diffusion passes, surface and metallic controller). Updated actual BeforeRender/RenderHand tests cover both pose formats/hands, rapid samples, recenter, loss and held-contact separation. New software passes are not physical acceptance.

The final render review also fixes split keyboard captions, keeps capture/status text below large overlays, and increases typing/dialog background opacity so dense native UI cannot bleed through the labels. Key/action names and callbacks remain unchanged.
