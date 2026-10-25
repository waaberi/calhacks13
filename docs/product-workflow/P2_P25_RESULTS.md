# Integrated P2/P2.5 software result

## Controller mapping, button feedback and explicit screen lock candidate

The wearer reports that controls other than Enable input appear ineffective and
give no visible press/state feedback. The direct controller path invoked onClick
without Unity pointer-state events, so ordinary Button transitions did not show
the trigger press. The repair explicitly flashes registered presses, retains
green/ON states for toggles/modifiers/tools, and displays last-press plus blocker
feedback above the controls. It does not label a requested native edit as applied.

Human-specified mapping: front trigger left-click; side grip right-click while
the screen is explicitly locked; stick tilt wheel/zoom; hold stick pressed and
tilt for pan. Temporary Shift/middle pan input is balanced on release, UI handoff,
tracking loss and transport cleanup. Locked native routing consumes the side grip
before screen grabbing; unlocked default retains accepted P2 movement. Lock is
available in preview controls and workspace Settings. All old mouse modes remain
under optional Mouse options; keyboard, shortcuts, modeling/numeric and direct
drawing functionality remain. Input freshness, authority and release-ACK gates
are unchanged.

Actual controller-ray/UI tests cover keyboard toggle/press acknowledgement,
held-trigger edges, lock pose preservation, front/side mouse down-up, pan cleanup,
scroll and tracking interruption. The cumulative Windows build and final P2 gates
pass with zero errors/all37 required markers, exact34 accepted XR flags and actual
Unity HTTP7+2+9.61 compiler inputs/154metas match; generated SDK settings were
archived/inspected/restored. Native/helper sources are byte-unchanged from the
151-helper-tested clarity revision. Physical results are pending. The separate human-authorized teammate
headset test owns the runtime: verified clarity Player65848 was closed gracefully;
all Blender/helper processes and unsaved work were preserved. This candidate is
prepared without launch or OS input during that test. No PR or main changes.

## Human-requested VR readability candidate

The wearer requested clearer streamed Blender text. The clarity candidate uses
150% Blender interface scale inside the disposable profile, maximum-quality JPEG
100 with unchanged4:4:4/full native capture, and a bounded-0.65 mip sampling bias
on the P2.5 preview. Trilinear/aniso4/mipmaps remain; non-P2.5 filtering, eye/render
scale, MSAA4, alpha, panel placement, source geometry/history and input mapping
remain unchanged. No frame-rate target or optimization was introduced.

Software PASS:151 helper tests/Ruff, actual Unity HTTP7+2+9,36 mandatory cumulative
build markers including source-resolution/pixel/mip preservation and unchanged P2
filtering. A small-text encoding regression verifies reduced reconstruction error,
4:4:4 and native dimensions; actual packaged native/CAD bootstrap exited0 with
private UI scale1.5.61 compiler inputs/154metas match; generated SDK settings were
archived/inspected/restored. An initial helper run lacked Pillow in its environment;
the complete packaged dependency environment passed. No assertions were weakened.

The running private Blender has unsaved user edits: keep it open, change only its
display preference, and retain the same document/process. Desktop inspection shows
larger source text; headset sharpness, shimmer and readability remain PENDING human
confirmation. This is not physical acceptance or a promise of monitor-level detail.

## Physical activation failure and repair candidate

The wearer briefly opened File with the green indicator on v6/929b78f, then
reported that input immediately turns itself off repeatedly. Cursor movement
was visible. The single successful click is retained as an observation;
sustained native-preview input remains FAILED, not accepted.

The live log captured HTTP429 after focus success. The helper uses this for
`input_busy`, a pre-admission lock collision with its safety/state work. It
consumes neither the sequence nor the action. The next repair discards the
old gesture and queue, obtains authoritative state/sequence, confirms exact
release acknowledgement, then admits a new gesture in the same verified window.
Rejected input is never replayed. Other failures retain their existing cleanup
gates; bounded rejection-code logs identify any separate cause.
The fresh v7 software run passed actual Unity HTTP7+2+9 (including this exact
unconsumed-sequence/no-replay case), all35 cumulative build markers and frozen
34 XR flags, with61 compiler inputs/154metas matched. Its physical result is
pending; v6's instability is not relabelled a pass.

The human approved starting physical testing. The wearer could not click
Blender's captured interface on v4/a779f98. Clearing the disposable Blender's
first-run setup/splash did not resolve that reported failure. Physical acceptance
remains failed/pending investigation; the accepted P2 rollback is preserved.

The repair adds a persistent input toggle showing Off, Enabling, On, Blocked or
Releasing, with text and colour. On requires the existing complete native
ownership, foreground, fresh displayed frame and geometry admission. Toggling off
retains release acknowledgement ordering. Transition diagnostics identify each
admission predicate without logging input tokens or document/room data.

A reproduced HTTP focus-denial path previously treated Windows refusing focus as
a dialog handoff, then hid the error behind the generic waiting message. It now
retains an actionable error, discards pending actions and waits for exact cleanup
acknowledgement before ending native ownership. This reproduced defect is not yet
established as the wearer's remaining root cause. Private-profile startup also
disables the splash without writing personal preferences; a fresh actual GUI
bootstrap exited successfully with no saved preference file.

