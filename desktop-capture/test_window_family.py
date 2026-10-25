"""Window-family checks use metadata and fake Win32 only; no desktop access."""

import ctypes as C
import unittest
from copy import deepcopy
from ctypes import wintypes as W
from types import SimpleNamespace

from capture_helper import Windows, WindowUnavailable
from window_family import MAX_OWNER_DEPTH, resolve_window


def record(hwnd, pid=200, cls="GHOST_WindowClass", owner=0, executable=None,
           parent=0, menu_owner=0, title="Blender"):
    return {"hwnd": hwnd, "pid": pid, "window_class": cls, "owner_hwnd": owner,
            "executable": executable if executable is not None else r"C:\Blender\blender.exe",
            "parent_hwnd": parent, "menu_owner_hwnd": menu_owner, "title": title}


class FamilyTests(unittest.TestCase):
    def setUp(self):
        self.records = {100: record(100)}

    def resolve(self, hwnd, **kwargs):
        return resolve_window(hwnd, lambda key: deepcopy(self.records.get(key)), **kwargs)

    def test_direct_blender_and_same_process_secondary_share_declared_root(self):
        self.records[101] = record(101, owner=100)
        for hwnd in (100, 101):
            item = self.resolve(hwnd, blender_pid=200)
            self.assertEqual((item["hwnd"], item["pid"], item["kind"]), (hwnd, 200, "blender"))
            self.assertEqual((item["blender_hwnd"], item["blender_pid"]), (100, 200))
            self.assertNotIn("executable", item)
        self.records[102] = record(102, owner=101)
        self.assertEqual(self.resolve(102)["blender_hwnd"], 100)
        del self.records[100]
        self.assertIsNone(self.resolve(101), "a lost declared owner does not promote an auxiliary root")
        self.assertIsNone(self.resolve(102))

    def test_ghost_ancestors_must_all_be_the_same_native_blender_process(self):
        self.records[101] = record(101, pid=201, owner=100)
        self.assertIsNone(self.resolve(101))
        self.records[101] = record(101, owner=100)
        self.records[100]["executable"] = r"C:\Other\not-blender.exe"
        self.assertIsNone(self.resolve(101))
        self.records[100]["executable"] = r"C:\Blender\blender.exe"
        self.records[100]["owner_hwnd"] = 101
        self.assertIsNone(self.resolve(101), "GHOST owner cycles cannot establish a terminal native root")

    def test_owned_dialog_popup_and_custom_class_require_real_chain(self):
        for cls, kind in (("#32770", "dialog"), ("#32768", "popup"),
                          ("CustomBlenderDialog", "dialog"), ("ComboLBox", "popup")):
            with self.subTest(cls=cls):
                self.records[101] = record(101, cls=cls, owner=100, title="")
                item = self.resolve(101)
                self.assertEqual((item["kind"], item["owner_hwnd"], item["blender_hwnd"]),
                                 (kind, 100, 100))
                self.records[101]["owner_hwnd"] = 0
                self.assertIsNone(self.resolve(101))

    def test_nested_and_brokered_dialogs_may_cross_process_boundaries(self):
        self.records[101] = record(101, pid=300, cls="#32770", owner=100,
                                   executable=r"C:\Windows\System32\broker.exe")
        self.records[102] = record(102, pid=301, cls="BrokerChild", owner=101,
                                   executable=r"C:\Windows\System32\other.exe")
        item = self.resolve(102, blender_pid=200)
        self.assertEqual((item["pid"], item["owner_hwnd"], item["blender_pid"]), (301, 101, 200))
        self.assertIsNone(self.resolve(102, blender_pid=300))
        self.records[101]["executable"] = None  # Target executable is optional; native root proof is not.
        self.assertIsNotNone(self.resolve(102))
        self.records[100]["executable"] = None
        self.assertIsNone(self.resolve(102))

    def test_missing_owner_never_falls_back_to_another_same_pid_window(self):
        self.records[101] = record(101, cls="#32770", owner=102)
        self.assertIsNone(self.resolve(101))
        self.records[102] = record(102, cls="Dialog", owner=100)
        self.assertIsNotNone(self.resolve(101))
        del self.records[102]
        self.assertIsNone(self.resolve(101))
        self.assertIsNotNone(self.resolve(100))

    def test_console_title_and_executable_spoofs_are_refused(self):
        for hwnd, cls, executable in ((101, "ConsoleWindowClass", r"C:\Blender\blender.exe"),
                                      (102, "GHOST_WindowClass", r"C:\Apps\not-blender.exe"),
                                      (103, "#32770", r"C:\Apps\other.exe")):
            self.records[hwnd] = record(hwnd, cls=cls, executable=executable, title="Blender File Browser")
            self.assertIsNone(self.resolve(hwnd))
        self.records[102]["owner_hwnd"] = 100
        self.assertIsNone(self.resolve(102), "a counterfeit GHOST cannot become an ordinary owned dialog")

    def test_owner_cycle_and_depth_limit_are_bounded(self):
        self.records[101] = record(101, cls="#32770", owner=102)
        self.records[102] = record(102, cls="#32770", owner=101)
        self.assertIsNone(self.resolve(101))
        self.records[102]["owner_hwnd"] = 100
        self.assertIsNone(self.resolve(101, max_depth=2))
        self.assertIsNotNone(self.resolve(101, max_depth=3))
        calls = []

        def endless(hwnd):
            calls.append(hwnd)
            return record(hwnd, cls="#32770", owner=hwnd + 1)

        self.assertIsNone(resolve_window(1, endless, max_depth=10**6))
        self.assertEqual(len(calls), MAX_OWNER_DEPTH)

    def test_wrong_raw_handle_pid_or_root_pid_cannot_recycle_declaration(self):
        self.records[101] = record(102, cls="#32770", owner=100)
        self.assertIsNone(self.resolve(101))
        self.records[101] = record(101, pid=0, cls="#32770", owner=100)
        self.assertIsNone(self.resolve(101))
        self.assertIsNone(self.resolve(100, blender_pid=201))
        self.records[100]["pid"] = 201
        self.assertIsNone(self.resolve(100, blender_pid=200))

    def test_menu_without_gw_owner_requires_menu_owner_or_parent_proof(self):
        self.records[101] = record(101, cls="#32768", menu_owner=100)
        item = self.resolve(101, blender_pid=200)
        self.assertEqual((item["kind"], item["owner_hwnd"], item["menu_owner_hwnd"], item["blender_hwnd"]),
                         ("popup", 0, 100, 100))
        self.records[101]["menu_owner_hwnd"] = 0
        self.assertIsNone(self.resolve(101))
        self.records[101]["parent_hwnd"] = 100
        self.assertIsNotNone(self.resolve(101))
        self.records[102] = record(102, pid=300, executable=r"C:\Apps\other.exe")
        self.records[101].update(parent_hwnd=0, menu_owner_hwnd=102)
        self.assertIsNone(self.resolve(101))

    def test_menu_owner_mismatch_and_generic_menu_proof_are_refused(self):
        self.records[101] = record(101, cls="#32768", owner=100, menu_owner=102)
        self.assertIsNone(self.resolve(101))
        self.records[101] = record(101, cls="UnownedCustom", menu_owner=100)
        self.assertIsNone(self.resolve(101), "GUI menu-owner proof applies only to native menu windows")

    def test_child_parent_chain_is_still_bounded_and_native_root_verified(self):
        self.records[101] = record(101, cls="ComboLBox", parent=102)
        self.records[102] = record(102, cls="ComboBox", parent=100)
        self.assertEqual(self.resolve(101)["blender_hwnd"], 100)
        self.records[102]["parent_hwnd"] = 101
        self.assertIsNone(self.resolve(101))


