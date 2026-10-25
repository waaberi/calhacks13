# Voice expansion in the combined glass candidate

The integration starts from combined source `ef74f0f` on `codex/talia-direct-edit-voice-integration`. It imports the complete voice feature delta from `db0dc2489f9d3757d55c65c3971f403e0aa23c36` to `182033e0871b6d003e93f2e7e57a1b3a0139d19c`, including implementation commits `f5ae3fa595a9f6c6fb2f567fcafd9b5de88817a5` and `0826a4279a9a05ae50070b83bc34b5ef5e9901e8`. The original combined and voice branches remain preserved. No old Player, package, accepted XR configuration or complete old application file replaces the current combined build.

## Included feature surfaces

The source delta spans 36 files. The historical isolated `acceptance/voice-command-chaining/software-manifest.json` is deliberately retained on its original branch rather than presented as evidence of the new combined candidate. The other 35 feature files are integrated, including the selection checks merged by the combined owner.

| Surface | Included changes |
| --- | --- |
| Native Blender | Complete deterministic composer and atomic sequence executor, resolver/grammar/continuations, commands admission for every captured target, material colour synchronization, single Undo/Redo transaction and rollback. |
| Protocol | Grammar capability and explicit composition opt-in, clarification/continuation fields, whole-sequence candidates and final-selection receipts. Current combined sketch solver receipt fields remain supported. |
| Voice runtime | Conversation routing, missing-detail questions, replacement/cancel/expiry, destructive sequence confirmation and no partial-prefix fallback. |
| Recognition/audio | Whisper preserves full composition transcripts, expanded Vosk grammar, generic detail and sequence confirmation clips with matching metadata. |
| Unity UI | Host capability negotiation, existing glass question panel, final object selection from native receipt, existing hidden transcription/selection-popup preferences and existing trigger select/deselect behavior. |
| Regression checks | Backend composer/lease/socket checks, actual Blender sequence checks, .NET composition/recognition tests and Unity composition/selection checks. |

## One native writer

Input ON still permits controller editing of the 2D Blender window. Voice resolution and `voice.run` both use the combined acknowledged helper-release/native-end/fresh-owner-state handoff. Local Input OFF alone is insufficient. The request keeps a stable ID, immutable complete payload, original session/document/actor identity and original selected-target generation. A changed identity or generation refuses the delayed request instead of retargeting it. Disconnect/re-welcome invalidate delayed resolutions.

Voice and direct controller edits share a single pending handoff. A second request cannot replace the first. Native modal operations, a pending native transaction and a drawing draft prevent a new writer. A voice request may discard a purely local uncommitted direct gesture; it cannot cancel or overwrite a submitted native transaction. Native target generations and ordinary linked-data leases are still checked immediately before the write, including every pre-existing object referenced later in a voice sequence.

The native receipt's `selection.id` updates the actual final voice target without dragging it. Newly added/duplicated/selected objects become the subsequent “it”; the native desktop's selection remains under Blender's own controls. Deletions require deliberate confirmation, and Undo/Redo/Cancel/Save remain separate utterances.

## Validation and remaining limits

The combined candidate's delivery manifest and external `evidence/direct-edit-voice-v1` directory record final test logs, source/package hashes and the current limits. The isolated voice manifest is historical evidence only. `voice-feature-provenance.json` records every path in the source feature delta and identifies exact imported blobs versus semantic merges.

The deterministic composer accepts at most 24 steps and 500 transcript characters. It supports existing curated editing operations and the documented scale/material/duplication/dimension/reset additions; unsupported clauses refuse the whole sequence. Voice modeling still requires native Object Mode. Mesh Edit Mode direct controller gestures have their own typed native-tool path; leave Edit Mode before issuing Object Mode voice modeling chains. Existing linked-data, lease, transform and geometry-budget restrictions remain in force. Unexpected native exceptions preserve unknown-outcome/reconciliation behavior and are never retried automatically.

Actual Whisper/GPU and new Quest speech/controller acceptance remain distinct from offline/parser/software checks. New room physical alignment, the latest controller visuals and new direct-edit/voice usability require the human's confirmation. The existing Player/helper/native process and all personal unsaved Blender sessions stay intact. The integration candidate must remain unlaunched until the human explicitly requests the runtime switch. No PR action, main action, FPS work or repeated accepted old-menu test is part of this integration.

## Short headset check after an authorized switch

1. Use the 2D Blender panel with controllers, then say “Add a cube, then move it twenty centimeters along x, then colour it blue, then scale it down twenty percent.” Input should release safely; all steps appear together and the new cube becomes selected. Undo once, then Redo once.
2. Say “Duplicate it ten centimeters along y, then set its width twenty millimeters, then reset its rotation.” Confirm the copy is independent and subsequent “it” targets the copy.
3. Try axis scaling/mirroring, lighter/darker and colour reset. Zero scale and an unsupported tail must leave the model unchanged.
4. Omit an axis or unit, answer the question and confirm nothing ran before the answer. Cancel or let a question expire, then issue a fresh command. A destructive chain must display its target and wait for deliberate confirmation.
5. Return Input ON and edit in the 2D panel again. A running Blender modal must be completed/cancelled before voice or direct 3D edits can take ownership. Follow the separate direct-controller checklist for Move/Rotate/Scale/component Extrude and one-gesture Undo/Redo.
