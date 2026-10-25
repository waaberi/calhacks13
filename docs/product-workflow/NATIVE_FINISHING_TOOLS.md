# Native finishing tools

These typed operations are available to reviewed modeling recipes through the
shared Blender command service. Blender's existing view remains the modeling
menu. No additional VR tool menu or automatic mode change is introduced.

| Family | Operations |
| --- | --- |
| UV | Pin/unpin selected faces; select the exact UV-connected island; pack selected islands; weld nearby UV endpoints belonging to the same native vertices; average island scale; activate/copy a UV layer. |
| Vertex groups | Create, rename, remove and lock a named group. |
| Weights | Assign/add/subtract or remove weights on selected vertices; normalize while preserving locked groups; smooth a group's weights over native edge neighbours. Object and single-mesh Edit Mode are supported. |
| Materials | Change fixed Principled shader values using an independent copy of the target's material; remove an exact material slot. Existing shared source materials remain intact. |
| Collections | Create, rename or change viewport/render visibility; link/unlink the selected object while retaining another collection. |
| Curves | Add Poly/NURBS/Bezier splines, set point coordinates/radius/tilt, remove splines, and set curve bevel/extrusion/resolution/fill settings. Coordinates and lengths use local-axis metres. |
| Mesh finishing | Project selected vertices to another evaluated native mesh surface with a metric distance/normal offset; smooth selected vertices; poke faces; join compatible triangles to quads; inverse subdivision. |
| Sculpt data | Set exact native vertex mask weights or face-set identifiers. These operations edit native attributes; brush-stroke controller support is separate. |
| Rigging | Set/reset FK bone pose channels; add/update/remove one owned native IK constraint; bind/unbind a mesh through existing bone-named vertex groups and an owned Armature modifier. |
| Animation | Insert/delete native bone pose keyframes, set object-channel interpolation/handles, and set frame range/FPS. Existing NLA and driver workflows remain in Blender's native editors. |
| Camera/light/text | Set bounded lens/projection/clipping, type-specific light values, and native text contents/alignment/metric size/extrusion/bevel. Text continues through evaluated scene geometry. |
| Modifier editing | Add Simple Deform, Cast, Displace or Edge Split; configure fixed reviewed fields on those and existing Bevel, Subdivision, Solidify, Array, Decimate, Mirror, Weld and Smooth modifiers. |

UV and mesh-finishing tools require the existing active single native mesh in
Edit Mode. Curves, collections, material slots and vertex-group definitions use
Object Mode. The user chooses modes in Blender. Mesh targets must be local,
single-user and free of shape keys; direct mesh mapping also requires the
current unmodified base mesh. Shader properties cover base colour, metallic,
roughness, alpha, IOR, transmission, coat, subsurface and emission.

UV welding merges only selected UV endpoints of the same native vertex, within
the requested UV-space distance. It preserves pin anchors and refuses
conflicting pinned positions. It does not run an interactive UV stitch editor.
Surface projection is all-or-nothing: every selected vertex must hit the
requested surface within the admitted distance. Collection operations require
document-wide command ownership because their effects can extend beyond one
object.

The caller owns fresh document/target generations, validation, native authority,
the complete operation's Undo step and streaming. `modeling_extras.preflight`
performs read-only admission; `apply_step` never pushes its own Undo step.
`ExtraBackup(steps, editor)` complements the shared object/data backup. On an
execution failure, restore the shared backup first, then `ExtraBackup.restore`,
and close both. This restores group definitions and native weights, collection
names/settings/links/memberships, and active material/group indices. Mesh/curve
data and material slots remain covered by the shared backup. Node edits operate
only on independent material copies.

FK pose and bone-keyframe operations require the current single native Pose rig;
the user enters Pose Mode in Blender. Bone locations use local pose-channel
metres and quaternion rotations use `[w,x,y,z]`. IK accepts only the exact owned
association; it refuses foreign constraints and targets that would introduce a
native dependency cycle. Skin binding uses explicitly created matching groups
and weights rather than guessed automatic weights. Camera and light properties
change the native Blender scene; the current floating renderer does not promise
identical native lighting or shader appearance.

Atomic rollback also restores posed channels, owned constraints, action bindings
and timeline state when those families are used. Action edits use independent
copies so existing action contents remain intact before successful commit.
Base recipes do not inherit finishing-specific scene bounds. Newly created IDs
are staged without publishing an intermediate scene. The read-only
`context_fingerprint(objects)` covers native pose/bone selection, UV/group data,
materials, curves, animation and collections that may change without altering
the streamed mesh. The host includes and rechecks it in the captured recipe
context; callers can pass all captured targets rather than only active objects.

The native software gate executes every offered operation in disposable factory
Blender processes and checks exact selected intent, metric units, rollback and
native history. These checks do not establish headset/controller acceptance or
identical shader appearance in the floating renderer.