class FakeWin32:
    """Only read operations exist here: activation/capture/input are impossible."""
    def __init__(self, records):
        self.records, self.closed = records, []
        self.pid_reads, self.owner_reads = [], []
        self.menu_reads, self.menu_available = [], True
        self.menu_threads = []
        self.hidden, self.denied = set(), set()

    def IsWindow(self, hwnd):
        return hwnd in self.records

    def IsWindowVisible(self, hwnd):
        return hwnd in self.records and hwnd not in self.hidden

    def GetWindowThreadProcessId(self, hwnd, pointer):
        pid = self.pid_reads.pop(0) if self.pid_reads else self.records[hwnd]["pid"]
        C.cast(pointer, C.POINTER(W.DWORD)).contents.value = pid
        return hwnd + 1000

    def GetWindowTextW(self, hwnd, buffer, _):
        buffer.value = self.records[hwnd]["title"]
        return len(buffer.value)

    def GetClassNameW(self, hwnd, buffer, _):
        buffer.value = self.records[hwnd]["window_class"]
        return len(buffer.value)

    def GetWindow(self, hwnd, mode):
        assert mode == 4
        return self.owner_reads.pop(0) if self.owner_reads else self.records[hwnd]["owner_hwnd"]

    def GetParent(self, hwnd):
        return self.records[hwnd]["parent_hwnd"]

    def GetGUIThreadInfo(self, thread_id, pointer):
        self.menu_threads.append(thread_id)
        if not self.menu_available:
            return False
        info = C.cast(pointer, C.POINTER(Windows.GUIThreadInfo)).contents
        assert info.cbSize == C.sizeof(Windows.GUIThreadInfo)
        info.hwndMenuOwner = (self.menu_reads.pop(0) if self.menu_reads else
                              self.records[thread_id - 1000]["menu_owner_hwnd"])
        return True

    def OpenProcess(self, _, inherit, pid):
        assert not inherit
        return None if pid in self.denied else pid

    def QueryFullProcessImageNameW(self, handle, _, buffer, length):
        item = next(item for item in self.records.values() if item["pid"] == handle)
        buffer.value = item["executable"] or ""
        C.cast(length, C.POINTER(W.DWORD)).contents.value = len(buffer.value)
        return bool(buffer.value)

    def CloseHandle(self, handle):
        self.closed.append(handle)

    def EnumWindows(self, callback, _):
        for hwnd in self.records:
            callback(hwnd, 0)
        return True


class WindowsFamilyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.records = {100: record(100), 101: record(101, cls="#32770", owner=100),
                        102: record(102, cls="ConsoleWindowClass"),
                        103: record(103, pid=300, cls="#32770", owner=101,
                                    executable=r"C:\Windows\broker.exe")}
        self.fake = FakeWin32(self.records)
        self.api = Windows.__new__(Windows)
        self.api.u = self.api.k = self.fake
        self.api.callback = lambda callback: callback

    def test_raw_window_reads_owner_class_process_and_releases_handle(self):
        raw = self.api.raw_window(103)
        self.assertEqual(raw, self.records[103])
        self.assertEqual(self.fake.closed, [300])
        self.assertIsNone(self.api.raw_window(999))

    def test_broker_executable_access_denial_does_not_remove_native_owner_proof(self):
        self.fake.denied.add(300)
        self.api.input_bridge = SimpleNamespace(enabled=True)
        self.assertEqual(self.api.identity(103)["blender_pid"], 200)
        self.fake.denied.add(200)
        self.assertIsNone(self.api.identity(103))

    def test_raw_read_rejects_pid_or_owner_recycling(self):
        self.fake.pid_reads = [300, 301]
        self.assertIsNone(self.api.raw_window(103))
        self.fake.owner_reads = [101, 100]
        self.assertIsNone(self.api.raw_window(103))
        self.assertEqual(self.fake.closed, [300, 300])

    def test_legacy_default_and_disabled_bridge_stay_ghost_only(self):
        expected = [{"hwnd": 100, "pid": 200, "title": "Blender"}]
        for bridge in (None, SimpleNamespace(enabled=False)):
            self.api.input_bridge = bridge
            self.assertEqual(self.api.windows(), expected)
            self.assertEqual(self.api.windows(include_owned=True), expected)
            self.assertIsNone(self.api.identity(101))
            self.assertEqual(self.api.identity(100), expected[0])
        self.records[104] = record(104, owner=999)
        self.assertEqual(self.api.identity(104), {"hwnd": 104, "pid": 200, "title": "Blender"},
                         "legacy direct GHOST semantics do not depend on a live owner")
        self.api.input_bridge.enabled = True
        self.assertIsNone(self.api.identity(104))

    def test_enabled_owned_list_is_explicit_visible_and_family_only(self):
        self.api.input_bridge = SimpleNamespace(enabled=True)
        self.assertEqual([item["hwnd"] for item in self.api.windows()], [100])
        self.assertEqual([item["hwnd"] for item in self.api.windows(include_owned=True)], [100, 101, 103])
        self.fake.hidden.add(101)
        self.assertEqual([item["hwnd"] for item in self.api.windows(include_owned=True)], [100, 103])
        self.assertEqual(self.api.identity(103)["owner_hwnd"], 101)

    def test_menu_owner_read_uses_target_thread_only_for_native_menu_class(self):
        self.api.input_bridge = SimpleNamespace(enabled=True)
        self.records[104] = record(104, cls="#32768", menu_owner=100)
        item = self.api.identity(104)
        self.assertEqual((item["kind"], item["menu_owner_hwnd"]), ("popup", 100))
        self.assertEqual(self.fake.menu_threads, [1104, 1104])
        self.api.raw_window(101)
        self.assertEqual(self.fake.menu_threads, [1104, 1104])

    def test_missing_or_changed_native_menu_owner_proof_refuses_membership(self):
        self.api.input_bridge = SimpleNamespace(enabled=True)
        self.records[104] = record(104, cls="#32768", menu_owner=100)
        self.fake.menu_available = False
        self.assertIsNone(self.api.identity(104))
        self.fake.menu_available = True
        self.fake.menu_reads = [100, 0]
        self.assertIsNone(self.api.raw_window(104))
        self.records[104]["menu_owner_hwnd"] = 999
        self.assertIsNone(self.api.identity(104))

    def test_capture_refuses_changed_target_and_family_before_any_pixel_call(self):
        self.api.input_bridge = SimpleNamespace(enabled=True)
        selected = self.api.identity(103)
        for field, replacement in (("pid", 301), ("window_class", "OtherClass"),
                                   ("owner_hwnd", 100), ("parent_hwnd", 999),
                                   ("menu_owner_hwnd", 100), ("blender_hwnd", 999), ("blender_pid", 201)):
            with self.subTest(field=field):
                stale = {**selected, field: replacement}
                with self.assertRaises(WindowUnavailable) as caught:
                    self.api.capture(stale)
                self.assertEqual(caught.exception.state, "no_window")


if __name__ == "__main__":
    unittest.main()
