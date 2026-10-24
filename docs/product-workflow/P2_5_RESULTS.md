# P2.5 verification and runtime handoff

P2.5 is developed on `codex/talia-p2-5-blender-interaction`. Its software checks
and later runtime acceptance are separate from P2's ongoing placement work. No
P2 headset test is requested or repeated by this verification workflow. FPS is
not an acceptance criterion. A compiler or simulated input pass cannot establish
that a native Blender button or spatial drawing gesture works in the headset.

## Headless control regression pass

The user explicitly requested headless testing. This pass launches no interactive
Blender, capture helper, desktop input injection, Player or headset session. Its
source checkpoint is `07db58c56ddedae8546a7ed7d37fd3a2e4d8e4df`.

The helper's real HTTP tests reproduced non-ASCII-token and huge-number crashes,
false focus acknowledgement after failed held-input release, and phantom releases
when context validation refused an event before dispatch. The fixes reject bad
requests with bounded errors, block focus until release succeeds, and track new
holds only immediately before dispatch. Successful watchdog release invalidates
the stale gesture session; failed cleanup and idle heartbeats preserve it.

The Unity client now validates the helper fields it consumes and always clears
its state-reader barrier. Dispatch and independent cleanup require explicit
`ok:true` with the exact event sequence. An HTTP 200 alone cannot end the native
reservation. Invalid acknowledgements cancel pending actions; model mutations are
not replayed. Only idempotent release can retry after a fresh authoritative GET.
The actual capture-only helper's compact disabled response is accepted without
credentials, so setup guidance still explains `--enable-input`. Even previously
synchronized input is revoked and cannot POST after this response.

| Headless check | Result | Evidence and limit |
| --- | --- | --- |
| Capture/input/launcher/bootstrap HTTP and isolation suite | 77 passed | `p25-headless-helper-20261024T183842Z/final-tests.log`; fake Windows adapter, no HWND/SendInput |
| Actual UnityWebRequest and production reader/sender/cleanup coroutines | 9 cases passed | `p25-headless-http9-result.json` and Editor log; fake ephemeral loopback responses, no native admission |
| Complete fresh-Editor sequence | Passed, exit 0 | `p25-headless-protocol-cumulative.log`; original P1/P2/arrangement gates plus protocol, target, occlusion and keyboard-last checks |
| Native background preview workflows | 136 assertions passed in six processes | Unit scales 1/.001 and CAD-free; private resources/TEMP/logs and unchanged source/bytecode verified |
| Native test runner isolation guards | 5 passed | Private inherited-environment replacement and external output refusal checks |
| Full Python suite and repository-wide Ruff | 873 passed, 36 skipped; Ruff passed | `p25-headless-final-pytest.log` / `p25-headless-final-ruff.log`; explicit skips are not native acceptance |
| Final Windows v9 build | Passed, zero errors/exit 0 | `p25-preview-spatial-v9-build-result.json` / build log; frozen source `07db58c`, complete mandatory gates, no Player launch |

The current complete runtime directory is external
`artifacts/p25-preview-spatial-v9/`. It was built headlessly in this worktree's own
Library, with BelowNormal priority and one worker. All HTTP9 source hashes match
the frozen build source. Generated settings were preserved to external evidence,
verified as whitespace-only changes, and restored to the accepted baseline.

| Final v9 identity | Value |
| --- | --- |
| Frozen app source | `07db58c56ddedae8546a7ed7d37fd3a2e4d8e4df` |
| Git app tree | `8efb72293a2c3a413849b474f313c969c4a66a41` |
| Managed assembly SHA-256 | `e35fbeb2da7cb6d1d300b0221fbd2a750838793ac615d9b13979403d736a8a44` |
| Executable SHA-256 | `001aeebfb92718f8b49f0c0e0a03e313c54669552b08e952b2fee3ddd143683a` |

The HTTP cases cover compact disabled state without input authority, recovery
after wrong-typed valid JSON, rejection of empty
200 responses, exact sender acknowledgements, cleanup callback refusal for
empty/wrong-sequence/false acknowledgements, successful release, and recovery by
GET before retrying release. `P25Checks.RunInputProtocol` runs inside the cumulative
Editor/build gates. It covers disabled/no-window state and
integer overflow without injecting OS input.

Run the asynchronous HTTP fixture with a new absolute external
`CALHACKS_P25_HTTP_RESULTS` path:

```powershell
& '<Unity-editor>/Editor/Unity.exe' -batchmode -nographics `
  -projectPath '<isolated-P25-worktree>/app' `
  -executeMethod P25HttpChecks.Run -job-worker-count 1 `
  -logFile '<new-external-evidence>/http-editor.log'
