# Phase 0: Talia's walkthrough

P0 proves the team's tools can start together. It does not yet promise VR modeling. The complete source plan is saved locally at `planning/PHASE_PLAN.md`; your current checklist is `planning/checklists/TALIA.md` and the next-action log is `planning/TALIA_WORKSPACE.md`.

| Who | Work for P0 |
| --- | --- |
| Codex with Talia | Set up the local branch, create the known-size Blender fixture, verify fresh reopen, prepare demo expectations, collect local tool/hardware facts and keep task evidence. |
| Talia | Approve useful reference dimensions, inspect the native file, wear the Quest, verify tracking/controllers and real microphone/audio, and test the event network with Lee Jae-yeon. |
| Waaberi | Own the repository foundation, message schemas/examples, Blender add-on and native ping; start VoiceCore. |
| Jihyeon | Own the Unity/OpenXR project and Windows shell. Provide the exact build/run instructions and explain the editor/input actions. |
| Lee Jae-yeon | Check Windows dependencies, the CAD solver's save/reopen behavior, and second-PC reachability. |

## 1. Inspect the prepared reference: P0-T-1

Open `samples/mechanical/p0_reference_v2.blend` using **File > Open** in a separate Blender window after saving any personal work. Select `Cube_20mm`. Hover over the viewport, press **N**, and open **Item**. Dimensions should read **20, 20, 20 mm**. The cylinder should read **10, 10, 30 mm**. In **Scene Properties > Units**, confirm **Metric**, **Unit Scale 1.0**, **Millimeters**. Use **File > Save As** for a practice copy. Record whether these are useful engineering starter dimensions.

Codex can create/check the file automatically. You decide whether it is the right reference and practice finding the numbers. The native measurement evidence is `acceptance/native-reference/p0-native-reference-v2.json`.

## 2. Check physical hardware and network: P0-T-2

The local inventory is in `planning/hardware-readiness.json`. Installed versions, a running Meta service and an active OpenXR runtime establish software setup only. They do not prove the headset is paired or Air Link works.

- [ ] In the Meta Horizon Link PC app, confirm the Quest is recognized. Record any GPU compatibility warning exactly.
- [ ] In the headset's Quest Link settings, choose the wireless/Air Link connection and pair the intended PC; verify any matching code on both devices. Menu names can vary with the installed release.
- [ ] Enter PC VR. Look around and move both controllers; record whether tracking and buttons work. Use an available known working PC VR scene if the team's shell is not ready.
- [ ] Confirm the actual Quest microphone input and headset audio output with a short recording/playback, without substituting the laptop microphone. Write the observed result.
- [ ] Ask event staff whether PC-to-headset and PC-to-PC traffic is permitted on this network and whether approved Ethernet is available. The detected PC is on 5 GHz Wi-Fi; Ethernet was disconnected at inventory time. The same SSID alone does not prove device reachability.
- [ ] With Lee Jae-yeon, use the team's documented authenticated endpoint to test reachability. Record both directions and actual errors. A failed ping alone is inconclusive because ICMP can be blocked. No host endpoint exists yet in the empty repository.

Keep the Quest on Talia's PC. If wireless fails, write down the exact point of failure and continue independent work. USB Link can help development, but it does not pass the wireless test. Follow the event's networking policy.

Meta documents the [Windows Link development setup and active OpenXR runtime setting](https://developers.meta.com/vr/documentation/unity/unity-link/). The local workflow targets a Windows app streamed to Quest, so Talia does not need to create a standalone Android project for this plan.

## 3. Review expected results: P0-T-3

Read `docs/demo/DEMO_STEPS.md`. The initial primitive sizes are suggested starter values. The plan's later CAD rectangle is **100 x 60 mm**, changing to **120 x 60 mm**. Later transformation checks include **+10 mm translation** and **90-degree rotation**, verified numerically in native Blender. Do not mistake a display-only table change for a native edit.

## 4. Learn the new Unity project when Jihyeon supplies it

Open the team's existing project using Unity Hub and the agreed editor; avoid creating a competing Unity project. Spend 60-90 minutes locating **Project/Assets**, **Hierarchy**, **Scene**, **Game**, **Inspector** and **Console**. Inspect the startup scene, press **Play**, then stop. Record console errors and ask Jihyeon to show the OpenXR input actions.

Current evidence: the latest fix on `codex/jihyeon-p0-shell`, `b9e08cb`, was pulled and built successfully with Unity 6000.6.5f1. Its startup scene is `Assets/Scenes/SampleScene.unity`. The preceding `fc9ab28` build failed at runtime with missing ScreenSpaceAmbientOcclusion resources; `b9e08cb` removes that inactive render feature, and the retest log had no exceptions during the 18-second observation. Talia confirmed the new Player's actual image/head tracking over USB Link. The Player was closed gracefully and the existing project opened in Unity Editor for orientation. The fake-scene cube/disconnection UI exercise remains pending. See `P0_RESULTS.md` for both versions' evidence.

## 5. Record the P0 team gate

P0 stays WORKING until the team records agreed versions/packages and message examples, runs Jihyeon's real Windows shell, loads Waaberi's native Blender add-on and completes its ping, and records the network/CAD compatibility outcomes. CAD/network blockers must have an owner. Reference generation and mock responses cannot pass those integration checks.

Update `planning/checklists/TALIA.md` and `planning/team-tasks.json` with evidence. Record what was actually tested, the build/file identity, failures and next owner. Never fill in a hardware pass from a software inventory.
