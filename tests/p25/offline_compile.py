"""Compile current Unity C# against an existing imported cache, without Unity.

Reads the reference/define options produced by a previous compatible Unity import.
Writes only to --output. This is a compiler check, not Unity/VR runtime evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def outside_worktree(path: Path) -> None:
    for directory in (path, *path.parents):
        if (directory / ".git").exists() or directory.name.lower().startswith("onedrive"):
            raise ValueError("Output must be outside Git worktrees and OneDrive")


def quote(path: Path) -> str:
    return '"' + path.as_posix() + '"'


def relocate(
    template: Path, cache: Path, sources: list[Path], output: Path, runtime: Path | None
) -> str:
    result = []
    for line in template.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(("-out:", "-refout:", "-analyzer:", "/additionalfile:", "-additionalfile:")):
            continue
        if line.lstrip('"').startswith("Assets/") and line.rstrip('"').endswith(".cs"):
            continue
        if line.startswith("-r:"):
            reference = Path(line[3:].strip('"'))
            if runtime is not None and reference.name == "Assembly-CSharp.ref.dll":
                reference = runtime
            elif not reference.is_absolute():
                reference = cache / reference
            if not reference.is_file():
                raise FileNotFoundError(reference)
            line = "-r:" + quote(reference)
        result.append(line)
    result += ["-out:" + quote(output), *[quote(source) for source in sources]]
    return "\n".join(result) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-app", required=True, type=Path, help="Previously imported app directory; read only")
    parser.add_argument("--unity-data", required=True, type=Path, help="Unity Editor/Data directory")
    parser.add_argument("--output", required=True, type=Path, help="Dedicated external output directory")
    parser.add_argument("--run-managed-checks", action="store_true", help="Run mapping/session checks under bundled Mono; no Unity process")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    cache = args.cache_app.resolve()
    output = args.output.resolve()
    outside_worktree(output)
    output.mkdir(parents=True, exist_ok=True)
    sdk = args.unity_data.resolve() / "DotNetSdk"
    compilers = sorted(sdk.glob("sdk/*/Roslyn/bincore/csc.dll"))
    if not compilers:
        raise FileNotFoundError("Unity bundled C# compiler not found")
    templates = sorted((p for p in (cache / "Library/Bee/artifacts").glob("*/Assembly-CSharp.rsp")
                        if (p.parent / "Assembly-CSharp-Editor.rsp").is_file()),
                       key=lambda p: p.stat().st_mtime)
    if not templates:
        raise FileNotFoundError("No imported Unity Assembly-CSharp.rsp in cache")
    template_dir = templates[-1].parent
    app = root / "app"
    source_root = app / "Assets"
    sources = sorted(p for p in source_root.rglob("*.cs") if "Samples" not in p.relative_to(source_root).parts)
    snapshots = {}
    manifest: dict = {"method": "offline Roslyn compiler; no Unity process", "cache_app": str(cache),
                      "runtime_acceptance": False, "sources": {}, "assemblies": []}
    for source in sources:
        data = source.read_bytes()
        relative = source.relative_to(root)
        snapshot = output / "sources" / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(data)
        snapshots[source] = snapshot
        manifest["sources"][relative.as_posix()] = hashlib.sha256(data).hexdigest()
    runtime_sources = [snapshots[p] for p in sources if "Editor" not in p.relative_to(source_root).parts]
    editor_sources = [snapshots[p] for p in sources if "Editor" in p.relative_to(source_root).parts]
    runtime_dll = output / "Assembly-CSharp.dll"
    for name, group in (("Assembly-CSharp", runtime_sources), ("Assembly-CSharp-Editor", editor_sources)):
        rsp = output / (name + ".rsp")
        dll = output / (name + ".dll")
        text = relocate(template_dir / (name + ".rsp"), cache, group, dll,
                        runtime_dll if name.endswith("Editor") else None)
        rsp.write_text(text, encoding="utf-8")
        command = [str(sdk / "dotnet.exe"), str(compilers[-1]), "@" + str(rsp)]
        completed = subprocess.run(command, cwd=output, capture_output=True, text=True, check=False)
        log = completed.stdout + completed.stderr
        (output / (name + ".log")).write_text(log, encoding="utf-8")
        print(f"{name}: exit={completed.returncode} sources={len(group)}")
        print(log, end="")
        manifest["assemblies"].append({"name": name, "exit_code": completed.returncode,
                                        "sha256": hashlib.sha256(dll.read_bytes()).hexdigest() if completed.returncode == 0 else None})
        (output / "compile-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if completed.returncode:
            return completed.returncode
    print("P25_OFFLINE_COMPILE PASS; Unity checks/build and native/VR acceptance remain separate")
    if args.run_managed_checks:
        harness = root / "tests/p25/ManagedChecks.cs"
        rsp = output / "ManagedChecks.rsp"
        runner = output / "ManagedChecks.exe"
        text = relocate(template_dir / "Assembly-CSharp.rsp", cache, [harness], runner, None)
        text += "-target:exe\n-r:" + quote(runtime_dll) + "\n-r:" + quote(output / "Assembly-CSharp-Editor.dll") + "\n"
        rsp.write_text(text, encoding="utf-8")
        completed = subprocess.run([str(sdk / "dotnet.exe"), str(compilers[-1]), "@" + str(rsp)],
                                   cwd=output, capture_output=True, text=True, check=False)
        compile_log = completed.stdout + completed.stderr
        (output / "ManagedChecks-compile.log").write_text(compile_log, encoding="utf-8")
        print(compile_log, end="")
        if completed.returncode:
            return completed.returncode
        env = os.environ.copy()
        env["MONO_PATH"] = os.pathsep.join(str(p) for p in (
            output, args.unity_data / "Managed/UnityEngine", args.unity_data / "Managed",
            cache / "Library/ScriptAssemblies"))
        completed = subprocess.run([str(args.unity_data / "MonoBleedingEdge/bin/mono.exe"), str(runner), str(root)],
                                   cwd=output, env=env, capture_output=True, text=True, check=False)
        log = completed.stdout + completed.stderr
        (output / "ManagedChecks.log").write_text(log, encoding="utf-8")
        print(log, end="")
        manifest["managed_checks_exit_code"] = completed.returncode
        manifest["managed_harness_sha256"] = hashlib.sha256(harness.read_bytes()).hexdigest()
        (output / "compile-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return completed.returncode
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, FileNotFoundError) as error:
        print(error, file=sys.stderr)
        sys.exit(2)
