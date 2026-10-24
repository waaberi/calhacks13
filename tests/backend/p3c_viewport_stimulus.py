"""Opt-in C smoke stimulus. Writes only the exact owned RegionView3D's view fields.

No operators, native data edits, selection, Undo, leases or capture configuration.
Control: output/viewport-control.json, increasing seq, frame/orbit/stop/restore.
"""

import json
import math
import os
import uuid


def control_request(raw, last_seq):
    """Closed, bounded control grammar; stale valid requests are consumed only once."""
    if len(raw) > 4096:
        raise ValueError("viewport control exceeds 4096 bytes")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("viewport control must be an object")
    seq, action = value.get("seq"), value.get("action")
    if type(seq) is not int or not 1 <= seq <= 2**31 - 1:
        raise ValueError("viewport seq must be an integer in 1..2147483647")
    fields = {"frame": {"seq", "action", "target"},
              "orbit": {"seq", "action", "duration_s"},
              "stop": {"seq", "action"}, "restore": {"seq", "action"}}
    if not isinstance(action, str) or action not in fields or set(value) - fields[action]:
        raise ValueError("unknown viewport action or fields")
    if action == "frame" and "target" in value:
        if not isinstance(value["target"], str):
            raise ValueError("viewport target must be a sketch UUID")
        uuid.UUID(value["target"])
    if action == "orbit":
        duration = value.get("duration_s")
        if (type(duration) not in (int, float) or not math.isfinite(duration)
                or not 4 <= duration <= 60 or duration % 4):
            raise ValueError("orbit duration_s must be 4..60 in complete four-second cycles")
    return value if seq > last_seq else None


def _pose(view):
    return {"location": list(view.view_location), "distance": float(view.view_distance),
            "rotation": list(view.view_rotation), "perspective": view.view_perspective}


def _delta(left, right):
    return {"location": max(abs(a - b) for a, b in zip(left["location"], right["location"])),
            "distance": abs(left["distance"] - right["distance"]),
            "rotation": max(abs(a - b) for a, b in zip(left["rotation"], right["rotation"])),
            "perspective_matches": left["perspective"] == right["perspective"]}


def drawable_bounds(record):
    """Only line/circle geometry counts; CAD's unconnected origin is not a frame."""
    points = {e["id"]: e["at"] for e in record["entities"] if e["kind"] == "point"}
    bounds = []
    for entity in record["entities"]:
        if entity["kind"] == "line":
            bounds.extend(points[pid] for pid in entity["points"])
        elif entity["kind"] == "circle":
            x, y = points[entity["center"]]
            radius = entity["radius"]
            bounds.extend(([x - radius, y - radius], [x + radius, y + radius]))
    if not bounds:
        return None
    lo = [min(p[i] for p in bounds) for i in (0, 1)]
    hi = [max(p[i] for p in bounds) for i in (0, 1)]
    if not all(math.isfinite(v) for v in (*lo, *hi)):
        raise ValueError("nonfinite authoritative sketch bounds")
    return lo, hi


