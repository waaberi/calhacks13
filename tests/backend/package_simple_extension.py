"""Build a flat, source-pinned Blender extension ZIP without workspace/private files."""
import datetime
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "b74225d"
base = Path(sys.argv[1]).resolve()
source = subprocess.check_output(["git", "rev-parse", SOURCE], cwd=ROOT, text=True).strip()
stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
folder = base / f"simple-collaboration-v1-{stamp}"
folder.mkdir(parents=True, exist_ok=False)
prefix = "blender_addon/spatial_modeling/"
paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", source, "--", prefix],
                                cwd=ROOT, text=True).splitlines()
manifest = {}
archive = folder / "spatial_modeling-simple-collaboration.zip"
with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
    for path in sorted(paths):
        relative = path.removeprefix(prefix)
        if "__pycache__" in Path(relative).parts or Path(relative).suffix in {".pyc", ".pyo"}:
            continue
        content = subprocess.check_output(["git", "show", f"{source}:{path}"], cwd=ROOT)
        entry = zipfile.ZipInfo(relative, (2026, 10, 25, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        bundle.writestr(entry, content)
        manifest[relative] = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
with zipfile.ZipFile(archive) as check:
    assert check.testzip() is None
    assert "blender_manifest.toml" in check.namelist() and "__init__.py" in check.namelist()
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
report = {"production_source": source, "zip": archive.name, "zip_bytes": archive.stat().st_size,
          "zip_sha256": digest, "file_count": len(manifest), "files": manifest}
(folder / "SHA256-MANIFEST.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
(folder / "README.txt").write_text(f"""Simple native Blender collaboration candidate
Production source: {source}
ZIP SHA256: {digest}

Use full desktop Blender 5.2.2 on both computers. This is an add-on for ordinary
Blender, not a replacement application. Both participants share object Move (G),
Rotate (R), Scale (S), Delete (X), and authoritative host Undo/Redo. Edit Mode,
modifiers, materials, rigs, and arbitrary native data changes are not synchronized.
The host owns the original model; the Client receives its evaluated scene mirror.

Install the ZIP in Blender: Edit > Preferences > Get Extensions > menu > Install
from Disk. Enable Spatial Modeling. The ZIP is already flat: do not extract or
repack it before installation. Install matching code at BOTH ends.

Host: choose Host in Spatial Modeling preferences. Deliberately enable LAN joining
and Client object editing. Keep TLS enabled. Share the host LAN address, port 8767,
and session token privately. SpacetimeDB 'This PC' is the local collaboration route;
the host retains its in-memory lease fallback if no local database is available.
No Maincloud account or bridge is needed for this same-LAN workflow.

Client: open a separate unsaved, EMPTY Blender session (remove default objects),
choose Client, enter the host address, port and token, keep TLS enabled, then
Connect. When permission and the fresh scene arrive, select an object and use the
normal G/R/S keys or gizmos, or X. Use the add-on's Host edits Undo/Redo controls
or its registered Ctrl+Z / Ctrl+Shift+Z bindings for shared host history.
An active modal operation is submitted when confirmed; Esc cancels. Rejected
edits return to the host state. A dropped connection disables writes; explicitly
reconnect for a fresh authoritative snapshot. Unknown outcomes require inspection
and acknowledgement rather than automatic replay. Do not edit unsupported native
data types expecting those local changes to reach the other participant.

Safety and delivery status: this package does not launch Blender, replace the
running backend, modify the existing headset Player, or open a sample document.
Do not run a default sample-creating launcher to install it. An upgrade of the
currently active host/backend requires a separately coordinated runtime switch
that preserves the current model, Undo history, and unsaved Blender sessions.
The isolated install smoke and native checks are software evidence. Two physical
PCs, separate home networks, physical mouse/keyboard and headset acceptance remain
separate. The Linux VM's black screenshot issue is not an interactive GUI pass.
""", encoding="utf-8")
print(json.dumps({"folder": str(folder), "source": source, "zip_sha256": digest,
                  "files": len(manifest), "zip_bytes": archive.stat().st_size}))
