# How we work

The full plan is in [PHASE_PLAN.md](PHASE_PLAN.md). This page is the short version of the Git and board rules.

## Daily loop

1. Pick your next issue on the [project board](https://github.com/users/waaberi/projects/3) (the "My tasks" view). Assign yourself and set **Status** to `WORKING`.
2. Branch from an up-to-date `main`:

   ```sh
   git switch main && git pull
   git switch -c codex/<person>-<phase>-<slice>   # e.g. codex/waaberi-p0-ping
   ```

3. Commit small, push, open a PR. Fill in the hand-off section and put `Closes #<issue>` in the description.
4. Merge working increments every 60–90 minutes. Squash-merge; the branch is deleted automatically.
5. After merging, run the changed component and a short smoke test of everything that already worked.

## Rules for `main`

- **Never force-push or delete `main`.** GitHub blocks it. To undo a bad change, use `git revert <sha>` and push the revert.
- Prefer PRs. Direct pushes are allowed for emergencies, but tell Waaberi.
- Reviews and CI are not required to merge. CI still runs on every PR, so look at it before merging.

## Statuses on the board

`NOT STARTED` → `WORKING` → `READY TO TEST` → `PASSED`, or `BLOCKED`. Only mark `PASSED` when the step actually works; for phase gates, only after the real team test. Use the **Build or commit**, **Evidence** and **Blocker** fields instead of guessing a percentage. Closing an issue moves it to `PASSED`.

## Phase gates and tags

When a phase's team test passes on the real setup, Waaberi tags that commit:

```sh
git tag -a p1-pass -m "P1 passed on <build id>, <evidence link>"
git push origin p1-pass
```

Use `p1-pass-2` and so on for later known-good builds of the same phase. Packaged builds are attached to a GitHub Release for the tag, never committed.

## File rules

- Only edit files in your own area (see the owner table in [README.md](README.md)). Ask the owner first, or agree to transfer the file.
- Interface changes update the sender, receiver and `contracts/` samples in the same PR.
- Unity: commit every asset together with its `.meta` file, and keep GUIDs unchanged. CI checks for missing and orphan `.meta` files.
- One person edits each binary `.blend` reference file.
- Put unfinished features behind a feature flag that is off by default.
- Never commit tokens, session credentials or machine paths. Put them in `.env` or `*.local.json` (both ignored by Git). If a secret gets pushed, rotate it; deleting the file is not enough.
- Use consistent filename case. Windows and macOS treat `Foo.cs` and `foo.cs` as the same file, so CI rejects paths that differ only by case.
- Keep files under 50 MB. Speech models and other large dependencies are downloaded by a script that pins the version and checksum.
- Clone outside cloud-sync folders such as OneDrive, iCloud or Dropbox.

## Local checks

```sh
pip install -r requirements-dev.txt
python .github/scripts/check_repo.py
python .github/scripts/validate_contracts.py
ruff check .
pytest tests
```

Python tests that need Blender should start with `bpy = pytest.importorskip("bpy")`, so CI skips them because it has no Blender install.
