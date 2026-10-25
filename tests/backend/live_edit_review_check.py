"""Independent lifecycle regressions using production Client and the existing fake host.

This intentionally exercises incoming-update ordering and native-cancel semantics;
real Blender/operator context is checked separately by the disposable native gate.
"""
import copy
import runpy
import sys
from pathlib import Path

old_exit = sys.exit
sys.exit = lambda code=0: None if code == 0 else (_ for _ in ()).throw(RuntimeError(code))
try:
    g = runpy.run_path(str(Path(__file__).with_name("live_edit_flow_check.py")))
finally:
    sys.exit = old_exit

rc, Host, connect, run = (g[k] for k in ("rc", "Host", "connect", "run"))
set_local, local, close = (g[k] for k in ("set_local", "local", "close"))
fakebpy, bpy, window = (g[k] for k in ("fakebpy", "bpy", "window"))
types = g["types"]
checks = []


def check(label, ok):
    checks.append((label, ok))
    print("REVIEW_PASS" if ok else "REVIEW_FAIL", label)


def fresh():
    window.modal_operators = []
    host = Host()
    connect(host)
    a, b = list(host.objects)
    return host, a, b, rc._mirror.objects[a]


# A native transform can finish before the 20ms timer sees it. An unrelated
# scene.update already in the queue must not erase the completed local action.
host, a, b, obj = fresh()
set_local(obj, loc=[.125, .25, 0])
host.move_itself(b, [0, 0, .75], rc._link.events)
run(8)
check("finished transform survives incoming unrelated update",
      close(host.objects[a]["transform"]["location"], [.125, .25, 0])
      and len(host.log) == 1)

# Deletion is also a native action that can precede its detector timer.
host, a, b, obj = fresh()
fakebpy.user_delete(bpy, obj)
host.move_itself(b, [0, 0, .75], rc._link.events)
run(8)
check("local delete survives incoming unrelated update",
      a not in host.objects and host.log == [("object.delete", {})])

# Opening another host document must never replay an unsent old-document value,
# even when native IDs are retained (normal when a .blend is reopened).
host, a, b, obj = fresh()
set_local(obj, loc=[8, 0, 0])
rc.live.held.add(a)
other = copy.deepcopy(host.snapshot())
other["document"]["open_epoch"] = "e" * 32
other["objects"][0]["transform"]["location"] = [0, 0, .9]
rc._link.events.put(("scene.snapshot", other))
run(3)
check("new document discards old unsent transform",
      close(local(rc._mirror.objects[a])[0], [0, 0, .9]) and not host.log)

# Escape restores the transform's starting value. If a host edit arrived during
# that drag, cancellation must adopt it rather than submit the old starting value.
host, a, b, obj = fresh()
obj.select_set(True)
window.modal_operators = [types.SimpleNamespace(bl_idname="TRANSFORM_OT_translate")]
run(1)
set_local(obj, loc=[.4, 0, 0])
host.move_itself(a, [0, .7, 0], rc._link.events)
run(2)
set_local(obj, loc=[0, 0, 0])  # Blender native Escape/RMB rollback.
window.modal_operators = []
run(8)
check("cancel after concurrent host edit never sends an edit",
      not host.log and close(local(obj)[0], [0, .7, 0])
      and close(host.objects[a]["transform"]["location"], [0, .7, 0]))

# An uncertain result must put back the host scene once, block, and never retry.
host, a, b, obj = fresh()
sent = []
original_send = rc._link.send


def hold_send(message):
    if message["type"] == "command":
        sent.append(message)
        return True
    return original_send(message)


rc._link.send = hold_send
set_local(obj, loc=[.3, 0, 0])
run(1)
assert len(sent) == 1
rc._link.events.put(("result", {"request_id": sent[0]["id"], "outcome": "unknown",
                                 "revision": host.doc["revision"]}))
run(10)
check("unknown outcome restores and blocks without replay",
      len(sent) == 1 and close(local(obj)[0], [0, 0, 0])
      and "unknown" in rc.edit_blocked().lower())

rc.disconnect()
print(f"{sum(ok for _, ok in checks)}/{len(checks)} independent review checks passed")
sys.exit(0 if all(ok for _, ok in checks) else 1)
