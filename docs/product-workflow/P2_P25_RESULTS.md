# Integrated P2/P2.5 software result

Software passed; physical acceptance is pending. No integrated Player, native GUI
input or capture session has replaced the accepted P2 runtime.

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
