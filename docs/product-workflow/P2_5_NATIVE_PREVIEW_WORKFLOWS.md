# P2.5 underlying native preview workflow checks

These checks execute actual Blender operations and the native preview handlers in
new factory-startup **background** Blender processes. They do not establish mouse
delivery, hover, scrolling, native button hit testing, OS window focus, capture,
modal event-loop interaction or headset acceptance.

`tests/p25/native_preview_workflows.py` uses the actual `Session`, `Commands`,
`Leases`, `Editor`, `NativePreviewSessions`, native tool-state query and scene-sync
code with `bpy.context`. Its local dispatch transport deliberately opens no socket
or listener. Connection objects only collect the real handlers' responses. Native
operations use Blender's real operators/properties on a disposable scene.

`tests/p25/run_native_preview_workflows.py` makes a new external evidence directory,
copies the pinned CAD extension, creates separate private resource profiles for
create/reopen, and invokes Blender with `--background --factory-startup`. It never
attaches to the existing P2 host, helper, Player or unsaved native documents.
Before launch it clears inherited `BLENDER_USER_*` overrides and supplies private
resource/config/script/data directories plus private `TEMP`/`TMP`/`TMPDIR`. Python
bytecode writes are disabled; the native script also resets any cached temporary
directory before the CAD logger initializes. Processes use BelowNormal priority.

Final source-consistent results on October 24, 2026:

| Native configuration | Create | Fresh-process reopen | Evidence directory under external `evidence/` |
| --- | --- | --- | --- |
| CAD Sketcher 0.32.1 / slvs 3.2, scene unit 1 | 37 passed | 10 passed | `p25-native-preview-private-unit1` |
| Same pinned dependency, scene unit .001 | 37 passed | 10 passed | `p25-native-preview-private-unit001` |
| CAD Sketcher disabled, scene unit 1 | 32 passed | 10 passed | `p25-native-preview-private-withoutcad` |

All six processes exited zero, with 136 native assertions in total. Each directory
contains `manifest.json`, per-process logs and `preview-*-result.json`, private
profiles, the native `.blend` copy and independent saved metadata. Source hashes
and the exact Git baseline are recorded; each native result also records its test
script SHA-256. The manifests verify unchanged add-on/test/CAD source bytes and
unchanged source bytecode files before/after both processes. Actual Blender and
Python temporary paths were checked inside each private profile. Every active CAD
file handler was checked and its private log file confirmed to exist. The CAD-free
variant has no CAD file handler.

The initial workflow runs set private Blender config/script/data directories but
inherited the user's temporary directory. Their retained logs show CAD Sketcher's
default logger opening its shared user-TEMP log in write mode. Those results remain
native workflow passes with an **initial temporary-file isolation limitation**;
they do not establish that P2's shared CAD log was preserved. No shared log was
deleted or restored. The six reruns above supersede those initial runs for isolated
evidence, with private temporary/log paths verified. Five pure runner regressions
now cover inherited override replacement, relative output refusal, OneDrive and
configured sync-root exclusion, and worktree exclusion.

The checks verify:

- Actual preview reservation ownership as the existing host-desktop exclusive
  lease, competing preview denial, competing typed command rejection, normal end
  and nonmodal disconnection release, with exact process/document identity.
- Native Add Cube, Unicode rename with stable object UUID, translation in meters,
  local-axis rotation/scale, native selection, Hide/Show, material Base Color,
  evaluated Bevel modifier geometry and duplicate/delete identity/removal deltas.
- Native Edit Mode telemetry and a completed native Subdivide operation reaching
  the synchronized mesh while Blender remains in Edit Mode: 48 expected triangles.
- Actual built-in Move/Select toolbar state and sidebar/overlay presentation
  changes without a shared geometry revision. These tool changes use real native
  operators, not simulated pointer events.
- Native Undo/Redo, Save As and Save, then a fresh process verifying complete
  object names/transforms/materials/evaluated meshes, stable document/object/CAD
  entity UUIDs, a new open epoch, rejection of the old epoch, and another native
  Unicode rename after reopening.
- One scaled unsupported native CAD sketch being omitted with an explicit reason
  while valid sketches and ordinary native object updates continue, followed by
  successful synchronization after restoring a rigid plane.
- Ordinary native preview admission with CAD Sketcher disabled, while sketch
  capability and dependency state correctly remain unavailable.

Native operation execution from a background script requires explicit native Undo
checkpoints; these tests push those checkpoints after reads/ID assignment. They
verify Blender's actual Undo/Redo implementation and persisted results, rather than
the automatic UI event-loop history boundary.

No native add-on change was necessary during this pass. These results expand
underlying native behavior evidence; the captured UI/button and physical spatial
drawing gates remain open. Real native modal retention/resume is still covered by
the separate mocked lifecycle tests, not by this nonmodal background run.

Example bounded invocation, using a new external directory each time:

```powershell
& '<bundled-python>/python.exe' tests/p25/run_native_preview_workflows.py `
  --blender '<Blender 5.2>/blender.exe' `
  --extension '<verified-copy>/CAD_Sketcher' `
  --output '<new-external-evidence-directory>' `
  --unit-scale .001
```

Use `--without-cad` to verify the ordinary native preview case without registering
CAD Sketcher. The runner still preserves its supplied extension copy for consistent
resource isolation; it is not imported in that variant.
