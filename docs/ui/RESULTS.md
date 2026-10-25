> Historical source-glass results for 06c136a / v14. Combined integration behavior and fresh verification are recorded in `COMBINED_INTEGRATION.md`; this file is not the combined build manifest.

# Glass appearance revision

The first v9 candidate was rejected by the human as rounded transparency. That visual gap was real. The revised software candidate adds actual Unity-scene diffusion and a rounded optical bevel; it is delivered for human appearance review, not claimed visually/physically accepted.

Compiled source: `06c136a9115a3d44f1694f7176accd802b7a280d`, isolated branch `codex/talia-p3-glass-ui`, run `p3-glass-ui-v14`. Later documentation commits do not change the compiled application. Package BUILD-RECORD.json contains binary/source/package hashes and exact compiler inputs.

## New verification

- Actual Unity6000.6.5f1 Windows build succeeds with zero errors, exit0. Cumulative P1/P2/P2.5 checks pass, including placement, room replay, native-only menu/input, release/focus, curved pixel mapping, controller ownership/loss and accepted aim drag.
- Real GPU readback compares identical material/tint with diffusion disabled/enabled: high-frequency detail drops from0.005569 to0.000858, ratio0.1541. Simple darkening cannot satisfy this comparison. Changing the actual scene changes the glass output.
- Refraction enabled/disabled produces measured bevel pixel difference0.005116. Empty-scene glass retains alpha0.7216; surrounding scene alpha remains0.0000. No compositor texture is sampled or claimed blurred.
- Complete batched component gallery retains the required optical shape channel on every dynamic control. Actual rendered gallery, all states, dark/bright/detailed backgrounds, dialog, off-axis eye references, curved preview/keyboard and2x high-contrast preview were inspected. Preview imagery is explicitly synthetic, not live Blender.
- Real BeforeRender/RenderHand fixture: both hands and both pose formats,480 rapid samples, deliberately different grip/aim, origin/recenter/loss. Deterministic tip/ray error below1micrometre, angle below0.03degrees. No new controller follow delay.
- BlenderScreen curved inverse covers four scales, three yaws, corners/edges, magnification/pan with less than one native pixel error. Working RawImage pixels remain outside the glass material, retaining source resolution/aspect and full native reachability.
- Exact34 accepted OpenXR feature flags and original render scale1/MSAA4/framebuffer/URP alpha remain frozen. Added feature lives on the existing renderer. Only its diffusion texture is half resolution; camera and streamed capture quality are unchanged.
- Theme audit passes. Previously verified unchanged capture/input suites remain applicable:151 helper/capture/launcher checks and actual UnityWebRequest7window/9input/2release-ACK cases. This material-only revision does not claim a fresh physical or live capture run.
- Private Blender theme verification retained:96 supported properties,16 roundness controls, no saved personal preferences/document. Native engine layout/separators/icons and some popup geometry remain Blender-owned.

## Research and scope

Five actual GitHub implementations were reviewed at pinned commits, with source/license decisions in [RESEARCH.md](RESEARCH.md). Public shared API/optical path and adoption details are in [GLASS_SYSTEM.md](GLASS_SYSTEM.md); full surface inventory is in [COVERAGE.md](COVERAGE.md). No upstream code package or proprietary Apple asset is distributed.

The source starts from P3 candidate1635668 and reconciles newer P2/P2.5 clarity/controller fixes efad88f/96f1093. Backend/contracts remain unchanged versus the P3 candidate. Later main voice/participant integrations are separate owner work and were not copied into this bounded isolated appearance branch.

## Limits and retained failures

Meta Windows Link compositor room pixels are unavailable to this shader. Opaque Unity content receives real diffusion/refraction; physical-room regions use the readable alpha-preserving satin/reflection fallback. Transparent Unity objects and other UI are excluded from the pre-transparent backdrop, preventing recursive text blur. Native working pixels are never frosted.

v10 caught an invalid RenderGraph read/write attachment alias; distinct scene-copy textures fixed it. Gallery review then caught dropped TexCoord1 metadata on dynamically parented controls; explicit canvas-channel setup and a batched-gallery gate fixed it. A diagnostic inspection used an outdated GetMesh overload and was corrected to the installed API. Failed logs and v9 renders remain in evidence; no acceptance assertion was removed.

Actual headset stereo/alpha composition, physical controller fit/feel, curve/drag comfort, live changing native capture/readability and final visual approval remain pending. No app/helper/Blender/Meta session was launched, stopped or reconfigured. No push, PR/main change or FPS work occurred. The package includes the guarded launcher and focused new-appearance headset checklist for the human-authorized runtime handoff.
