"""Client viewport editing end to end: fake Blender + fake host, real remote_client code.

Run: python tests/backend/live_edit_flow_check.py (exits 1 on any failure).
"""
import copy
import math
import queue
import sys
import types
import uuid
from pathlib import Path

import live_edit_fakebpy as fakebpy

ADDON = Path(__file__).resolve().parents[2] / "blender_addon/spatial_modeling"
bpy, window = fakebpy.install()
pkg = types.ModuleType("spatial_modeling")
pkg.__path__ = [str(ADDON)]
sys.modules["spatial_modeling"] = pkg
stub = types.ModuleType("spatial_modeling.remote_test_ui")
stub.cancel_before_send = lambda: None
sys.modules["spatial_modeling.remote_test_ui"] = stub
pkg.remote_test_ui = stub
import spatial_modeling.remote_client as rc
from spatial_modeling.remote_client.mirror import Mirror

DOC = {"id": uuid.uuid4().hex, "open_epoch": uuid.uuid4().hex, "name": "t.blend", "revision": 1,
       "dirty": False, "units": {"system": "METRIC", "length_unit": "MILLIMETERS",
                                 "rotation_unit": "DEGREES", "scale_length": 0.001}}
CUBE = {"positions": [0, 0, 0, 1, 0, 0, 0, 1, 0], "indices": [0, 1, 2]}


def obj(name):
    return {"id": uuid.uuid4().hex, "name": name, "type": "MESH", "parent": None, "generation": 1,
            "visible": True, "transform": {"location": [0, 0, 0], "rotation": [1, 0, 0, 0],
                                           "scale": [1, 1, 1]},
            "color": [.8, .8, .8, 1], "mesh": CUBE}


class Host:
    def __init__(self):
        self.doc = copy.deepcopy(DOC)
        self.objects = {o["id"]: o for o in (obj("Cube"), obj("Cube.001"))}
        self.reject_next = None
        self.log = []

    def snapshot(self):
        return {"document": dict(self.doc), "objects": list(copy.deepcopy(self.objects).values()),
                "sketches": []}

    def bump(self, changed=(), removed=()):
        self.doc["revision"] += 1
        return {"document": dict(self.doc), "removed": list(removed), "sketches": [],
                "objects": [{k: v for k, v in copy.deepcopy(self.objects[i]).items() if k != "mesh"}
                            for i in changed]}

    def handle(self, msg, events):
        p = msg["payload"]
        self.log.append((p["op"], p.get("args")))
        oid = p.get("target", {}).get("id")
        if self.reject_next or (oid and self.objects[oid]["generation"] != p["target"]["generation"]):
            code = self.reject_next or "stale_revision"
            self.reject_next = None
            events.put(("result", {"request_id": msg["id"], "outcome": "rejected",
                                   "revision": self.doc["revision"], "error": {"code": code}}))
            return
        rec = self.objects.get(oid)
        if p["op"] == "object.delete":
            del self.objects[oid]
            update = self.bump(removed=[oid])
        else:
            key = {"object.move": "location", "object.rotate": "rotation",
                   "object.scale": "scale"}[p["op"]]
            rec["transform"][key] = list(p["args"]["to"])
            rec["generation"] += 1
            update = self.bump(changed=[oid])
        events.put(("scene.update", update))
        events.put(("result", {"request_id": msg["id"], "outcome": "applied",
                               "revision": self.doc["revision"]}))

    def move_itself(self, oid, loc, events):
        self.objects[oid]["transform"]["location"] = loc
        self.objects[oid]["generation"] += 1
        events.put(("scene.update", self.bump(changed=[oid])))


class Link:
    def __init__(self, host):
        self.host, self.events, self.healthy = host, queue.Queue(), True
        self.thread = types.SimpleNamespace(is_alive=lambda: True)

    def send(self, msg):
        if msg["type"] == "command":
            self.host.handle(msg, self.events)
        return True

    def stop(self):
        self.healthy = False


def welcome(host, can_edit=True):
    return {"session_id": uuid.uuid4().hex, "host_epoch": uuid.uuid4().hex,
            "actor_id": uuid.uuid4().hex, "can_edit": can_edit,
            "document": {k: host.doc[k] for k in ("id", "open_epoch", "name", "revision")}}


def run(n=10):
    for _ in range(n):
        rc.poll()


def local(o):
    loc, rot, scale = o.matrix_world.decompose()
    return list(loc), list(rot), list(scale)


def set_local(o, loc=None, rot=None, scale=None):
    l, r, s = local(o)
    o.matrix_world = fakebpy.Matrix(loc or l, rot or r, scale or s)


def close(a, b):
    return all(math.isclose(x, y, abs_tol=1e-9) for x, y in zip(a, b, strict=True))


def connect(host, can_edit=True):
    rc.disconnect()
    rc._mirror = Mirror()
    rc.state = rc.SceneState()
    rc.requests = rc.RequestTracker()
    rc.live.reset()
    rc._link = Link(host)
    rc._link.events.put(("welcome", welcome(host, can_edit)))
    rc._link.events.put(("scene.snapshot", host.snapshot()))
    run(2)


