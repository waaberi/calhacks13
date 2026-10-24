# calhacks13

Edit a real Blender project in VR on a Quest 3S over Air Link, while a second person edits the same session from desktop Blender.

- **Who owns what, and the phases:** [PHASE_PLAN.md](PHASE_PLAN.md). Its technical choices are a starting point, not final.
- **Tasks:** [project board](https://github.com/users/waaberi/projects/3)
- **Deadline:** feature freeze Sat Oct 24, 7 pm PT. Everything done by 11 pm PT.

## Working in this repo

- Branch off `main` as `codex/<person>-<phase>-<slice>` (e.g. `codex/waaberi-p0-ping`). Open a PR, and merge small working pieces every 60–90 minutes.
- `main` can't be force-pushed or deleted. Use `git revert` to undo a change.
- Keep your code in the folders you own (see the ownership table in the plan). Create a folder when you first need it.
- Unity: commit each asset together with its `.meta` file.
- Never commit tokens, machine paths or build outputs. `.env` and `*.local.json` are already ignored.
