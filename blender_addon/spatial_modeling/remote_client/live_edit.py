"""Direct editing from the Client's viewport (two-way editing). No Blender or network calls.

When the host allows Client edits, the mirror's objects become selectable, so the
Client user can grab (G), rotate (R), scale (S) and delete (X) them like any Blender
object. This module turns those local changes into ordinary edit requests:

- after a transform finishes, compare each object's local world transform with the
  host's record and send what differs as `object.move` / `object.rotate` /
  `object.scale` with absolute `to` args (one request in flight, as requests.py
  requires);
- an object deleted locally becomes `object.delete`;
- until the host has answered, the mirror keeps the local transform ("held") so the
  object does not jump back; a rejected or unknown outcome reverts it to the host's
  record, so the host scene stays the truth.
"""

import math

LOCATION_TOLERANCE = 1e-4  # meters (0.1 mm)
ROTATION_TOLERANCE = 1e-3  # radians
SCALE_TOLERANCE = 1e-4
FACTOR = (0.001, 1000)  # commands.py: args.to of object.scale
COORDINATE = (-1000, 1000)  # commands.py: meters
FAILED = {"rejected", "unknown", "missing", "dropped", "checked"}


def _angle(a, b):
    """Angle in radians between two [w, x, y, z] rotations (q and -q are equal)."""
    na = math.sqrt(sum(c * c for c in a)) or 1.0
    nb = math.sqrt(sum(c * c for c in b)) or 1.0
    dot = abs(sum(x * y for x, y in zip(a, b, strict=True))) / (na * nb)
    return 2 * math.acos(min(1.0, dot))


def _unit(q):
    n = math.sqrt(sum(c * c for c in q))
    q = [c / n for c in q]
    return [-c for c in q] if q[0] < 0 else q


def _fmt(values):
    return ", ".join(f"{v:g}" for v in values)


def changes(record, local, name):
    """(op, label, args) requests that make the host's `record` transform match `local`.

    Both are {"location": [m]*3, "rotation": [w, x, y, z], "scale": [f]*3}. Location
    first, then rotation, then scale: the host applies each about the object's origin.
    Raises ValueError when local is outside what the host accepts.
    """
    out = []
    loc, rot, scale = local["location"], local["rotation"], local["scale"]
    if max(abs(a - b) for a, b in zip(loc, record["location"], strict=True)) > LOCATION_TOLERANCE:
        if not all(COORDINATE[0] <= v <= COORDINATE[1] for v in loc):
            raise ValueError("That position is too far from the origin for the host")
        mm = [round(v * 1000, 1) for v in loc]
        out.append(("object.move", f"Move {name} to ({_fmt(mm)}) mm", {"to": list(loc)}))
    if _angle(rot, record["rotation"]) > ROTATION_TOLERANCE:
        out.append(("object.rotate", f"Rotate {name}", {"to": _unit(rot)}))
    if max(abs(a - b) for a, b in zip(scale, record["scale"], strict=True)) > SCALE_TOLERANCE:
        if not all(FACTOR[0] <= v <= FACTOR[1] for v in scale):
            raise ValueError("That scale is outside what the host accepts (0.001 to 1000)")
        out.append(("object.scale", f"Scale {name} to ({_fmt(round(v, 3) for v in scale)})",
                    {"to": list(scale)}))
    return out


def differing(records, locals_):
    """Object IDs whose local transform isn't the host's (any change, valid or not)."""
    out = set()
    for oid, transform in locals_.items():
        record = records.get(oid)
        if record is None:
            continue
        try:
            if changes(record["transform"], transform, ""):
                out.add(oid)
        except ValueError:
            out.add(oid)
    return out


class LiveEdits:
    """Which mirror objects hold a local change, and the request sent for each."""

    def __init__(self):
        self.held = set()  # object IDs whose local transform/deletion isn't on the host yet
        self.sent = {}  # request ID -> object ID
        self.wait_revision = {}  # object ID -> host revision its applied edit produced
        self.revert = set()  # object IDs to put back to the host's record
        self.error = ""  # last reason a local change couldn't be sent

    def reset(self):
        self.__init__()

    def settle(self, requests, revision):
        """Follow up sent requests. `requests` maps ID -> object with .state/.revision."""
        for rid, oid in list(self.sent.items()):
            request = requests.get(rid)
            if request is None:
                del self.sent[rid]
                continue
            if request.state == "applied":
                del self.sent[rid]
                if request.revision is not None and (revision is None or
                                                     revision < request.revision):
                    self.wait_revision[oid] = request.revision
            elif request.state in FAILED:
                del self.sent[rid]
                self.held.discard(oid)
                self.revert.add(oid)
                self.error = f"The host didn't take an edit ({request.code or request.state})"
        for oid, wanted in list(self.wait_revision.items()):
            if revision is not None and revision >= wanted:
                del self.wait_revision[oid]

    def busy(self, oid):
        """True while this object's last request or its scene.update is still on the way."""
        return oid in self.sent.values() or oid in self.wait_revision

    def next_request(self, records, locals_, deleted):
        """(object ID, op, label, args) to send now, or None. Updates `held`.

        records: object ID -> host record; locals_: object ID -> local transform for
        objects still present; deleted: object IDs removed locally.
        """
        chosen = None
        for oid in sorted(deleted):
            if oid not in records:
                self.held.discard(oid)
                continue
            self.held.add(oid)
            if chosen is None and not self.busy(oid):
                chosen = (oid, "object.delete", f"Delete {records[oid].get('name', oid)}", {})
        for oid in sorted(locals_):
            record = records.get(oid)
            if record is None:
                continue
            try:
                wanted = changes(record["transform"], locals_[oid], record.get("name", oid))
            except ValueError as e:
                self.error = str(e)
                self.held.discard(oid)
                self.revert.add(oid)
                continue
            if not wanted:
                if not self.busy(oid):
                    self.held.discard(oid)
                continue
            self.held.add(oid)
            if chosen is None and not self.busy(oid):
                chosen = (oid, *wanted[0])
        return chosen
