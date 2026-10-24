# calhacks13

Edit a real Blender project in VR on a Quest 3S over Air Link, while a second person edits the same session from desktop Blender.

- **Architecture, phases and who owns what:** [PHASE_PLAN.md](PHASE_PLAN.md). Start with its "Architecture" section.
- **Wire formats:** [contracts/README.md](contracts/README.md)
- **Tasks:** [project board](https://github.com/users/waaberi/projects/3)
- **Before changing VR placement/orientation:** [placement lifecycle contract](docs/product-workflow/PLACEMENT_ORIENTATION_CONTRACT.md)
- **Deadline:** feature freeze Sat Oct 24, 7 pm PT. Everything done by 11 pm PT.

## Where code goes

| Path | What | Owner |
| --- | --- | --- |
| `blender_addon/spatial_modeling/` | Blender add-on: Host role (server, commands, scene sync, permissions) | Waaberi |
| `blender_addon/spatial_modeling/remote_client/` | Blender add-on: Client role for the second PC | Lee Jae-yeon |
| `blender_addon/spatial_modeling/sketch/` | CAD Sketcher adapter | Lee Jae-yeon |
| `contracts/` | Wire formats, message examples and schemas | Waaberi |
| `voice/VoiceCore/` | Voice command library: plain C#, loaded by Unity as a local package | Waaberi |
| `app/` | Unity VR app, created in P0-M2-1 | Jihyeon |
| `desktop-capture/` | Blender window capture helper | Lee Jae-yeon |
| `tests/` | Tests; `tests/backend/` and `tests/voice/` are Waaberi's, `tests/protocol/` and `tests/security/` are Lee Jae-yeon's | per folder |

Other folders in the plan's ownership table (`spacetime/`, `scripts/windows-release/`, `samples/mechanical/`, `docs/demo/` and so on) are created by their owner when first needed.

## Getting started

### Verified Windows P0 versions

| Component | Version |
| --- | --- |
| Unity Editor / Windows x64 Player | 6000.6.5f1 |
| Blender | 5.2.2 LTS |
| Blender Python | 3.13.13 |
| OpenXR package | 1.18.0 |
| XR Interaction Toolkit | 3.6.1 |
| Input System | 1.20.1 |
| Universal Render Pipeline | 17.6.0 |
| Blender OpenSSL | 3.5.6; TLS PSK support verified on Talia's Windows PC |

Unity package versions are pinned in `app/Packages/manifest.json` and its lockfile.
The P0 headset run uses Quest 3S through Meta OpenXR and USB Link; Air Link and
two-PC event-network acceptance are separate checks. CAD Sketcher 0.32.1 with
slvs 3.2 was checked on Talia's Blender; this does not establish second-PC CAD
compatibility. Test evidence and outstanding gates are recorded in GitHub #5.

- **Blender add-on:** link `blender_addon/spatial_modeling` into Blender's extensions folder (`extensions/user_default/`). Then enable it under Preferences > Add-ons and pick Host or Client.
- **Unity app:** open `app/` with Unity 6000.6.5f1. VoiceCore is referenced from `app/Packages/manifest.json` as `"com.calhacks13.voicecore": "file:../../voice/VoiceCore"`.
- **Checks:** `pip install ruff pytest jsonschema`, then run `ruff check .` and `pytest tests`. CI runs the same on every PR.

## Working in this repo

- Branch off `main` as `codex/<person>-<phase>-<slice>` (e.g. `codex/waaberi-p0-ping`). Open a PR with `Closes #<issue>`, and merge small working pieces every 60–90 minutes.
- `main` can't be force-pushed or deleted. Use `git revert` to undo a change.
- Unity: commit each asset together with its `.meta` file.
- Never commit tokens, machine paths, build outputs or speech models. `.env` and `*.local.json` are already ignored.