class OwnedCadViewport:
    def __init__(self, output, allow_orbit=False):
        import bpy
        self.bpy = bpy
        windows = list(bpy.context.window_manager.windows)
        if len(windows) != 1:
            raise RuntimeError("C viewport requires exactly one owned factory-startup window")
        self.window = windows[0]
        areas = [area for area in self.window.screen.areas if area.type == "VIEW_3D"]
        if not areas:
            raise RuntimeError("owned window has no VIEW_3D")
        self.area = max(areas, key=lambda area: area.width * area.height)
        self.region = next(region for region in self.area.regions if region.type == "WINDOW")
        self.space = self.area.spaces.active
        self.view = self.space.region_3d
        self.identity = (self.window.as_pointer(), self.area.as_pointer(),
                         self.region.as_pointer(), self.space.as_pointer(), self.view.as_pointer())
        self.output, self.allow_orbit = output, allow_orbit
        self.original, self.framed = _pose(self.view), None
        self.target = self.last_applied = None
        self.pending, self.auto, self.pinned = True, True, False
        self.orbit, self.last_seq = None, 0
        self.report = {"status": "frame_pending", "pid": os.getpid(),
                       "owned_pointers": list(self.identity), "original": self.original,
                       "allow_orbit": allow_orbit, "events": [], "ticks": 0}
        self._owned()

    def _owned(self):
        # Replaced surfaces are an error; never find/rebind a different window or region.
        try:
            valid = (self.window in self.bpy.context.window_manager.windows[:]
                     and self.area in self.window.screen.areas[:]
                     and self.area.type == "VIEW_3D"
                     and self.region in self.area.regions[:]
                     and self.space == self.area.spaces.active
                     and self.identity == (self.window.as_pointer(), self.area.as_pointer(),
                         self.region.as_pointer(), self.space.as_pointer(), self.view.as_pointer()))
        except ReferenceError:
            valid = False
        if not valid:
            raise RuntimeError("owned C viewport was replaced or destroyed; refusing to rebind")
        self.report["region_rect"] = [self.region.x, self.region.y,
                                      self.region.width, self.region.height]

    def _event(self, action, now, **detail):
        self.report["events"].append({"action": action, "monotonic": now, **detail})
        # Bounded even during a long external smoke run.
        self.report["events"] = self.report["events"][-256:]

    def _write(self, pose):
        self._owned()
        self.view.view_location = pose["location"]
        self.view.view_distance = pose["distance"]
        self.view.view_rotation = pose["rotation"]
        self.view.view_perspective = pose["perspective"]
        self.area.tag_redraw()

    def observe_receipt(self, receipt):
        if receipt.get("outcome") != "applied" or not receipt.get("op", "").startswith("sketch."):
            return
        target = (next(iter(receipt.get("created", [])), None)
                  if receipt["op"] == "sketch.create" else receipt.get("target"))
        self.last_applied = target
        if self.auto and not self.pinned and target and target != self.target:
            self.target, self.pending = target, True

    def _frame(self, records, unit_scale, now):
        from mathutils import Quaternion, Vector
        if not self.target:
            return
        record = next((r for r in records if r["id"] == self.target), None)
        if record is None:
            self.report["status"] = "frame_pending"
            return
        bounds = drawable_bounds(record)
        if bounds is None:
            self.report["status"] = "frame_pending"
            return
        if not math.isfinite(unit_scale) or unit_scale <= 0:
            raise ValueError("C viewport requires a finite positive native Unit Scale")
        lo, hi = bounds
        center = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 0))
        plane = record["plane"]
        rotation = Quaternion(plane["rotation"]).normalized()
        location = (rotation @ center + Vector(plane["location"])) / unit_scale
        # Stable envelope: a 100->120 mm dimension edit never auto-reframes this target.
        width, height = max(.16, (hi[0] - lo[0]) * 1.4), max(.11, (hi[1] - lo[1]) * 1.4)
        aspect = self.region.width / max(1, self.region.height)
        distance = max(height, width / aspect) * max(self.space.lens / 32, 1) * 1.15
        self.framed = {"location": list(location), "distance": distance / unit_scale,
                       "rotation": list(rotation), "perspective": "ORTHO"}
        self._write(self.framed)
        self.pending = False
        self.report.update(status="framed", target=self.target, framed=self.framed,
                           frame_bounds_m=[lo, hi], envelope_m=[width, height],
                           unit_scale=unit_scale, lens_unchanged=float(self.space.lens))
        self._event("framed", now, target=self.target)

    def _stop(self, now, reason):
        if self.orbit is not None:
            self._event("orbit_stopped", now, reason=reason,
                        elapsed_s=now - self.orbit["start"], samples=self.orbit["samples"])
        self.orbit = None
        if self.framed is not None:
            self._write(self.framed)
            self.report.update(status="framed", framed_restore_delta=_delta(_pose(self.view),
                                                                            self.framed))

    def restore_original(self, now, reason="finish"):
        self.orbit, self.auto, self.pending = None, False, False
        self._write(self.original)
        delta = _delta(_pose(self.view), self.original)
        self.report.update(status="restored", original_restore_delta=delta)
        self._event("original_restored", now, reason=reason, delta=delta)
        return delta

    def tick(self, now, records, unit_scale):
        from mathutils import Quaternion
        self._owned()
        self.report["ticks"] += 1
        control = self.output / "viewport-control.json"
        if control.exists():
            if control.stat().st_size > 4096:
                raise ValueError("viewport control exceeds 4096 bytes")
            request = control_request(control.read_bytes(), self.last_seq)
            if request is not None:
                self.last_seq = request["seq"]
                self.report["last_seq"] = self.last_seq
                action = request["action"]
                self._event("control", now, request=request)
                if action == "restore":
                    self.restore_original(now, "control")
                elif action == "stop":
                    self._stop(now, "control")
                elif action == "frame":
                    self._stop(now, "frame control")
                    self.target = request.get("target", self.last_applied)
                    self.pinned = "target" in request
                    self.auto, self.pending = True, True
                elif action == "orbit":
                    if (not self.allow_orbit or not self.auto or self.framed is None or self.pending
                            or not any(r["id"] == self.target for r in records)):
                        raise ValueError("orbit requires opt-in and an already framed real sketch")
                    self.orbit = {"start": now, "duration": request["duration_s"], "samples": 0}
                    self._event("orbit_started", now, duration_s=request["duration_s"],
                                target=self.target)
        if self.auto and self.pending and self.orbit is None:
            self._frame(records, unit_scale, now)
        if self.orbit is not None:
            elapsed = now - self.orbit["start"]
            if elapsed >= self.orbit["duration"]:
                self._stop(now, "duration")
            else:
                phase = 2 * math.pi * elapsed / 4
                yaw, pitch = math.radians(15) * math.sin(phase), math.radians(8) * math.sin(phase)
                rotation = (Quaternion(self.framed["rotation"])
                            @ Quaternion((0, 1, 0), yaw) @ Quaternion((1, 0, 0), pitch)).normalized()
                pose = dict(self.framed, rotation=list(rotation))
                self._write(pose)
                self.orbit["samples"] += 1
                self.report.update(status="orbiting", orbit_elapsed_s=elapsed,
                                   orbit_samples=self.orbit["samples"], yaw_rad=yaw, pitch_rad=pitch)
        self.report["current"] = _pose(self.view)
