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
| Extrude | Actual selected face boundaries and normal arrows identify the captured faces. The action label distinguishes region movement from individual normal extrusion and any explicitly grabbed normal constraint. A line labelled a reference does not silently change native constraints. |
| Inset | Actual selected boundaries and boundary reference points, with the native thickness after acknowledgement. Native individual/outset/boundary/even/relative options remain in Blender. |
| Bevel | Native selected vertices/edges and reference points, with acknowledged amount/segments. Native Affect, profile, overlap and offset choices remain authoritative. |
| Loop Cut | Preview follows actual opposite edges through compatible visible quads. The slide arrow indicates increasing interpolation along the captured seed edge. Exactly one seed edge is required; invalid/conflicting rings are refused rather than guessed. |
| Knife | Actual sampled surface path with start/end points while held. Cut-through and selected-only choices are shown. The path is projected from the captured view; it is not an unrestricted 3D boolean. An overlong stroke is refused and cancelled rather than silently replacing its final path detail. |
| Merge | Captured variant and selected count. First/Last destinations are shown only with complete native selection order; By Distance shows its captured metric threshold. An unavailable cursor position is never invented. |
| Dissolve | Captured variant and selected count; Limited shows its angle. This is a discrete operation, with no pretend continuous deformation. |
| Delete | Captured component/domain and selected count before the deliberate gesture. A tap does not delete. Live deletion remains cancellable until release/commit. |

Component points and outlines use native IDs, not render-triangle indices.
Visual pools are bounded; this does not truncate the native selection submitted
to Blender. Transform, normal and cut guides retain their captured mapping during
the gesture, including reflected/nonuniform display arrangements.

Cyan snap targets identify the actual candidate in its displayed position.
Proportional editing shows the captured native radius/falloff where a truthful
spatial guide is available. Projected proportional mode uses Blender's native
view footprint, which is not exported; the label identifies this limitation
instead of presenting a headset-plane circle as the native influence region.

Acknowledged readouts describe the parameters Blender accepted. Controller paths
and previews may be ahead of the latest acknowledgement and are identified as
pending. A quaternion's shortest rotation angle is labelled as such; it does not
claim to measure accumulated controller travel.

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
