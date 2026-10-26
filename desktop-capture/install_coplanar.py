"""Install a per-user Coplanar launcher and shortcuts. Does not launch VR or Blender."""
import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

from coplanar_setup import discover_blender, local_data, validate_package, write_json


def install_shortcuts(pythonw, entry, package):
    """Use Windows' native Shell Link API; no shell scripts or policy changes."""
    import ctypes as C
    from ctypes import wintypes as W

    class GUID(C.Structure):
        _fields_ = [("bytes", C.c_ubyte * 16)]

        def __init__(self, value):
            super().__init__()
            C.memmove(C.byref(self), uuid.UUID(value).bytes_le, 16)

    ole = C.OleDLL("ole32")
    shell = C.WinDLL("shell32")
    ole.CoInitialize.argtypes = [C.c_void_p]
    ole.CoInitialize.restype = W.LONG
    initialized = ole.CoInitialize(None)
    ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, W.DWORD, C.POINTER(GUID), C.POINTER(C.c_void_p)]
    ole.CoCreateInstance.restype = W.LONG
    shell.SHGetFolderPathW.argtypes = [W.HWND, C.c_int, W.HANDLE, W.DWORD, W.LPWSTR]
    shell.SHGetFolderPathW.restype = W.LONG
    def checked(code):
        if code < 0:
            raise OSError(f"Windows shortcut operation failed (0x{code & 0xffffffff:08x})")
    def call(pointer, index, arguments, *values):
        table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
        return C.WINFUNCTYPE(W.LONG, C.c_void_p, *arguments)(table[index])(pointer, *values)
    paths = []
    try:
        for folder_id in (0x10, 0x02):  # User Desktop and Start Menu Programs; honors redirection.
            folder = C.create_unicode_buffer(32768)
            checked(shell.SHGetFolderPathW(None, folder_id, None, 0, folder))
            directory = Path(folder.value)
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / "Coplanar.lnk"
            if destination.exists():
                backup = local_data() / "shortcut-backups" / (uuid.uuid4().hex + ".lnk")
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            link = C.c_void_p()
            checked(ole.CoCreateInstance(C.byref(GUID("00021401-0000-0000-c000-000000000046")), None, 1,
                    C.byref(GUID("000214f9-0000-0000-c000-000000000046")), C.byref(link)))
            persist = C.c_void_p()
            try:
                args = f'"{entry}" --package "{package}"'
                for index, value in ((20, str(pythonw)), (11, args), (9, str(entry.parent)),
                                     (7, "Connect Blender and start your Coplanar VR workspace")):
                    checked(call(link, index, [W.LPCWSTR], value))
                checked(call(link, 17, [W.LPCWSTR, C.c_int], str(package / "SpatialModeling.exe"), 0))
                checked(call(link, 0, [C.POINTER(GUID), C.POINTER(C.c_void_p)],
                             C.byref(GUID("0000010b-0000-0000-c000-000000000046")), C.byref(persist)))
                checked(call(persist, 6, [W.LPCWSTR, W.BOOL], str(destination), True))
                # Read arguments back from the native link object before reporting success.
                buffer = C.create_unicode_buffer(32768)
                checked(call(link, 10, [W.LPWSTR, C.c_int], buffer, len(buffer)))
                if buffer.value != args or not destination.is_file():
                    raise RuntimeError("Coplanar shortcut verification failed")
                paths.append(str(destination))
            finally:
                if persist.value:
                    call(persist, 2, [])
                call(link, 2, [])
    finally:
        if initialized >= 0:
            ole.CoUninitialize()
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--blend", type=Path)
    args = parser.parse_args()
    package = validate_package(args.package)
    # Check imports before changing shortcuts. No windows/captures are created.
    sys.path.insert(0, str(package / "python-deps"))
    import importlib

    for module in ("tkinter", "PIL", "cv2", "numpy", "windows_capture"):
        importlib.import_module(module)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        raise RuntimeError("Install using the bundled Windows Python runtime, including pythonw.exe.")
    data = local_data()
    release = data / "launcher" / uuid.uuid4().hex
    release.mkdir(parents=True)
    source = Path(__file__).parent
    for path in source.glob("*.py"):
        if not path.name.startswith("test_"):
            shutil.copy2(path, release / path.name)
    settings = data / "settings.json"
    if not settings.is_file():
        write_json(settings, {"package": str(package), "blender": discover_blender(),
                              "blend": str(args.blend.resolve()) if args.blend else ""})
    shortcuts = install_shortcuts(pythonw, release / "coplanar_setup.py", package)
    write_json(data / "installation.json", {"launcher": str(release), "package": str(package),
               "python": str(pythonw), "shortcuts": shortcuts, "applications_started": False})
    print(json.dumps({"installed": True, "launcher": str(release), "applications_started": False,
                      "shortcuts": shortcuts}))


if __name__ == "__main__":
    main()
