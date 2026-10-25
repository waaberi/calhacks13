# Voice command chains and editing additions

The command expansion from `codex/talia-voice-command-chaining` (`182033e`) is integrated semantically into the current P2/P2.5/P3 glass candidate, preserving its newer UI, room/controller work and native-input protections. Use the matching Player and complete add-on package together. The candidate stays unlaunched until the human requests the runtime switch; software checks do not establish headset acceptance. Preserve the existing running session and unsaved Blender documents.

## Combining commands

Say supported editing commands in order, separated by **then**, **and then**, or **and** followed by an action. Examples:

* “Add a cube, then move it twenty centimeters along x, then rotate it forty-five degrees around z, then scale it down fifty percent.”
* “Duplicate it ten centimeters along y, then colour it blue, then set its height thirty millimeters.”
* “Select Shaft, then bevel the edges two millimeters, then shade smooth.”

This is a general composer over the core editing handlers and existing curated operation registry. There are no pair-specific combination rules and no language model. “It” follows the current target, including an object created/duplicated earlier in the same sequence. An explicit object name or Select step changes that target. The final applied receipt updates local VR selection to the actual final object; native Blender selection remains unchanged.

The whole sequence is parsed before editing. Missing target, axis, amount, units, colour or modifier choice prompts for that detail while retaining all steps. Controller selection can answer a missing-target question. Cancel, timeout, disconnect, document changes and changed/deleted captured targets invalidate unfinished plans. A new editing utterance replaces an unfinished plan.

One sequence is one native command, scene publication and Undo step. Undo reverses the entire sequence; Redo reapplies it. Reversible steps use private in-memory object/data/modifier backups; failures restore earlier steps and remove creations without saving/reopening the document. Deletions wait until other steps succeed and require deliberate controller confirmation with the deletion targets displayed. Unexpected native exceptions retain the existing unknown-outcome/reconciliation behavior and are never automatically retried.

Undo, Redo, Cancel and Save are request/history controls: say them separately, not inside a modeling transaction. Recognized-but-unsupported operations (for example Join, Hide and Edit-Mode-only Extrude) do not become supported merely by chaining. Normal context/type, linked-data, lease, revision, transform and geometry-budget restrictions still apply. A default Remesh can exceed the inherited geometry budget in a millimeter scene; the entire sequence is then refused without publishing an earlier step. Up to 24 steps and 500 transcript characters are accepted; speech recognition can still mishear words and requires headset acceptance.

## Additional editing commands

| Feature | Examples and meaning |
| --- | --- |
| Shrinking and signed scaling | “Scale it down twenty percent” multiplies by 0.8. “Scale it up twenty percent” multiplies by 1.2. “Scale it along x by two” affects only local X. “Scale it along negative x by two” or “scale x by negative two” mirrors/scales that axis. Zero factors are refused. |
| Colour | “Colour it red”; “make it lighter”; “make it darker”; “reset its colour.” Named colours: red, green, blue, yellow, orange, purple, pink, cyan, white, black, gray/grey and brown. Changes uniform object-linked Blender material slots and synchronized VR colour without recolouring another user of a shared material/mesh. Reset restores the previous slots/materials if still available. |
| Duplicate | “Duplicate it” or “duplicate it ten centimeters along x.” Makes an independent object/data copy; later “it” targets the copy. |
| Dimensions | “Set its width twenty millimeters”; “set its depth two centimeters”; “set its height thirty millimeters.” Width/depth/height are native local X/Y/Z bounding dimensions, including scale. Other dimensions are preserved or the sequence is refused. Values are physical distances in either meter or millimeter scenes. |
| Reset | “Reset its rotation” resets local rotation; “reset its scale” restores positive local scale 1/1/1. These are not Apply Rotation/Scale. Location is preserved. |

Compact creation placement is also accepted: “Add a cube at x twenty centimeters” sets X=0.2 m, with the usual core Add origin/default 50 mm size. “Add a cube twenty centimeters along x” adds then moves it along world X. “Twenty centimeters **from the x axis**” is ambiguous and is refused with an explanation; say **at x** or **along x**.

## Integration and verification

New hosts advertise `voice.grammar.composition=true`. New clients explicitly opt in with `voice.resolve.composition=true`; legacy requests retain the old resolver. Clarification uses an expiring, connection/document-bound continuation token. Ready plans are stored on the host and consumed once by the existing `voice.run` request. The client never supplies an executable operator. Every existing target's generation and lease is checked at admission, including targets beyond the command's primary target. Parameters are checked again natively.

When native preview Input is ON, both resolution and execution use the combined build's acknowledged helper release, native-end and fresh-owner-state barrier. The input session is released before a plan captures the scene. Session/document/actor identity and the selected object's generation are frozen and checked again after the handoff; changes refuse the queued intent instead of retargeting it. A modal operation or drawing draft must be finished/cancelled first. Input stays OFF after the handoff. The existing controller-based 2D Blender editing remains available by enabling Input again.

Whisper preserves every word of an opted-in composition transcript, including unsupported tails; grammar snapping must not silently discard a later step. The Vosk fallback receives the expanded grammar. New generic-detail and sequence-confirmation clips use the repository's pinned redistributable Piper voice and carry matching text metadata.

Verification entry points:

* `pytest tests/backend`: parser, full backend/contract/lease regressions and real-socket plan admission.
* `dotnet test tests/voice/VoiceCore.Tests.csproj`: conversation routing, clarification/cancel/expiry, destructive confirmation, no prefix fallback, raw Whisper transcript preservation and existing voice tests. `VOSK_MODEL` plus the packaged native DLL directory enables actual offline Vosk tests.
* Background Blender: `tests/backend/voice_sequence_blender_check.py` in a fresh disposable process. Actual native values, one Undo/Redo, rollback (including conversion, existing modifier pointers and an injected post-delete failure), shared-material isolation, 23 existing curated operations in chains, unit scales 1/0.001 and save/reopen.
* Unity: `VoiceCompositionChecks.Windows` runs production conversation/receipt routing, actual selection/no-drag/controller and cumulative P2/P1 gates, then builds Windows. This is software verification, not headset acceptance.

The original isolated evidence remains on its preserved feature branch at `acceptance/voice-command-chaining/software-manifest.json`. Current combined delivery evidence is recorded separately with its matching source/package; issue #171 tracks integration and the still-pending physical checks. No PR or main merge is implied by this delivery.
