"""sync._fit without Blender: which meshes a payload over the line limit sends as null.

sync.py imports bpy and the add-on's bpy modules at the top; stand-ins take
their place while it loads, so this runs in CI. Only _fit is exercised here;
test_scene.py checks the same path in real Blender.
"""

import copy
import importlib.util
import json
import random
import sys
import types
from pathlib import Path
from unittest import mock

import protocol
import pytest

SYNC = Path(__file__).resolve().parents[2] / "blender_addon" / "spatial_modeling" / "sync.py"


class _Stub(types.ModuleType):
    """A module with every attribute: bpy.app.handlers' lists and the add-on's other modules."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return []


@pytest.fixture(scope="module")
def sync():
    handlers = _Stub("bpy.app.handlers")
    handlers.persistent = lambda function: function
    app = _Stub("bpy.app")
    app.handlers = handlers
    bpy = _Stub("bpy")
    bpy.app = app
    package = _Stub("_sync_without_blender")
    package.protocol = protocol
    spec = importlib.util.spec_from_file_location(f"{package.__name__}.sync", SYNC)
    module = importlib.util.module_from_spec(spec)
    stubs = {"bpy": bpy, "bpy.app": app, "bpy.app.handlers": handlers, package.__name__: package}
    with mock.patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


def fit_by_reencoding(sync, payload):
    """_fit as it was: it encoded the whole payload again after each mesh it nulled."""
    objects = payload["objects"]
    if sync._estimate(objects) <= sync.FIT_BYTES:
        return payload
    while sync._size(payload) > sync.FIT_BYTES:
        meshes = [o for o in objects if o.get("mesh")]
        if not meshes:
            break
        biggest = max(meshes, key=lambda o: len(o["mesh"]["positions"]) + len(o["mesh"]["indices"]))
        print(f"Spatial Modeling: {biggest['name']}'s mesh ({len(biggest['mesh']['indices']) // 3} "
              "triangles) is too large to send; clients get it without a mesh")
        biggest["mesh"] = None
    return payload


def payload(seed, count, update):
    """A scene.snapshot (or scene.update) payload with varied meshes and names."""
    rng = random.Random(seed)
    objects = []
    for i in range(count):
        obj = {"id": f"{i:032x}", "name": rng.choice(["Cube", "Würfel", "立方体"]) + f".{i:03}",
               "type": "MESH", "parent": None, "generation": i, "visible": True,
               "transform": {"location": [i, 0, 0]}, "color": [1, 1, 1, 1]}
        kind = rng.random()
        if kind < 0.1:
            obj["mesh"] = None  # a camera, an empty...
        elif not (update and kind < 0.2):  # an update leaves out a mesh that didn't change
            # Few distinct triangle counts, so meshes tie on _fit's measure of size while
            # their JSON differs in length (2 or 6 decimals).
            vertices, decimals = 3 * rng.choice([1, 4, 4, 9, 30]), rng.choice([2, 6])
            obj["mesh"] = {
                "positions": [round(rng.uniform(-9, 9), decimals) for _ in range(3 * vertices)],
                "normals": [round(rng.uniform(-1, 1), 6) for _ in range(3 * vertices)],
                "indices": list(range(vertices)),
            }
        objects.append(obj)
    out = {"document": {"name": "Ünïcode.blend", "revision": 3}, "objects": objects,
           "sketches": []}
    if update:
        out["removed"] = []
    return out


@pytest.mark.parametrize("update", [False, True], ids=["snapshot", "update"])
@pytest.mark.parametrize("seed", range(4))
def test_the_same_meshes_are_sent_as_null_as_before(sync, monkeypatch, capsys, seed, update):
    original = payload(seed, 14, update)
    real_size, sizes = sync._size, []

    def measure(value):
        sizes.append(real_size(value))
        return sizes[-1]

    monkeypatch.setattr(sync, "_size", measure)
    monkeypatch.setattr(sync, "FIT_BYTES", 0)
    fit_by_reencoding(sync, copy.deepcopy(original))  # every size the old loop went through
    monkeypatch.setattr(sync, "_size", real_size)
    capsys.readouterr()
    # Each limit at which another mesh must go, exactly and one byte under; 0 fits nothing.
    for limit in sorted({0, 10**9, *sizes, *(s - 1 for s in sizes)}):
        monkeypatch.setattr(sync, "FIT_BYTES", limit)
        expected = fit_by_reencoding(sync, copy.deepcopy(original))
        expected_out = capsys.readouterr().out
        assert sync._fit(copy.deepcopy(original)) == expected, limit
        assert capsys.readouterr().out == expected_out, limit


def test_each_mesh_is_encoded_once(sync, monkeypatch, capsys):
    """The old loop encoded the whole payload after each null: minutes for 200 objects."""
    original = payload(7, 60, update=False)
    full = sync._size(original)
    meshes = sum(1 for o in original["objects"] if o.get("mesh"))
    monkeypatch.setattr(sync, "FIT_BYTES", full // 4)  # most meshes must go
    encoded, real_dumps = [], json.dumps

    def dumps(value, **kwargs):
        text = real_dumps(value, **kwargs)
        encoded.append(len(text))
        return text

    monkeypatch.setattr(json, "dumps", dumps)
    result = sync._fit(copy.deepcopy(original))
    work = list(encoded)
    nulled = sum(1 for a, b in zip(original["objects"], result["objects"])
                 if a.get("mesh") and b["mesh"] is None)
    assert nulled >= 30 and sync._size(result) <= sync.FIT_BYTES
    assert len(work) <= meshes + 1 and sum(work) < 1.1 * full, (len(work), sum(work), full)

    encoded.clear()
    fit_by_reencoding(sync, copy.deepcopy(original))
    assert sum(encoded) > 10 * sum(work)  # what the old loop encoded for the same result
    capsys.readouterr()
