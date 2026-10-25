# Combined glass integration

Human requested the completed glass appearance on the current combined P2/P2.5/P3 application, preserving its controls and functionality. Base: f59f7ae7f6b0d59fd485f694c59ee94048174ae5. Appearance source: local 62dc3269e385c7480e0be0471564611bd73ba48d (compiled glass source 06c136a). Branch: codex/talia-combined-glass-ui.

Shared rounded glass panels, action states, typography, accessibility, curved screen/keyboard geometry and matching hit mapping are ported selectively. The native working image remains untinted. The private factory Blender companion theme changes supported widget colors and roundness without saving preferences or altering documents. Current window/dialog navigation, controller/mouse modes, screen lock, pointer choice, full keyboard, drawing, room/plane controls, object selection, native authority/history and release protections are preserved. The existing seven-column preview action layout is retained.

Settings → Voice transcription starts OFF on first use. Its saved toggle shows/hides the passive microphone/target/heard/result overlay and recognized-speech feedback. Voice recognition remains enabled. Missing-field questions, option choices, delete confirmation, errors and selection feedback retain their existing behavior and use shared glass backing. The monitor's typed voice fallback remains available.

The source glass branch has older functional files. Its HostLink/HostScene command handling, scene voice component changes and raw-pointer controller routing are not imported. In particular, existing stabilized pointer/grab routing and the held-workspace exclusion/stick-state fixes remain intact. Separate voice command chaining (#171) and participant/SpacetimeDB changes are excluded.

Verification uses actual Unity rendering, inverse curved pixel mapping, both controller pose formats, cumulative P1/P2/P2.5 gates and voice selection. CombinedGlassChecks additionally exercises default-hidden transcription, the real Settings collider toggle, persisted reload, hidden transient transcripts, retained selection feedback, missing-field/delete prompts, complete Arrange/Settings controls and panel bounds. Rendered previews use labeled synthetic pixels and do not establish live capture or physical acceptance.

No Player launch, PR action, main update, old accepted menu retest or FPS work is authorized by these software results. The prior running combined session is preserved. The package SOFTWARE-RESULTS.json and acceptance manifest record the exact final hashes, checks and pending physical gates.
