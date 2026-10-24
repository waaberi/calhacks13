# Demo steps and engineering expectations

Owner: Talia. Prepared during P0. All VR, CAD, voice and collaboration outcomes below remain pending until tested on the actual build.

Talia approved the reference dimensions on October 23, 2026: 20 mm cube, cylinder diameter 10 mm and height 30 mm, and the plan's 100 x 60 mm sketch changing to 120 x 60 mm. USB Link Desktop and the guided hardware/audio exercises have user-reported success; the custom application's runtime and modeling acceptance remain separate.

1. Open a copy of `samples/mechanical/p0_reference_v2.blend` in Blender 5.2.2. Show the cube's 20 x 20 x 20 mm dimensions and the cylinder's 10 x 10 x 30 mm bounds. Confirm Metric, unit scale 1.0, millimeter display, Z up and applied scale.
2. Enter the Windows app through wireless Quest Link, check both controllers, and show/hide the app's changing Blender-window panel. Record the app build and connection failures.
3. Place the virtual table. Move, add and delete an object in desktop Blender and observe automatic VR updates. Moving the table must preserve native dimensions and history.
4. In VR, move the cube +10 mm on X and rotate +90 degrees about Z. Confirm native X = -10 mm, unchanged dimensions, and numeric Z rotation = 90 degrees. Check Undo/Redo and Save/fresh reopen on the editing copy.
5. Create a real constrained 100 x 60 mm rectangle with an anchored corner, coincident corners and horizontal/vertical edges. Change width to 120 mm; height stays 60 mm. Reject an inconsistent constraint while preserving the last valid editable sketch. This requires the actual solver; it is not part of the primitive fixture.
6. With several objects and no target, say “Rotate this object 90 degrees.” Hear the clarification, select the target, supply an axis if asked, and complete the retained command exactly once. Verify the native result with the actual Quest microphone and audio.
7. With Lee Jae-yeon on the second Windows PC, edit two different objects, attempt a same-object conflict, and disconnect/rejoin. Both Blender windows and VR must agree without duplicate edits or lost saved data.
8. On the release candidate, check required material/UV preservation, native render/export units, and final Save/fresh reopen. Record the build, actual result and failures. Repeat the integrated demo twice before declaring P6 passed.

For P0 now, complete step 1 and the hardware checklist in `docs/product-workflow/PHASE_0_GUIDE.md`. The remaining steps describe the expected product and are not evidence that those features exist.
