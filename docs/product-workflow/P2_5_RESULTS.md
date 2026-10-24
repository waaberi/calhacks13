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
image hit and no panel grip.

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

Initial isolated verification on 2026-10-24:

| Check | Result | Limit |
| --- | --- | --- |
| Full runtime C# and Editor C# offline compile | Pass, 19 runtime / 7 Editor sources | Compiler only; source generators/IL/shaders/Player build not run |
| Actual compiled preview mapping/routing gates under Mono | Pass | Synthetic coordinates; no real controller/desktop input |
| Actual compiled native edit session gates under Mono | Pass | Wire-state behavior only; no native geometry execution |
| Dedicated launcher isolation tests | 5 passed and 7 subtests passed | Mocked preflight; no runtime launched |
| Ruff for owned Python wrappers | Pass | Static style/import checks |
| Spatial native matrix gates, cumulative Unity gates and Windows Player build | Pending | Held until the isolated build slot is confirmed |
| Broad native UI workflows and direct VR drawing in headset | Pending | Requires later coordinated P2.5 runtime slot |

The external `p25-offline-compile/compile-manifest.json` records the exact source
hashes and compiled assembly hashes for its run; subsequent source changes require
a fresh run. A previous in-flight compile correctly refused a missing drawing
class while parallel implementation was unfinished. That transient error is not
reported as a completed feature regression.

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
ports, for example host 8769 and capture 8768. It refuses P2's default 8765/8766.
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

The existing `desktop-capture/launch.py` contains the extension ZIP layout used by
the project (manifest and add-on files at archive root, excluding Python caches).
There is no separate tracked Windows release packager in this P2-based branch.
Do not run that default-port launcher to package/test P2.5 during P2's runtime slot.
