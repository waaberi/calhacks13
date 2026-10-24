"""Read-only scene cache and semantic checks; no Blender or network calls."""

import copy
import math
import re
import time


def vector(value, size, field):
    if (not isinstance(value, list) or len(value) != size
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)):
        raise ValueError(f"Invalid {field}")


def check_object(obj):
    if not isinstance(obj.get("id"), str) or not re.fullmatch("[0-9a-f]{32}", obj["id"]):
        raise ValueError("Object has no ID")
    if type(obj.get("generation")) is not int or obj["generation"] < 0:
        raise ValueError("Invalid object generation")
    transform = obj["transform"]
    for field, size in (("location", 3), ("rotation", 4), ("scale", 3)):
        vector(transform[field], size, field)
    if abs(sum(x*x for x in transform["rotation"]) - 1) > 0.01:
        raise ValueError("Rotation must be a unit quaternion")
    if obj.get("color") is not None:
        vector(obj["color"], 4, "color")
    mesh = obj.get("mesh")
    if mesh is not None:
        pos, idx = mesh["positions"], mesh["indices"]
        vector(pos, len(pos), "positions")
        if len(pos) % 3 or len(idx) % 3:
            raise ValueError("Incomplete mesh triangle or vertex")
        if any(type(i) is not int or not 0 <= i < len(pos)//3 for i in idx):
            raise ValueError("Mesh index out of range")
        if mesh.get("normals") is not None:
            vector(mesh["normals"], len(pos), "normals")


class SceneState:
    """Accept complete ordered scenes atomically. A stale cache is never current."""

    def __init__(self):
        self.document = None
        self.objects = {}
        self.current = False
        self.status = "Disconnected — read-only"
        self.last_message = 0

    def stale(self, reason="Disconnected — last scene is stale"):
        self.current = False
        self.status = reason

    def receive(self, payload, snapshot):
        doc = copy.deepcopy(payload["document"])
        if not all(isinstance(doc.get(k), str) and re.fullmatch("[0-9a-f]{32}", doc[k])
                   for k in ("id", "open_epoch")):
            raise ValueError("Document identity missing")
        if type(doc.get("revision")) is not int or doc["revision"] < 0:
            raise ValueError("Invalid scene revision")
        units = doc["units"]
        if type(units.get("scale_length")) not in (int, float) or not (
                math.isfinite(units["scale_length"]) and units["scale_length"] > 0):
            raise ValueError("Invalid unit scale")
        if not snapshot:
            if not self.current or self.document is None:
                raise ValueError("Update before a fresh snapshot")
            if any(doc[k] != self.document[k] for k in ("id", "open_epoch")):
                raise ValueError("Update belongs to a different document")
            # Save/dirty updates legitimately retain the same revision.
            if not self.document["revision"] <= doc["revision"] <= self.document["revision"] + 1:
                raise ValueError("Scene revision gap; reconnect for a fresh snapshot")
        # Accepted records are immutable. Copy the mapping, not every unchanged
        # mesh's large arrays on each transform-only update.
        candidate = {} if snapshot else self.objects.copy()
        for oid in payload.get("removed", []):
            candidate.pop(oid, None)
        seen = set()
        for item in payload["objects"]:
            check_object(item)
            oid = item["id"]
            if oid in seen:
                raise ValueError("Duplicate object ID")
            seen.add(oid)
            obj = copy.deepcopy(item)
            if "mesh" not in obj:
                if oid not in candidate:
                    raise ValueError("New object has no mesh field")
                obj["mesh"] = candidate[oid].get("mesh")
            candidate[oid] = obj
        if any(o.get("parent") is not None and o["parent"] not in candidate
               for o in candidate.values()):
            raise ValueError("Object parent missing from scene")
        self.objects, self.document = candidate, doc
        self.current = True
        self.last_message = time.monotonic()
        self.status = f"Connected — {doc.get('name', '')}, revision {doc['revision']} — read-only"

    def check_reference(self, expected, tolerance=1e-6):
        """Check known IDs/world positions in meters against an independent oracle."""
        if not self.current:
            raise ValueError("Cannot verify a stale scene")
        for oid, location in expected.items():
            actual = self.objects[oid]["transform"]["location"]
            if any(abs(a-b) > tolerance for a, b in zip(actual, location, strict=True)):
                raise ValueError(f"Position mismatch for {oid}")
        return {"objects": len(self.objects), "revision": self.document["revision"],
                "wire_units": "meters", "scale_length": self.document["units"]["scale_length"]}
