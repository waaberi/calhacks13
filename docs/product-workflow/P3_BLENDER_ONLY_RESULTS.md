# Independent P3 software results

2026-10-24 human-authorized work on `codex/talia-p3-blender-only`. Full requirement/source matrix, unsupported routes, architecture decision and selective integration steps are in [P3_BLENDER_ONLY_HANDOFF.md](P3_BLENDER_ONLY_HANDOFF.md). No new PR, main update or runtime takeover.

The candidate starts at complete P2/P2.5 `9b93b3a`, selectively reuses merged Client/ownership PR149/160/161 and lease replay protection, and incorporates the later bounded native-input repairs `929b78f`/`252f5ff`. The compact native-only input surface and native-context drawing remain intact. No cumulative old P3 branch or unrelated main/voice/store work was merged.

| Check | Verified result | Limit |
|---|---|---|
| Backend/P2.5 Python 3.13 | 951 passed, 36 explicitly skipped | Skips include unavailable ordinary-Python bpy/GUI fixtures and optional SpacetimeDB/CLI dependencies. Separate private native runners cover native work; no SpacetimeDB acceptance. |
| Capture/input/bootstrap/launcher | 150 unittest cases passed after the bounded input repairs | Mocked capture/input paths; no OS input or active capture selection change. |
| Native P2.5 reuse | Seven successful runner groups: navigation plus preview/modeling/object actions at unit scales 1 and .001, including native 10 mm/90-degree readbacks, operations, history/save and cold reopen | Background native evidence; no GUI event or controller delivery. |
| Additional native CAD/UI | Four successful create/reopen phases at scales 1 and .001 | Real CAD Sketcher 0.32.1/slvs 3.2, solver states, anchored 100x60 -> 120x60 mm, diameter/angle/distance, exact conflicts, Undo/Redo and further 130x60 mm edit. Actual native tools/UUIDs and framing invariance; GPU contrast render remains pending. |
| Private authority prototype | 20 assertions, two actual background Blenders, clean exits, source/dependency/bytecode invariance | Only mapped native operator and typed command routes; strict production prevention/full native UI coverage remain failed/unmet. |
| Windows build | `P25Build.Windows`, zero errors; cumulative accepted P1/P2, native-only menu/direct line-circle-rectangle/context/late-grant checks, 34 frozen Standalone XR flags checked before/after | Build never launched a Player. Physical P3 acceptance absent. |
| Actual Unity loopback HTTP | 7 window/busy/focus cases + 2 release-barrier cases + 9 input transport cases | Real coroutines/UnityWebRequest against private loopback fixtures; no OS input/native GUI/Player. |
| Package | Complete matching Player/native/helper/CAD/solver/dependencies/reference and exact P2 rollback; hash-validated without launch; packaged native background bootstrap exits cleanly with CAD available and package unchanged | No interactive/physical launch performed. Final artifact/source/hash manifest is recorded separately. |
| Hygiene | Repository Ruff passes; generated SDK settings archived, inspected and restored; working source excludes generated resources | No user preferences, personal Blender files or active room/model data changed. |

## Preserved failures

- Initial Windows v1 failed because newly added pointer preference loading used `PlayerPrefs.GetInt` in a MonoBehaviour field initializer. Moved preference loading to `OnEnable`; subsequent actual component/build gates pass. The first failed binary was not launched.
- Windows v2 passed the new native-only menu check, then its inherited window fixture looked for retired dedicated clipboard/model controls (`Sequence contains no matching element`). The fixture now exercises the generic keyboard and direct-drawing release handoff; production editing palettes were not restored. Later build/HTTP gates pass.
- The first additional CAD/UI fixture passed solver/history/framing, then could not select a CAD toolbar tool in background mode. The pinned dependency deliberately skips toolbar registration there. The corrected private fixture invokes the actual sketch-tool registration path; all four create/reopen phases pass. This is not proof of GUI delivery.
- One helper-suite invocation used the bundled authoring Python with `-m pytest`, which is not installed in that runtime. The actual supported helper runner is stdlib unittest with existing capture dependencies; it passes all 150 cases. No dependencies were installed or security settings changed.
- Initial packaged-bootstrap verification pre-created the required-new session directory when constructing its private profile, so bootstrap correctly refused it. The corrected verifier supplies a new private resource path without pre-creating the session; actual packaged startup/CAD and no-mutation checks pass.
- SDK-generated settings and their whitespace diagnostics were retained separately before restoration. No generated XR/settings delta is silently published.

No failed run is counted as an aggregate pass. The seven successful existing native groups are reused from the initial native run; its aggregate remains failed because of the toolbar fixture failure. The four corrected CAD/UI phases have their own successful manifest. Native/code hashes and individual manifests preserve that distinction.

## Remaining gates

- Review and any later source reconciliation with the P2/P2.5 owner; its v7 narrow activation pass is not P3 acceptance.
- Actual native GUI create/select/transform/delete, numeric/readback, keyboard/drag/scroll, popup/dialog, modal Cancel, focus/disconnect/held-input recovery with the same disposable document.
- Native CAD UI edits and direct headset drawing coupled to live changing capture; actual framing/contrast/readability and comfortable use with both pointer hands.
- Real two-PC/concurrent-owner scenarios and the separately assigned #165/#87 SpacetimeDB lease check.
- A human-authorized architecture/scope decision for strict full-native-UI authority. The prototype mirror uses display `CURVE` geometry without native `sketch_constraints`; unrestricted native edits do not automatically become validated commands. Production #87/RC16 stays FAIL.

No full phase acceptance or passing phase tag is claimed. The active runtime belongs to its existing owner; this candidate is prepared for later coordinated integration/testing only.