```

Do not supply `-quit`: the bounded Editor scheduler exits after the actual
asynchronous HTTP operations finish. The fixture does not enable XR or launch a
Player. See [native workflow evidence and isolation limits](P2_5_NATIVE_PREVIEW_WORKFLOWS.md)
for the operation coverage and the initial shared-TEMP logger mistake, which is
preserved separately from the corrected private reruns. Reproductions and fixes
are recorded in [issue 139](https://github.com/waaberi/calhacks13/issues/139#issuecomment-6388121302).

Actual hover, menu/button delivery, sliders/drags, OS focus, auxiliary windows,
changing captured pixels and controller/headset drawing remain pending. Successful
native operations establish the underlying behavior; their UI event sequences
still require the later coordinated runtime slot. No evolving P2 surface changes
were imported during this control test pass, and no P2 physical test was requested.

The earlier passing v8 checkpoint is preserved at source `e81d36b`, app tree
`383e7e006b97ba443366f808ff3cd6282af865e2`, DLL SHA-256
`6378781fec53e72ac725e222d08a052cee72f57923d3fa5f080257d8ccb7302b`.
It passed the complete build sequence with zero errors/exit 0. The later
capture-only setup correction has its own source and HTTP9 evidence above.

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

`P25Checks.RunTargets` checks that an applied new-sketch receipt selects its actual
native UUID even when native telemetry still names an older sketch. A missing new
scene record waits for that UUID, and removal refuses to redirect drawing to the
old sketch. Rejected/unrelated receipts and genuine native context switches are
covered by the actual managed implementation.

`P25Checks.RunKeyboardIsolation` sends synthetic Input System events only inside
the isolated Editor. It invokes actual `TablePlacement.Update` and verifies that
native-owned M/Enter/Escape do not also move/place/cancel the table; ordinary
desktop behavior remains. The actual composite pan action rejects owned keyboard
arrows while preserving independent controller axes. Pending input cleanup still
blocks desktop shortcuts. No OS keyboard event is injected. This mandatory gate
runs last, after the existing controller gates, to isolate its synthetic player
input state from their Editor-buffer tests.

`P25Build.Windows` requires `CALHACKS_P25_BUILD_PATH` to be an absolute `.exe` path
outside Git worktrees and OneDrive. It invokes the P2.5 gates and existing cumulative
P2/arrangement/P1 gates, preserving the accepted aim, controller, startup, image
freshness and visual baseline checks. It never launches the resulting Player.
The final keyboard-isolation gate must also pass before the wrapper logs
`P25_BUILD_RESULT Succeeded`; an existing output directory alone is insufficient.

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

Earlier v7 isolated verification on 2026-10-24:

| Check | Result | Limit |
| --- | --- | --- |
| Full runtime C# and Editor C# offline compile | Pass, 22 runtime / 7 Editor sources | Actual compiled mapping/transport/target/session gates ran under Mono; final Editor fixture also compiled in Unity |
| Actual compiled preview mapping/routing gates under Mono | Pass | Synthetic coordinates; no real controller/desktop input |
| Actual compiled HTTP sequence barrier under Mono | Pass | Pure state gate; actual HTTP failure paths remain separate |
| Confirmed new-sketch target selection | Pass under Mono and Unity | New UUID, delayed record and removed-target regression coverage |
| Actual compiled native edit session gates under Mono | Pass | Wire-state behavior only; no native geometry execution |
| Dedicated launcher isolation tests | 5 passed and 7 subtests passed | Mocked preflight; no runtime launched |
| Ruff for owned Python wrappers | Pass | Static style/import checks |
| Isolated native CAD create/reopen at scene unit scales 1 and .001 | Pass, four fresh Blender processes | Native solver/persistence checks; no desktop/headset input |
| Backend/contract combined suite | 868 passed, 36 skipped | Skips remain distinct from actual isolated native runs |
| Capture/input/launcher/bootstrap combined suite | 69 passed | Source/transport/isolation tests; no headset acceptance |
| Spatial native matrix gates | Pass inside Unity | Known world/native oracles; no physical gesture |
| Cumulative P2/arrangement/P1 interaction and visual gates | Pass inside Unity | Synthetic/editor checks preserve existing requirements; no new physical acceptance |
| Actual keyboard ownership and controller-axis isolation | Pass inside Unity | Real Input System synthetic edges and actual table update; no OS input injected |
| Integrated P2 visible-level and preview occlusion gates | Pass inside Unity | Actual RawImage/RouteHand respects nearer levels, primary hand and grip routing |
| Windows Player build | Pass, exit 0 and zero errors | Frozen app source `ccb2c56`, published P2 `e880714` integrated; resulting Player never launched |
| Broad native UI workflows and direct VR drawing in headset | Pending | Requires later coordinated P2.5 runtime slot |

The external `p25-offline-p2-integration/compile-manifest.json` records the exact runtime source
hashes and compiled assembly hashes for its run; subsequent source changes require
a fresh run. Later Editor-fixture repairs were compiled and executed by Unity's
narrow and complete build gates. A previous in-flight compile correctly refused a missing drawing
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

The verified Windows checkpoint is the external directory
`artifacts/p25-preview-spatial-v7/`. The build used this feature worktree's own
Library, Unity 6000.6.5f1 in batch/nographics mode with two job workers, and a
BelowNormal Editor process. `P25Build.Windows` passed its mapping, transport and
spatial gates, then the cumulative P2 placement/menu/scene, arrangement, accepted
aim/controller/startup/freshness and render-scale/MSAA/alpha checks, followed by
mandatory keyboard isolation. Unity reported
`Succeeded errors=0` and exited with code 0. No Player, capture helper or interactive
Blender was launched by this build. P2's active test runtime was not replaced.

| Verified v7 identity | Value |
| --- | --- |
| Frozen app source | `ccb2c56f5090cf391024e71c8f0037025ed2c0b0` |
| Git app tree | `444e52685e56bfdeede1f00df159cbfe6c89bebb` |
| `SpatialModeling_Data/Managed/Assembly-CSharp.dll` SHA-256 | `c5e28b0358dbb0d55c359828fa48be2cf334c422423719245b28bba08baf9828` |
| `SpatialModeling.exe` SHA-256 | `001aeebfb92718f8b49f0c0e0a03e313c54669552b08e952b2fee3ddd143683a` |
| Build evidence | `evidence/p25-preview-spatial-v7-build.log` and `p25-preview-spatial-v7-build-result.json` |

V7 selectively integrates the six published P2 surface/visible-level files from
`e880714` through feature-branch merge `8937c95`. Accepted grip and P2.5 hooks are
retained: closer level geometry bounds the preview route, and a closer preview
control wins its ray hit. RawImage layout and capture behavior were not changed.
Offline/managed checks and the complete fresh-Editor P2/arrangement/P1/P2.5 sequence
passed before the v7 build, including real `RouteHand` calls against an active
RawImage with nearer/farther occlusion limits. Evidence is
`p25-p2-integration-editor.log`. The P2 owner still reports an open OpenXR runtime
lifecycle failure, `XR_ERROR_LIMIT_REACHED`; this never-launched P2.5 candidate
does not establish a fix or new headset acceptance. P2's runtime owner retains
the testing slot even while its Player is closed.

The pre-integration v6 checkpoint remains preserved at frozen `e4d3108`, DLL
SHA-256 `1c9ba81a69fe8a1e74d18451f5787433f13e4dc6ef75726317823f87d5717736`,
with its original build log/result manifest. V9 above is the current headless-verified candidate.

The first v1 build began before the component-disable cleanup repair was frozen
and picked up that repair during Player compilation. It is retained as a
mixed-timing diagnostic and is not attributed exclusively to its starting commit.
The historical v2 rebuild used frozen `900b7a7`; its C# source was verified unchanged afterward.
The equal v1/v2 DLL hashes reflect the first build having already incorporated the
repair. Their historical DLL hash is `1a838542e58e1760f681b10ab4e010dcbc5d4e091e83e832cae25482816e5f18`.
They precede the explicit new-sketch target and expanded keyboard regressions and
are superseded by v7. Generated settings diffs were preserved to external evidence for each run,
verified to contain only line-ending/trailing-whitespace changes, then restored.
No generated render/XR/project settings were included in this feature change.

Rejected intermediate build attempts remain preserved:

| Attempt | Exact failing gate | Diagnosis and correction |
| --- | --- | --- |
| v3, `af087f1` | `synthetic keyboard actually delivers a fresh key event` | Edit-mode input buffers did not supply the required player edge counter. The fixture now enables/restores the installed Input System's nonpersisted player-update test flag; the fresh-edge assertion remains. |
| v4, `969c958` | `P2: table controls plus pin/dock menu actions constructed` | The inactive fixture left its separately created menu behind because Unity did not call its OnDestroy. The fixture now explicitly invokes its real cleanup and asserts no extra TableActions remain. |
| v5, `e992ed1` | `Typed pose reader must accept Current` | Synthetic player updates initialized global Input System state before the original Editor-buffer pose tests. The mandatory keyboard fixture now runs last; all original P1/P2 assertions are unchanged. |

These are verification-harness failures, not observed headset or native geometry
failures. Their logs are retained as `p25-preview-spatial-v3/v4/v5-build.log` under
external evidence. They are tracked in [P2.5 issue 139](https://github.com/waaberi/calhacks13/issues/139),
including the [original fresh-edge failure](https://github.com/waaberi/calhacks13/issues/139#issuecomment-6387560729).
The complete narrow sequence `P25Checks.RunCumulativeEditor` passed with unchanged
P2, arrangement and Current/Legacy controller gates before the full v6 build; its
evidence is `p25-complete-editor-isolation.log`. V6 then passed the complete build
and its final mandatory keyboard gate with exit code 0. No intermediate failure
was promoted to a candidate or replaced P2's runtime.

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
