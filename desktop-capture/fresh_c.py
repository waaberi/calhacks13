"""Explicit fresh C-session launcher. Existing P1 attachment behavior is separate."""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import uuid
import zipfile
from pathlib import Path, PurePosixPath

HOST = "127.0.0.1"
PORT = 8765
IDENTITY = "codex-source-identity.json"
CAD_MANIFEST_SHA256 = "2e8c1899bf52764e43c19e6d06c79e8883314dc0fc04d97f1db62858943bbdfa"
WHEEL_NAME = "slvs-3.2-cp313-cp313-win_amd64.whl"
WHEEL_SHA256 = "86159bc0c5e749eb04d94cbf28b6d38ace795e802b8131be36870502e336f4fa"
MAX_LINE = 16 * 1024 * 1024
NOTICES = ("CAD_DEPENDENCIES.md", "CAD_SKETCHER_GPL3.txt", "SLVS_COPYING.txt")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def archive_entries(archive):
    entries = {}
    for item in archive.infolist():
        name = item.filename
        path = PurePosixPath(name)
        if ("\\" in name or path.is_absolute() or ".." in path.parts
                or (item.external_attr >> 16) & 0o170000 == 0o120000):
            raise ValueError("Package contains an unsafe path")
        if item.is_dir():
            continue
        if name in entries:
            raise ValueError("Package contains duplicate paths")
        entries[name] = archive.read(item)
    return entries


def package_identity(path, expected_sha256):
    expected_sha256 = (expected_sha256 or "").lower()
    if not re.fullmatch("[0-9a-f]{64}", expected_sha256 or ""):
        raise ValueError("Fresh C requires the published add-on ZIP SHA256")
    if sha256(path) != expected_sha256:
        raise ValueError("Add-on ZIP does not match the expected SHA256")
    with zipfile.ZipFile(path) as archive:
        entries = archive_entries(archive)
    identity = json.loads(entries.pop(IDENTITY))
    if not re.fullmatch("[0-9a-f]{40}", identity.get("source_revision", "")):
        raise ValueError("Add-on package has no exact source revision")
    actual = {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}
    if actual != identity.get("files"):
        raise ValueError("Add-on package file manifest does not match its contents")
    manifest = tomllib.loads(entries["blender_manifest.toml"].decode("utf-8"))
    if manifest.get("id") != "spatial_modeling" or "__init__.py" not in entries:
        raise ValueError("Expected the Spatial Modeling extension package")
    if any("third_party/" + name not in entries for name in NOTICES):
        raise ValueError("C package is missing retained dependency notices")
    return {**identity, "zip_sha256": expected_sha256, "app_version": manifest["version"]}


