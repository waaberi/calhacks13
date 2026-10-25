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


def _local(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is None:
        raise ValueError("Invalid sketch entity or constraint ID")


def check_sketch(record, revision):
    if not isinstance(record, dict):
        raise TypeError("Sketch record must be an object")
    if (not isinstance(record.get("id"), str)
            or re.fullmatch("[0-9a-f]{32}", record["id"]) is None
            or not isinstance(record.get("name"), str) or not 1 <= len(record["name"]) <= 256
            or type(record.get("generation")) is not int
            or not 0 <= record["generation"] <= revision):
        raise ValueError("Invalid sketch identity or generation")
    plane = record["plane"]
    vector(plane["location"], 3, "sketch plane location")
    vector(plane["rotation"], 4, "sketch plane rotation")
    if abs(sum(x*x for x in plane["rotation"]) - 1) > .01:
        raise ValueError("Sketch plane rotation must be a unit quaternion")
    solver = record["solver"]
    dof = solver["dof"]
    if (solver["status"] not in ("free", "fully_constrained", "conflicting")
            or dof is not None and (type(dof) is not int or dof < 0)):
        raise ValueError("Invalid sketch solver status")
    entities, constraints = record["entities"], record["constraints"]
    if not isinstance(entities, list) or not isinstance(constraints, list):
        raise TypeError("Sketch entities and constraints must be lists")
    kinds = {}
    for entity in entities:
        eid, kind = entity["id"], entity["kind"]
        _local(eid)
        if eid in kinds or kind not in ("point", "line", "circle"):
            raise ValueError("Duplicate or unknown sketch entity")
        kinds[eid] = kind
        if kind == "point":
            vector(entity["at"], 2, "solved sketch point")
        if kind == "circle":
            radius = entity["radius"]
            if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
                raise ValueError("Invalid solved circle radius")
    for entity in entities:
        if entity["kind"] == "line":
            refs = entity["points"]
            if not isinstance(refs, list) or len(refs) != 2:
                raise ValueError("Line must reference two solved points")
        elif entity["kind"] == "circle":
            refs = [entity["center"]]
        else:
            continue
        if any(kinds.get(ref) != "point" for ref in refs):
            raise ValueError("Solved sketch point reference missing")
    seen = set()
    dimensional = {"distance", "diameter", "angle"}
    for constraint in constraints:
        cid, kind, refs = constraint["id"], constraint["kind"], constraint["entities"]
        _local(cid)
        if cid in seen or kind not in dimensional | {"fixed", "coincident", "horizontal", "vertical"}:
            raise ValueError("Duplicate or unknown sketch constraint")
        seen.add(cid)
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 2
                or any(ref not in kinds for ref in refs)):
            raise ValueError("Constraint entity reference missing")
        if kind in dimensional:
            value = constraint["value"]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid sketch driving dimension")
        elif "value" in constraint:
            raise ValueError("Nondimensional sketch constraint has a value")


class SceneState:
    """Accept complete ordered scenes atomically. A stale cache is never current."""

    def __init__(self):
        self.document = None
        self.objects = {}
        self.sketches = {}
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
        sketch_candidate = {} if snapshot else self.sketches.copy()
        for oid in payload.get("removed", []):
            if not isinstance(oid, str) or re.fullmatch("[0-9a-f]{32}", oid) is None:
                raise ValueError("Invalid removed scene ID")
            candidate.pop(oid, None)
            sketch_candidate.pop(oid, None)
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
        sketch_records = payload.get("sketches", [])
        if not isinstance(sketch_records, list):
            raise TypeError("Sketch records must be a list")
        for record in sketch_records:
            check_sketch(record, doc["revision"])
            sid = record["id"]
            if sid in seen or sid in candidate:
                raise ValueError("Duplicate sketch/object ID")
            seen.add(sid)
            if (not snapshot and sid in self.sketches
                    and record["generation"] < self.sketches[sid]["generation"]):
                raise ValueError("Sketch generation regressed")
            if (not snapshot and sid in self.sketches and record != self.sketches[sid]
                    and record["generation"] == self.sketches[sid]["generation"]):
                raise ValueError("Sketch changed without a new generation")
            sketch_candidate[sid] = copy.deepcopy(record)
        if candidate.keys() & sketch_candidate.keys():
            raise ValueError("Object and sketch IDs overlap")
        if any(o.get("parent") is not None and o["parent"] not in candidate
               for o in candidate.values()):
            raise ValueError("Object parent missing from scene")
        self.objects, self.sketches, self.document = candidate, sketch_candidate, doc
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
