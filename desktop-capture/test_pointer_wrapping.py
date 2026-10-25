"""Cursor-warp regression fakes only; these tests never send desktop input."""

import ctypes as C
import unittest
from ctypes import wintypes as W
from types import SimpleNamespace

from input_bridge import InputRejected, NativeInput, WindowsInput
import test_input_bridge as bridge_fixture
from test_input_bridge import FakeNative


class WarpingNative(FakeNative):
    def __init__(self):
        super().__init__()
        self.cursor = (400, 300)
        self.button = False
        self.numeric_value = 0
        self.warps = 0

    def send(self, events):
        super().send(events)
        for event in events:
            if event[0] == "button":
                self.button = event[2] == "down"
            elif event[0] in ("move", "move_delta"):
                if event[0] == "move":
                    target = event[1:3]
                else:
                    target = self.cursor[0] + event[1], self.cursor[1] + event[2]
                if self.button:
                    self.numeric_value += target[0] - self.cursor[0]
                    self.cursor = (400, 300)  # Native continuous-grab warp.
                    self.warps += 1
                else:
                    self.cursor = target


class PointerWrappingTests(unittest.TestCase):
    publish, event, dispatch, reject = (bridge_fixture.BridgeTests.publish, bridge_fixture.BridgeTests.event,
                                       bridge_fixture.BridgeTests.dispatch, bridge_fixture.BridgeTests.reject)

    def setUp(self):
        bridge_fixture.BridgeTests.setUp(self)
        self.native = WarpingNative()
        self.bridge.native = self.native

    def test_stationary_held_contact_and_release_do_not_reassert_absolute_cursor(self):
        self.dispatch("button", button="left", action="down", x=.8, y=.5)
        self.native.cursor = (400, 300)
        self.native.sent.clear()
        for _ in range(30):
            self.dispatch("pointer", x=.8, y=.5)
        self.assertEqual(self.native.numeric_value, 0)
        self.assertEqual(self.native.sent, [])
        self.dispatch("button", button="left", action="up", x=.8, y=.5)
        self.assertEqual(self.native.sent, [[("button", "left", "up")]])
        self.assertEqual(self.native.numeric_value, 0)

    def test_user_drag_deltas_continue_after_each_native_wrap_without_amplification(self):
        self.dispatch("button", button="left", action="down", x=.8, y=.5)
        self.native.cursor = (400, 300)
        for x in (.803, .806, .81):
            self.dispatch("pointer", x=x, y=.5)
            for _ in range(8):
                self.dispatch("pointer", x=x, y=.5)
        expected = round(.81 * 1607) - round(.8 * 1607)
        self.assertEqual(self.native.numeric_value, expected)
        self.assertEqual(self.native.warps, 3)
        self.dispatch("button", button="left", action="up", x=.81, y=.5)
        self.assertEqual(self.native.numeric_value, expected)
        self.dispatch("button", button="left", action="down", x=.2, y=.3)
        self.assertEqual(self.native.sent[-1][0], ("move", 421, 324))

    def test_release_cleanup_resets_intent_and_does_not_replay_motion(self):
        self.dispatch("button", button="left", action="down", x=.8, y=.5)
        self.native.cursor = (400, 300)
        self.dispatch("release")
        self.assertIsNone(self.bridge.pointer_intent)
        self.assertEqual(self.native.sent[-1], [("button", "left", "up")])
        self.dispatch("button", button="left", action="down", x=.2, y=.3)
        self.assertEqual(self.native.sent[-1][0], ("move", 421, 324))

    def test_occluded_requested_point_still_rejects_held_drag(self):
        self.dispatch("button", button="left", action="down", x=.8, y=.5)
        old_intent = self.bridge.pointer_intent
        self.native.occluded = True
        self.reject("selected_window_occluded_at_pointer", self.event("pointer", x=.81, y=.5))
        self.assertEqual(self.bridge.pointer_intent, old_intent)
        self.assertFalse(any(e[0] == "move_delta" for batch in self.native.sent for e in batch))


class WindowsPointerDeltaTests(unittest.TestCase):
    def adapter(self, visible=True, cursor_available=True):
        delivered = []

        def get_cursor(pointer):
            point = C.cast(pointer, C.POINTER(W.POINT)).contents
            point.x, point.y = 400, 300
            return cursor_available

        def send(count, array, size):
            self.assertEqual(size, C.sizeof(NativeInput))
            delivered.extend((r.mi.dx, r.mi.dy, r.mi.dwFlags) for r in array)
            return count

        native = WindowsInput.__new__(WindowsInput)
        native.u = SimpleNamespace(GetCursorPos=get_cursor, SendInput=send,
                                   GetSystemMetrics=lambda n: {76: -1920, 77: 0, 78: 3840, 79: 1080}[n])
        targets = []
        native.target_visible = lambda *point: targets.append(point) is None and visible
        return native, delivered, targets

    def test_delta_is_applied_to_actual_warped_cursor_with_exact_destination_guard(self):
        native, delivered, targets = self.adapter()
        native.send([("move_delta", 5, -2, 100)])
        self.assertEqual(targets, [(100, 405, 298)])
        self.assertEqual(delivered, [(round((405 + 1920) * 65535 / 3839), round(298 * 65535 / 1079), 0xC001)])

    def test_occluded_actual_destination_or_unreadable_cursor_sends_nothing(self):
        for visible, available, reason in [(False, True, "selected_window_occluded_at_drag_destination"),
                                           (True, False, "native_cursor_position_unavailable")]:
            native, delivered, _ = self.adapter(visible, available)
            with self.assertRaises(InputRejected) as caught:
                native.send([("move_delta", 5, -2, 100)])
            self.assertEqual(caught.exception.reason, reason)
            self.assertEqual(delivered, [])


if __name__ == "__main__":
    unittest.main()