def build_addon_zip(source, target, revision):
    """Package a frozen source tree; no Blender, dependency install or process starts."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise ValueError("Use the exact frozen source commit")
    if target.exists() or target.is_relative_to(source):
        raise ValueError("Use a new ZIP outside the add-on source")
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Add-on source contains a symbolic link")
        if (not path.is_file() or "__pycache__" in path.parts
                or path.suffix == ".pyc" or path.name == IDENTITY):
            continue
        files[path.relative_to(source).as_posix()] = path
    if "blender_manifest.toml" not in files or "__init__.py" not in files:
        raise ValueError("Not an extension source directory")
    notices = source.parents[1] / "docs" / "third-party"
    for name in NOTICES:
        path = notices / name
        if not path.is_file():
            raise ValueError("Frozen C source is missing its dependency notice: " + name)
        files["third_party/" + name] = path
    identity = {"source_revision": revision, "files": {name: sha256(path) for name, path in files.items()}}
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            archive.write(path, name)
        archive.writestr(IDENTITY, json.dumps(identity, sort_keys=True))
    return {**identity, "zip_sha256": sha256(target), "zip": str(target)}


def verify_cad(extension):
    extension = Path(extension).resolve()
    if sha256(extension / "blender_manifest.toml") != CAD_MANIFEST_SHA256:
        raise ValueError("CAD Sketcher manifest is not the verified 0.32.1 pin")
    if sha256(extension / "wheels" / WHEEL_NAME) != WHEEL_SHA256:
        raise ValueError("slvs wheel is not the verified Windows CPython3.13 pin")
    return {"cad_sketcher": "0.32.1", "slvs": "3.2", "manifest_sha256": CAD_MANIFEST_SHA256,
            "wheel_sha256": WHEEL_SHA256}


def verify_player(player, expected_assembly, source_revision):
    expected_assembly = (expected_assembly or "").lower()
    if not re.fullmatch("[0-9a-f]{64}", expected_assembly) or not re.fullmatch("[0-9a-f]{40}", source_revision or ""):
        raise ValueError("Fresh C requires the tested Player assembly SHA256 and build source revision")
    player = Path(player).resolve()
    assembly = player.parent / (player.stem + "_Data") / "Managed" / "Assembly-CSharp.dll"
    if not assembly.is_file() or sha256(assembly) != expected_assembly:
        raise ValueError("Player assembly does not match the selected tested C build")
    return {"source_revision": source_revision, "assembly_sha256": expected_assembly,
            "exe_sha256": sha256(player)}


def require_free_port(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((HOST, port))
        except OSError as exc:
            raise RuntimeError("Fresh C requires free localhost8765; existing host was not attached or stopped") from exc


def isolated_environment(resources):
    resources = Path(resources).resolve()
    env = {key: value for key, value in os.environ.items() if not key.startswith("BLENDER_USER_")}
    env.update(BLENDER_USER_RESOURCES=str(resources), BLENDER_USER_CONFIG=str(resources / "config"),
               BLENDER_USER_SCRIPTS=str(resources / "scripts"), BLENDER_USER_DATAFILES=str(resources / "datafiles"))
    return env


def verify_readiness(ready, identity, process_id, working_copy, expected_port=PORT):
    if (ready.get("status") != "ready" or ready.get("pid") != process_id
            or ready.get("host") != HOST or ready.get("port") != expected_port
            or Path(ready.get("working_copy", "")).resolve() != Path(working_copy).resolve()
            or ready.get("source_revision") != identity["source_revision"]
            or ready.get("zip_sha256") != identity["zip_sha256"]
            or ready.get("cad", {}).get("available") is not True
            or ready["cad"].get("cad_sketcher") != "0.32.1" or ready["cad"].get("slvs") != "3.2"):
        raise RuntimeError("New host identity/CAD readiness did not match the selected C package and working copy")


def verify_protocol(ready, app_version, port=PORT):
    """Actual hello/snapshot/main-thread ping, never a write or editing lease."""
    hello_id, ping_id = uuid.uuid4().hex, uuid.uuid4().hex
    messages = ({"v": 1, "type": "hello", "id": hello_id,
                 "payload": {"role": "vr", "name": "C launch verification",
                             "app": {"name": "SpatialModeling", "version": app_version}}},
                {"v": 1, "type": "ping", "id": ping_id, "payload": {}})
    welcome = snapshot = None
    pong = False
    with socket.create_connection((HOST, port), timeout=3) as connection:
        connection.sendall(b"".join(json.dumps(msg).encode() + b"\n" for msg in messages))
        with connection.makefile("rb") as stream:
            for _ in range(16):
                line = stream.readline(MAX_LINE + 1)
                if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
                    raise RuntimeError("Incomplete native verification response")
                msg = json.loads(line)
                if msg.get("v") != 1:
                    raise RuntimeError("Native verification protocol version mismatch")
                if msg.get("type") == "error":
                    raise RuntimeError("Native host refused C launch verification")
                if msg.get("type") == "welcome" and msg.get("re") == hello_id:
                    welcome = msg["payload"]
                elif msg.get("type") == "scene.snapshot":
                    snapshot = msg["payload"]
                elif msg.get("type") == "pong" and msg.get("re") == ping_id:
                    pong = True
                if welcome is not None and snapshot is not None and pong:
                    break
    if (not welcome or snapshot is None or not pong
            or welcome.get("capabilities", {}).get("sketch") is not True
            or welcome.get("host_epoch") != ready.get("host_epoch")):
        raise RuntimeError("New host did not confirm native C capabilities/currentness and pong")
    expected = ready["document"]
    for doc in (welcome.get("document", {}), snapshot.get("document", {})):
        if any(doc.get(key) != expected.get(key) for key in ("id", "open_epoch")):
            raise RuntimeError("Native document changed during C launch verification")
    if snapshot["document"] != welcome["document"] or not isinstance(snapshot.get("objects"), list) \
            or not isinstance(snapshot.get("sketches"), list):
        raise RuntimeError("New host did not provide a complete current C scene")
    return {"host_epoch": welcome["host_epoch"], "document": snapshot["document"],
            "capabilities": welcome["capabilities"], "native_pong": True}


def require_selected_host(selection, process_id, requested=None):
    if (not selection or selection.get("pid") != process_id
            or (requested is not None and selection.get("hwnd") != requested)):
        raise RuntimeError("Select the newly launched C Blender window; the existing selection was not changed")


def require_fresh_pixels():
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8766/frame", timeout=3) as response:
        captured = int(response.headers["X-Captured-At"])
        if not 0 <= int(time.time() * 1000) - captured <= 3000 or not response.read(1):
            raise RuntimeError("New C host capture has no fresh actual pixels")
        return captured


def run(args, *, existing_players, capture_status):
    if existing_players(args.player.name):
        raise RuntimeError("Close the existing Player normally before a fresh C launch")
    require_free_port()  # Before file copies, dependency work, picker or Player.
    for path in (args.player, args.blender, args.blend, args.addon_zip):
        if path is None or not path.is_file():
            raise ValueError("Fresh C requires existing --player, --blender, --blend and --addon-zip files")
    if args.cad_extension is None or args.session_dir is None:
        raise ValueError("Fresh C requires --cad-extension and a new --session-dir")
    session = args.session_dir.resolve()
    if any("onedrive" in part.casefold() for part in session.parts):
        raise ValueError("Use a fresh C session outside OneDrive")
    if session.exists() and any(session.iterdir()):
        raise FileExistsError("Fresh C session already contains files; nothing was overwritten")
    identity = package_identity(args.addon_zip, args.addon_sha256)
    verify_cad(args.cad_extension)
    player_identity = ({"not_validated_or_launched": True} if args.host_only else
                       verify_player(args.player, args.player_assembly_sha256, args.player_source_revision))
    session.mkdir(parents=True, exist_ok=True)
    resources = session / "blender-resources"
    resources.mkdir()
    working = session / "working.blend"
    shutil.copy2(args.blend, working)
    addon = session / "spatial_modeling.zip"
    shutil.copy2(args.addon_zip, addon)
    cad = resources / "private-cad" / "CAD_Sketcher"
    shutil.copytree(args.cad_extension, cad, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    verify_cad(cad)
    script = Path(__file__).with_name("bootstrap_c.py")
    config = {"session": str(session), "working_copy": str(working), "addon": str(addon),
              "addon_sha256": identity["zip_sha256"], "cad_extension": str(cad)}
    write_json(session / "c-bootstrap.json", config)
    env = isolated_environment(resources)
    with (session / "blender.log").open("w", encoding="utf-8") as output:
        host = subprocess.Popen([str(args.blender), "--factory-startup", "--python", str(script),
                                 "--", str(session / "c-bootstrap.json")], env=env,
                                stdout=output, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    until = time.monotonic() + 90
    while not (session / "c-ready.json").exists():
        if host.poll() is not None or (session / "c-error.json").exists() or time.monotonic() > until:
            raise RuntimeError("New C host was not ready; inspect session blender.log/c-error.json. Other hosts were not changed")
        time.sleep(.2)
    ready = json.loads((session / "c-ready.json").read_text(encoding="utf-8"))
    verify_readiness(ready, identity, host.pid, working)
    protocol = verify_protocol(ready, identity["app_version"])
    record = {"mode": "fresh-c", "source_revision": identity["source_revision"],
              "addon_zip_sha256": identity["zip_sha256"], "host": ready,
              "native_verification": protocol, "working_copy": str(working), "player": str(args.player.resolve()),
              "player_identity": player_identity}
    write_json(session / "launch.json", record)
    if args.host_only:
        print("Fresh C native capabilities and current snapshot/pong verified; host-only mode, no picker or Player started.", flush=True)
        return
    # Only after the actual new host passed identity/currentness verification.
    if capture_status() is None:
        command = [sys.executable, str(Path(__file__).with_name("capture_helper.py"))]
        if args.window is not None:
            from capture_helper import Windows
            require_selected_host(Windows().identity(args.window), host.pid, args.window)
            command += ["--window", str(args.window)]
        with (session / "capture.log").open("w", encoding="utf-8") as output:
            helper = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
        record["capture_pid"] = helper.pid
    print(f"Choose new C Blender PID{host.pid} in the capture picker. Other windows were not selected automatically.", flush=True)
    until = time.monotonic() + 180
    while True:
        selection = capture_status("/selection")
        status = capture_status()
        if selection and selection.get("pid") == host.pid and status and status.get("state") == "capturing":
            require_selected_host(selection, host.pid, args.window)
            require_fresh_pixels()
            break
        if host.poll() is not None or time.monotonic() > until:
            raise RuntimeError("Fresh C window selection not confirmed; no Player started. New working host remains open")
        time.sleep(.25)
    if existing_players(args.player.name):
        raise RuntimeError("Another Player started during setup; no competing C Player launched")
    verify_protocol(ready, identity["app_version"])
    require_selected_host(capture_status("/selection"), host.pid, args.window)
    record["captured_at_ms"] = require_fresh_pixels()
    player_env = os.environ.copy()
    player_env["CALHACKS_HOST_PORT"] = str(PORT)
    with (session / "player-console.log").open("w", encoding="utf-8") as output:
        player = subprocess.Popen([str(args.player.resolve()), "-logFile", str(session / "player.log")],
                                  env=player_env, stdout=output, stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
    record.update(player_pid=player.pid, capture_selection=capture_status("/selection"))
    write_json(session / "launch.json", record)
    print(f"Fresh C Player started with the verified new host and working copy. Logs: {session}", flush=True)