Repair software checks: 150 helper tests and Ruff passed; actual Unity HTTP
6+2+9 cases passed, including focus denial/no replay/ordered release. The fresh
Windows build passed all 35 cumulative markers with zero errors and the exact
34 accepted P2 Standalone XR flags before/after build. All 61 source/scene/shader
inputs and 154 metas matched the frozen prebuild hashes. Generated Editor feature
sets, WebGL records and Android install-location changes were archived, inspected
and restored; no generated configuration was committed. These checks do not
establish that the wearer's activation failure is resolved.

## Original v4 software delivery (historical)

Software passed; physical acceptance was pending at delivery. The following
results describe the original frozen v4 package before its physical trial.

Frozen application/build source: `a779f98ee882e22d52a4b7cd3cd961a88522b8f6`.
Integration merge: `c9997217792849e907ddbc7309683e56340d3c95`, with parents final
P2 `d3230cdbc8a93188d4c4f0e0bff4e1a6ac497cc4` and complete P2.5
`3ab38b2fb95b0b9cf84b93ba36953bb90c878149`. Follow-up `423583c` preserves the
reviewed P1 capture-thread recovery; `77a8cac` and `a779f98` freeze accepted P2 XR
flags against generated SDK settings. Later documentation commits do not change
the compiled application.

Complete candidate folder: `p2-p25-integrated-v4`. Keep every file together.
Managed assembly SHA256:
`80a213777e6411b6d9c70cbac6701acd8ac596548ed0242f616067e809780ce2`.
Windows EXE SHA256:
`001aeebfb92718f8b49f0c0e0a03e313c54669552b08e952b2fee3ddd143683a`.
The EXE is Unity's common launcher; the managed assembly and full package
manifest identify the application. The complete known-good final P2 rollback is
bundled separately, with its unchanged assembly hash recorded in the guide.

| Gate | Result |
| --- | --- |
| Full Python suite | 904 passed, 36 skipped; same scoped P2.5 reference |
| Helper/input/window/bootstrap/launcher suite | 148 passed: original 142, five launcher-safety tests, one reviewed capture-recovery regression |
| Ruff | Passed |
| Real Unity UI and cumulative Windows build | Passed, exit 0, zero build errors, all 28 original markers plus seven final P2/integration markers |
| Final P2 regression coverage | Scale, Settings/gear render, independent planes/delete/Align/vertical-front creation, paired controllers/both pose formats, startup placement, anchoring, aim displacement, room/current-room, capture freshness, render/alpha and keyboard isolation passed |
| Independent native room conversion | 33 native cases, 66 world cases, 240 boundary points; omission/inverse/double controls each rejected 66/66 |
| Frozen accepted XR feature inventory | Exact 34 Standalone feature flags verified before and after build |
| Actual Unity HTTP suites | Five dialog/window cases, two release-order cases, nine transport cases passed |
| Background native preview, modeling and object/history | Create/reopen at unit scales 1 and .001; all seven runners passed with private resources and unchanged source/bytecode |
| Native panels/navigation | 60 required assertions, 31 installed shortcut matches, eight panel transitions, no pending/optional failures |
| Assembled native/CAD startup | Actual packaged add-on, pinned CAD solver and copied document started privately on the isolated port and exited 0; reference unchanged |
| Frozen compiler inputs | 61 source/scene/shader files matched; tracked settings restored after archiving generated output |
| Accepted session | Existing final P2 Player/native/helper/personal Blender preserved |

Failed observations remain retained locally:

- First build used a different room capture and failed the wall-normal assertion.
  The exact final-P2 paired fixtures then passed with unchanged assertions.
- A rebuild reused an output folder and Unity reported an existing
  `RuntimeActionBindings.json`. The artifact was rejected; fresh output directories
  built with zero errors. Earlier folders and logs were preserved.
- Initial new launcher tests had Ruff context-manager/style errors; corrected
  tests pass. No failing run is relabelled passed.
- Initial imports generated feature-set/proximity/foveation/WebGL/Android setting
  changes. These were archived and restored. The final build requires and checks
  the accepted 34-feature inventory; final generated changes were whitespace only.
- A local marker-audit string initially used the wrong singular/plural marker;
  the production test had passed. The audit now checks the exact production marker.

Real OS input/capture, nested native dialogs, physical controller gestures,
interruption cleanup, live changing viewport, native drawing/Undo/Redo and focused
P2 preservation remain pending the coordinated human-approved runtime handoff.
Headless native operation checks do not establish those outcomes. No FPS target,
main update or PR action was performed.

Use the [integration and focused physical-test guide](P2_P25_INTEGRATION.md).
The package contains `Validate-Package.ps1`, `Start-Integrated-Test.ps1`,
`Restore-P2.ps1`, the matching add-on/helper/dependencies, a disposable reference,
private-session configuration, complete rollback, and full file hash manifest.
The configured installed prerequisites are Windows Blender 5.2.2 and the existing
bundled Python runtime; no manual branch/dependency assembly is required.
