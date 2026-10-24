"""Repository hygiene checks run by CI on every push and pull request.

Catches problems that are easy to create on a mixed Windows/macOS/Linux team:
paths that differ only by letter case, Unity assets committed without their
.meta file (or orphaned .meta files), generated/secret files force-added past
.gitignore, and files too large for GitHub.

Run locally from the repo root: python .github/scripts/check_repo.py
"""

import os
import re
import subprocess
import sys
from collections import defaultdict

MAX_FILE_BYTES = 50 * 1024 * 1024  # GitHub warns at 50 MB and rejects 100 MB
UNITY_ASSETS = "app/Assets/"
GENERATED_UNITY_DIRS = ("library", "temp", "obj", "build", "builds", "logs", "usersettings")
SECRET_NAMES = {".env"}
SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12")
BLEND_BACKUP = re.compile(r"\.blend\d+$")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def parent_dirs(path):
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def unity_ignores(path):
    """Unity skips names starting with '.', ending with '~', 'cvs' and '*.tmp'."""
    return any(
        part.startswith(".") or part.endswith(("~", ".tmp")) or part.lower() == "cvs"
        for part in path.split("/")
    )


def check_case_collisions(files):
    errors = []
    by_lower = defaultdict(set)
    for path in files:
        by_lower[path.lower()].add(path)
        for d in parent_dirs(path):
            by_lower[d.lower()].add(d)
    for variants in by_lower.values():
        if len(variants) > 1:
            names = ", ".join(sorted(variants))
            errors.append((min(variants), f"Paths differ only by case (breaks Windows/macOS): {names}"))
    return errors


def check_unity_meta(files):
    errors = []
    tracked = set(files)
    assets = [p for p in files if p.startswith(UNITY_ASSETS) and not unity_ignores(p[len(UNITY_ASSETS):])]
    dirs = {d for p in assets for d in parent_dirs(p) if d.startswith(UNITY_ASSETS)}
    for path in assets:
        if path.endswith(".meta"):
            target = path[: -len(".meta")]
            if target not in tracked and target not in dirs:
                errors.append((path, "Orphan .meta: its asset or folder is not committed. Delete it or commit the asset."))
        elif path + ".meta" not in tracked:
            errors.append((path, "Unity asset committed without its .meta file. Commit both together."))
    for d in sorted(dirs):
        if d + ".meta" not in tracked:
            errors.append((d, "Unity folder committed without its .meta file."))
    return errors


def check_forbidden(files):
    errors = []
    for path in files:
        lower = path.lower()
        name = lower.rsplit("/", 1)[-1]
        if any(lower.startswith(f"app/{d}/") for d in GENERATED_UNITY_DIRS):
            errors.append((path, "Generated Unity folder content must not be committed."))
        elif name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES):
            errors.append((path, "Looks like a secret or credential file. Remove it and rotate the secret."))
        elif BLEND_BACKUP.search(name):
            errors.append((path, "Blender backup save (.blend1, .blend2, ...) must not be committed."))
    return errors


def check_sizes(files):
    errors = []
    for path in files:
        if os.path.isfile(path) and not os.path.islink(path):
            size = os.path.getsize(path)
            if size > MAX_FILE_BYTES:
                errors.append((path, f"File is {size / 1024 / 1024:.0f} MB; keep large files out of Git (use a pinned download or a GitHub Release)."))
    return errors


def main():
    files = tracked_files()
    errors = check_case_collisions(files) + check_unity_meta(files) + check_forbidden(files) + check_sizes(files)
    for path, message in errors:
        print(f"::error file={path}::{message}")
        print(f"  {path}: {message}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} repository hygiene problem(s) found.", file=sys.stderr)
        return 1
    print(f"Repository hygiene OK ({len(files)} tracked files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
