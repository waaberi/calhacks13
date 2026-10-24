# P2.5 verification and runtime handoff

P2.5 is developed on `codex/talia-p2-5-blender-interaction`. Its software checks
and later runtime acceptance are separate from P2's ongoing placement work. No
P2 headset test is requested or repeated by this verification workflow. FPS is
not an acceptance criterion. A compiler or simulated input pass cannot establish
that a native Blender button or spatial drawing gesture works in the headset.

## Isolation

- The feature worktree is outside OneDrive. Existing P2 working trees, build
  artifacts, Blender documents, capture selections and the single headset runtime
  remain owned by their original chat.
- `tests/p25/offline_compile.py` runs Unity's bundled Roslyn compiler against a
  read-only compatible imported cache. Its rewritten response files, assemblies,
  logs and source-hash manifest are written to a dedicated external directory.
  It does not launch Unity Editor, a Player, Blender, an input helper or XR.
- `--run-managed-checks` uses bundled Mono to execute the actual compiled preview
  mapping and native-edit state machine. It neither sends real input nor connects
  to the native host.
- Runtime enablement is explicit: `CALHACKS_P25=1` or `--p25`. The Windows helper
  separately requires `--enable-input`. The accepted P2 runtime is not switched
  merely by compiling or publishing this branch.

## Automated gates

`P25Checks.RunMapping` checks independently expected native coordinates at full
image corners, an offset image pivot, and magnified/panned UV corners. It rejects
outside and nonfinite points, zero dimensions and invalid crops. The complete
routing truth table requires current input, the chosen controller, an actual
image hit and no panel grip. Displayed/helper instance and selection-generation
identity must also match before input can target the preview.

`P25Checks.RunTransport` exercises the actual serialized transport's sequence
barrier after an uncertain POST. Both possibilities (server consumed the number
or did not receive it) must recover from the next authoritative GET, and a helper
restart must reset the session. Mutation requests are not automatically replayed.

`tests/p25/ManagedChecks.cs` checks the actual `NativeEditSession`: no native
command while drafting, permission before mutation, matching grants, stale scene
refusal, preserved revision/generation, cancellation before grant, no fictitious
rollback during execution, no blind retry after a missing receipt, late receipt
cleanup, fresh-snapshot recovery and competing-owner refusal. This establishes
client state behavior, not native geometry or universal editing protection.

`P25Checks.RunSpatial` checks native XY metres, a separately calculated world hit
under translated/rotated/nonuniform display magnification, a rotated native plane,
and invalid/parallel/behind/singular inputs. It must run inside Unity because the
actual Unity matrix/quaternion implementations can require native initialization.

`P25Build.Windows` requires `CALHACKS_P25_BUILD_PATH` to be an absolute `.exe` path
outside Git worktrees and OneDrive. It invokes the P2.5 gates and existing cumulative
P2/arrangement/P1 gates, preserving the accepted aim, controller, startup, image
freshness and visual baseline checks. It never launches the resulting Player.

Example offline compiler invocation, substituting local absolute paths:

```powershell
& '<bundled-python>/python.exe' tests/p25/offline_compile.py `
  --cache-app '<existing-compatible-P2-worktree>/app' `
  --unity-data '<Unity-editor>/Editor/Data' `
  --output '<external-evidence>/p25-offline-compile' `
  --run-managed-checks
```

The existing cache must use the same Unity version, package versions and assembly
configuration. The offline compiler does not run Unity imports, source generators,
IL postprocessing, shader builds or scene serialization; those remain separate
integration checks. Never treat offline assembly output as a distributable Player.

## Evidence and remaining acceptance

Implementation and verification results are recorded as they complete. No native
interaction, headset interaction or broad Blender button coverage is claimed from
the compiler or managed checks alone.

Final isolated verification on 2026-10-24:

| Check | Result | Limit |
| --- | --- | --- |
| Full runtime C# and Editor C# offline compile | Pass, 21 runtime / 7 Editor sources | Actual compiled mapping/transport/session gates also ran under Mono |
| Actual compiled preview mapping/routing gates under Mono | Pass | Synthetic coordinates; no real controller/desktop input |
| Actual compiled HTTP sequence barrier under Mono | Pass | Pure state gate; actual HTTP failure paths remain separate |
| Actual compiled native edit session gates under Mono | Pass | Wire-state behavior only; no native geometry execution |
| Dedicated launcher isolation tests | 5 passed and 7 subtests passed | Mocked preflight; no runtime launched |
| Ruff for owned Python wrappers | Pass | Static style/import checks |
| Isolated native CAD create/reopen at scene unit scales 1 and .001 | Pass, four fresh Blender processes | Native solver/persistence checks; no desktop/headset input |
| Spatial native matrix gates | Pass inside Unity | Known world/native oracles; no physical gesture |
| Cumulative P2/arrangement/P1 interaction and visual gates | Pass inside Unity | Synthetic/editor checks preserve existing requirements; no new physical acceptance |
| Windows Player build | Pass, exit 0 and zero errors | Frozen app source `900b7a7`; resulting Player never launched |
| Broad native UI workflows and direct VR drawing in headset | Pending | Requires later coordinated P2.5 runtime slot |

The external `p25-offline-release/compile-manifest.json` records the exact source
hashes and compiled assembly hashes for its run; subsequent source changes require
a fresh run. A previous in-flight compile correctly refused a missing drawing
class while parallel implementation was unfinished. That transient error is not
reported as a completed feature regression.

