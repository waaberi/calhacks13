# Direct tool guides and availability

Blender's existing window remains the tool menu. Choose its mode, tool and
properties with the existing 2D controller input, then edit the floating model.
The new guides supplement that workflow. Headset usability remains unaccepted
until the wearer tests the matching candidate.

Trigger taps select or deselect native objects/components. SHIFT adds/removes.
Hold the trigger and deliberately move to start an edit; merely selecting a tool
does not change geometry. Blender updates during the held edit. Release commits
one native Undo step; grip or Escape cancels. Wait for Blender's actual rollback
before beginning another edit. Native 2D editing and native Undo/Redo remain
available.

| Tool | Visible feedback and intended action |
| --- | --- |
| Move | Red X, green Y and blue Z arrows; grab an arrow to move on its frozen native axis. Body free Move and plane handles remain. |
| Rotate | Coloured rings and arrowheads; sweep the grabbed ring around its captured pivot. |
| Scale | Coloured cube-ended axes and plane handles. Outward axis movement enlarges; inward movement reduces. The native multiplier uses Blender's acknowledged factor. Free body scaling retains its existing gesture. |
| Extrude | Actual selected face boundaries and normal arrows identify the captured faces. The native tool/options determine region or individual extrusion; a deliberately grabbed normal handle constrains the gesture. |
| Inset | Actual selected boundaries and boundary reference points. Native thickness and individual/outset/boundary/even/relative options remain in Blender. |
| Bevel | Native selected vertices/edges and reference points. Native amount, segments, Affect, profile, overlap and offset choices remain authoritative in Blender. |
| Loop Cut | Preview follows actual opposite edges through compatible visible quads. The slide arrow indicates increasing interpolation along the captured seed edge. Exactly one seed edge is required; invalid/conflicting rings are refused rather than guessed. |
| Knife | Actual sampled surface path with start/end points while held. Native cut-through and selected-only choices remain in Blender. The path is projected from the captured view; an overlong stroke is refused and cancelled rather than silently replacing its final path detail. |
| Merge | Selection points and the native destination when known. First/Last destinations require complete native selection order. The variant and By Distance threshold remain in Blender; an unavailable cursor position is never invented. |
| Dissolve | Selection points identify the affected geometry. The native variant and Limited angle remain in Blender. This is a discrete operation, with no pretend continuous deformation. |
| Delete | Selected component points/outlines before the deliberate gesture. A tap does not delete. Live deletion remains cancellable until release/commit. |

Component points and outlines use native IDs, not render-triangle indices.
Visual pools are bounded; this does not truncate the native selection submitted
to Blender. Transform, normal and cut guides retain their captured mapping during
the gesture, including reflected/nonuniform display arrangements.

Cyan snap targets identify the actual candidate in its displayed position.
Proportional editing shows the captured native radius where a truthful spatial
guide is available. Projected proportional mode uses Blender's native view
footprint, which is not exported; no headset-plane circle stands in for it.
The deliberate left-hand Guide explains these limits and native options.

Automatic tool instructions, hover commentary and parameter paragraphs are
hidden. The requested scale multiplier is retained as one concise line:
`Scale ×… · pending/Blender` for native edits, or `Display scale ×… · VR view`
for arrangement. The Blender-labelled factor comes from its acknowledgement;
pending controller feedback does not claim native acceptance. Detailed written
steps are available on demand in the left-hand Guide. Genuine editing refusal
and unsupported-feature popups remain available.

Unsupported direct features show **This feature isn't available yet in 3D** when
an edit is attempted. Supported tools with the wrong mode, selection, model or
settings show the specific requirement instead. Spatial box/lasso/circle sweeps
remain separate from supported trigger-tap selection. The Blender 2D view stays
available for those tools.

The independent availability popup stays at its opening world pose, wraps/pages
long explanations, and does not capture controller input or replace voice review.
It distinguishes a refused attempt from an already started live preview that
must finish cancellation. A refusal never becomes a delayed edit after input
release, permission, or a late acknowledgement.

G/R/S start Blender's native 2D modals; finish or cancel them before a direct
gesture. Existing document/host identities, generations, exclusive leases and
acknowledged native-input handoff still apply.

The separate multi-user integration chat must compose these changes into its
latest source and rerun its integration gates. This guide alone does not establish
multi-user, two-PC, microphone, room alignment or physical headset acceptance.
