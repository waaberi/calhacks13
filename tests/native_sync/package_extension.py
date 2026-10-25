"""Package only pinned tracked add-on sources; never include local user data."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", default="HEAD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = subprocess.check_output(["git", "rev-parse", args.source], cwd=root, text=True).strip()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    prefix = "blender_addon/spatial_modeling/"
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", source, "--", prefix],
                                    cwd=root, text=True).splitlines()
    archive = out / "spatial_modeling-native-collaboration-0.2.0.zip"
    files = {}
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(paths):
            name = path.removeprefix(prefix)
            assert "__pycache__" not in Path(name).parts and Path(name).suffix not in {".pyc", ".pyo"}
            data = subprocess.check_output(["git", "show", f"{source}:{path}"], cwd=root)
            entry = zipfile.ZipInfo(name, (2026, 10, 25, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            bundle.writestr(entry, data)
            files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
        assert {"blender_manifest.toml", "__init__.py", "native_sync/document.py",
                "native_sync/fingerprint.py", "native_sync/host.py", "native_sync/client.py"} <= set(check.namelist())
        assert b'version = "0.2.0"' in check.read("blender_manifest.toml")
    report = {"production_source": source, "zip": archive.name, "zip_bytes": archive.stat().st_size,
        "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": files,
        "file_count": len(files), "requires_matching_host_upgrade": True,
        "current_runtime_changed": False, "physical_acceptance": False}
    (out / "SHA256-MANIFEST.json").write_text(json.dumps(report, indent=2) + "\n")
    instructions = subprocess.check_output(["git", "show",
        f"{source}:docs/product-workflow/NATIVE_SHARED_BLENDER.md"], cwd=root)
    (out / "README.txt").write_bytes(instructions)
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, indent=2))


if __name__ == "__main__":
    main()