The isolated native run is recorded under external evidence
`p25-native-20261024T173230Z/manifest.json`. All four create/reopen processes exited
zero and their `*-result.json` files report `passed: true`. It used Blender 5.2.2
LTS, CAD Sketcher 0.32.1 and slvs 3.2 in private profiles at both native unit scales.
Create exercised 28 native mutations per scale; reopen performed a further native
edit in each fresh process. Native Undo/Redo passed, complete native entity and
constraint identities survived reopening, conflict rollback and unsupported sketch
isolation passed, and `Window.modal_operators` was inspectable. These were
background isolated native documents, not input sent to the user's Blender or a
proof of a working VR gesture. The captured native button/menu workflows remain
pending runtime acceptance.

Final Windows output is the external directory
`artifacts/p25-preview-spatial-v2/`. The build used this feature worktree's own
Library, Unity 6000.6.5f1 in batch/nographics mode with two job workers, and a
BelowNormal Editor process. `P25Build.Windows` passed its mapping, transport and
spatial gates, then the cumulative P2 placement/menu/scene, arrangement, accepted
aim/controller/startup/freshness and render-scale/MSAA/alpha checks. Unity reported
`Succeeded errors=0` and exited with code 0. No Player, capture helper or interactive
Blender was launched by this build. P2's active test runtime was not replaced.

| Final v2 identity | Value |
| --- | --- |
| Frozen app source | `900b7a7` |
| Git app tree | `b2f2ec89f619babc77f1facd0d3fd9b7d9aade37` |
| `SpatialModeling_Data/Managed/Assembly-CSharp.dll` SHA-256 | `1a838542e58e1760f681b10ab4e010dcbc5d4e091e83e832cae25482816e5f18` |
| `SpatialModeling.exe` SHA-256 | `001aeebfb92718f8b49f0c0e0a03e313c54669552b08e952b2fee3ddd143683a` |
| Build evidence | `evidence/p25-preview-spatial-v2-build.log` and `p25-preview-spatial-v2-build-result.json` |

The first v1 build began before the component-disable cleanup repair was frozen
and picked up that repair during Player compilation. It is retained as a
mixed-timing diagnostic and is not attributed exclusively to its starting commit.
The v2 rebuild used frozen `900b7a7`; its C# source was verified unchanged afterward.
The equal v1/v2 DLL hashes reflect the first build having already incorporated the
repair. Generated settings diffs were preserved to external evidence for each run,
verified to contain only line-ending/trailing-whitespace changes, then restored.
No generated render/XR/project settings were included in this feature change.

Before accepting a later isolated runtime, record exact source and assembly hashes
and verify a deliberately changing native viewport alongside actual operations:
workspace tabs/panels, menus/submenus, fields, selection, scrolling, drags, keyboard
and modifiers, Undo/Redo, cancellation, and owned pop-up windows. Validate that
each action changes Blender as expected. Exercise native and VR coordinate values
for line/circle/rectangle drawing, solver results and Undo/Redo; preserve a native
save/reopen copy. Distinguish accessible native UI actions from unsupported spatial
tools and unsupported synchronization output. Window focus, source identity,
stale frames, tracking loss and held-button cleanup need actual failure-path checks.

The runtime handoff must be explicitly coordinated with P2's original chat. Do not
replace its Player/helper, steal desktop focus or reuse unsaved user documents to
obtain these checks. Main is not updated by this feature's validation or publication.

## Dedicated launch preflight

`desktop-capture/launch_p25.py` requires explicitly selected, distinct nondefault
ports, for example host 8769 and capture 8768. It refuses P2's default 8765/8766/8767.
It sends only `hello` and `preview.state.query` to the existing host and reads
`GET /input/state` from the existing helper. It verifies the welcomed document,
host epoch, advertised P2.5 bridge, fresh capture and selected native process ID.
It does not focus Blender during preflight and never prints the input token.

```powershell
# Read-only diagnosis; existing isolated host/helper must already be configured.
& '<bundled-python>/python.exe' desktop-capture/launch_p25.py `
  --host-port 8769 --capture-port 8768 --diagnose

# Only after the original P2 chat releases the single Player slot.
& '<bundled-python>/python.exe' desktop-capture/launch_p25.py `
  --host-port 8769 --capture-port 8768 `
  --player '<external-P25-build>/SpatialModeling.exe' `
  --session-dir '<new-external-P25-session>'
```

Launch sets `CALHACKS_P25=1`, `CALHACKS_HOST_PORT` and `CALHACKS_CAPTURE_PORT` for
the new Player only. It refuses any existing `SpatialModeling.exe` (including a
windowless Player) and checks again immediately before spawn. The operator must
start this branch's host/add-on and helper in a separately configured session; no
automatic installation, helper restart or attachment to P2's default session is
attempted. Native CAD availability is reported separately: native preview access
can work without CAD Sketcher; direct drawing requires the pinned native dependency.

The dedicated `desktop-capture/bootstrap_p25.py` prepares private add-on/CAD/solver
copies, verifies their source hashes and opens a copied native document only in a
new factory-startup Blender with a new external resource profile. It binds the
explicit isolated host port and never installs into a personal profile. Its module
documentation contains the launch arguments; its pure preparation tests do not
start Blender. The Windows Player must be distributed with its entire runtime
directory, excluding Unity's `BackUpThisFolder_ButDontShipItWithYourGame` directory;
the EXE alone is insufficient. Do not use the old default-port launcher for P2.5.
