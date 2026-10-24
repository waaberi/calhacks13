# CalHacks 13: Collaborative Blender VR

[![CI](https://github.com/waaberi/calhacks13/actions/workflows/ci.yml/badge.svg)](https://github.com/waaberi/calhacks13/actions/workflows/ci.yml)

A Windows VR app for building and editing a real Blender project from a Quest 3S over Air Link. A second person edits the same session from Blender on another PC. Edits in VR update native Blender, and changes made in Blender show up in VR.

- **Plan:** [PHASE_PLAN.md](PHASE_PLAN.md) covers product behavior, phases, checklists and acceptance.
- **Board:** [GitHub Project](https://github.com/users/waaberi/projects/3). Each checklist task in the plan is an issue, and each phase is a milestone.
- **How we work:** [CONTRIBUTING.md](CONTRIBUTING.md) covers branches, merging, tags and file rules.

## Deadlines

| When | Pacific | Toronto |
| --- | --- | --- |
| Feature freeze | Sat Oct 24, 7 pm | Sat Oct 24, 10 pm |
| Final integrated rehearsal | Sat Oct 24, 9 to 11 pm | Sun Oct 25, 12 to 2 am |
| **Everything done** | **Sat Oct 24, 11 pm** | **Sun Oct 25, 2 am** |
| Sleep, then pitch prep. Arrive by | Sun Oct 25, 8 am | Sun Oct 25, 11 am |
| Devpost submissions close | Sun Oct 25, 9 am | Sun Oct 25, 12 pm |

## Repository layout and owners

| Path | Owner |
| --- | --- |
| `contracts/`, `host/`, `voice-spec/`, `tests/backend/`, `tests/voice/` | Waaberi |
| `blender_addon/spatial_modeling/` (except `sketch/` and `remote_client/`) | Waaberi |
| `app/Assets/SpatialModeling/Scripts/VoiceCore/` | Waaberi |
| Root Git, CI and `.github/` | Waaberi |
| `desktop-capture/`, `scripts/windows-release/`, `tests/protocol/`, `tests/security/` | Lee Jae-yeon |
| `blender_addon/spatial_modeling/sketch/`, `blender_addon/spatial_modeling/remote_client/` | Lee Jae-yeon |
| `app/` (Unity project, except VoiceCore) | Jihyeon |
| `samples/mechanical/`, `acceptance/native-reference/`, `docs/product-workflow/`, `docs/demo/` | Talia |

Jihyeon creates the Unity project directly in `app/`. Until then, that folder does not exist.

## Tool versions

These are the initial targets. Verify and lock them in P0, then update this table.

| Tool | Version |
| --- | --- |
| Unity | 6000.6.5f1 |
| Blender | 5.2.2 (bundles Python 3.13) |
| OpenXR / Meta Horizon Link | to be pinned in P0 |
| CAD Sketcher and solver | to be pinned in P0 (GPL-3.0) |
| Speech recognition library and model | to be pinned in P4 |

## Getting started

```sh
git clone https://github.com/waaberi/calhacks13.git   # outside OneDrive/iCloud/Dropbox
cd calhacks13
pip install -r requirements-dev.txt                   # Python 3.13: ruff, pytest, jsonschema
python .github/scripts/check_repo.py                  # same hygiene checks CI runs
```