checks = []


def check(name, ok):
    checks.append((name, ok))
    print("PASS" if ok else "FAIL", name)


host = Host()
a_id, b_id = list(host.objects)
connect(host)
mirror = rc._mirror
A, B = mirror.objects[a_id], mirror.objects[b_id]
check("objects selectable when host allows edits", not A.hide_select and mirror.editable)
check("state current after snapshot", rc.state.current and rc.edit_blocked() is None)

# 1. Drag A with G: nothing is sent mid-drag, and a host update to B doesn't snap A back.
A.select_set(True)
window.modal_operators = [types.SimpleNamespace(bl_idname="TRANSFORM_OT_translate")]
set_local(A, loc=[.1, .2, 0])
host.move_itself(b_id, [0, 0, .5], rc._link.events)
run(5)
check("nothing sent while dragging", host.log == [])
check("dragged object not snapped back by another update", close(local(A)[0], [.1, .2, 0]))
check("other object follows host", close(local(B)[0], [0, 0, .5]))
window.modal_operators = []
run(10)
check("move sent after drag ends", host.log == [("object.move", {"to": [.1, .2, 0]})])
check("host has new location", close(host.objects[a_id]["transform"]["location"], [.1, .2, 0]))
check("local kept, nothing held", close(local(A)[0], [.1, .2, 0]) and not rc.live.held)

# 2. Rotate + scale in one go: two requests, one after the other.
host.log.clear()
half = math.sqrt(.5)
set_local(A, rot=[half, 0, 0, half], scale=[2, 2, 2])
run(20)
check("rotate then scale sent", [op for op, _ in host.log] == ["object.rotate", "object.scale"])
check("host rotation+scale updated",
      close(host.objects[a_id]["transform"]["rotation"], [half, 0, 0, half])
      and close(host.objects[a_id]["transform"]["scale"], [2, 2, 2]))
check("no resend loop", len(host.log) == 2)

# 3. Rejected edit snaps back to the host's version.
host.log.clear()
host.reject_next = "lease_conflict"
set_local(B, loc=[1, 1, 1])
run(10)
check("rejected move reverted locally", close(local(B)[0], [0, 0, .5]))
check("error shown", "lease_conflict" in rc.live.error)
check("only one attempt", len(host.log) == 1)
run(10)
check("edits possible again", rc.edit_blocked() is None and not rc.live.held)

# 4. Delete with X.
host.log.clear()
fakebpy.user_delete(bpy, B)
run(10)
check("delete sent", host.log == [("object.delete", {})])
check("host removed it", b_id not in host.objects)
check("mirror forgot it", b_id not in mirror.objects)

# 5. Host-side move of A while client idle: mirror follows.
host.move_itself(a_id, [0, 0, 0], rc._link.events)
run(5)
check("client follows host move", close(local(A)[0], [0, 0, 0]))
check("follow didn't trigger a request", host.log == [("object.delete", {})])

# 6. Host does not allow Client edits: not selectable; a forced local change is undone.
host2 = Host()
connect(host2, can_edit=False)
m2 = rc._mirror
X = next(iter(m2.objects.values()))
check("not selectable without permission", X.hide_select and not m2.editable)
set_local(X, loc=[3, 3, 3])
run(5)
check("nothing sent without permission", host2.log == [])

# 7. Locally deleted while edits not allowed: recreated from host.
host3 = Host()
connect(host3, can_edit=True)
m3 = rc._mirror
oid = next(iter(m3.objects))
rc._can_edit = False  # e.g. host revoked
fakebpy.user_delete(bpy, m3.objects[oid])
run(5)
check("recreated after local delete without permission",
      oid in m3.objects and not m3.objects[oid]._dead)

# 8. Both edit the same object: host moves it first, client's later move still wins cleanly.
host4 = Host()
connect(host4, can_edit=True)
m4 = rc._mirror
oid4 = next(iter(m4.objects)); O4 = m4.objects[oid4]
O4.select_set(True)
window.modal_operators = [types.SimpleNamespace(bl_idname="TRANSFORM_OT_translate")]
set_local(O4, loc=[.3, 0, 0])
host4.move_itself(oid4, [0, .7, 0], rc._link.events)
run(3)
window.modal_operators = []
run(10)
check("concurrent: client's move applied last",
      close(host4.objects[oid4]["transform"]["location"], [.3, 0, 0]) and not rc.live.held)

# 9. Connection drops with a local change pending: host version comes back.
host5 = Host()
connect(host5, can_edit=True)
m5 = rc._mirror
oid5 = next(iter(m5.objects)); O5 = m5.objects[oid5]
rc._link.healthy = False
set_local(O5, loc=[9, 9, 9])
run(3)
check("disconnected: nothing sent", host5.log == [])
check("disconnected: local change put back", close(local(O5)[0], [0, 0, 0]))
check("disconnected: not selectable", O5.hide_select)

print(f"\n{sum(ok for _, ok in checks)}/{len(checks)} passed")
sys.exit(0 if all(ok for _, ok in checks) else 1)
