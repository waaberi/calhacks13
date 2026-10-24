"""The scene as the wire describes it: scene.snapshot now, scene.update in P2.

See "Scene" in contracts/README.md. P2-W-1 fills this module in. Until then the
snapshot lists no objects and no sketches. That is a valid scene.snapshot for
the right document, and contracts/README.md says that P1 hosts send it, so
clients know an empty scene from a P1 host means "not serialized yet".
"""


def snapshot(document):
    """Return the scene.snapshot payload for `document`, the open document's description.

    Called on Blender's main thread right after each welcome, so it may read bpy
    data. P2-W-1: fill `objects` with every object (stable ID, transform, color
    and evaluated mesh, see scene.snapshot.schema.json) and `sketches` with the
    CAD Sketcher sketches from the sketch/ adapter.
    """
    return {"document": document, "objects": [], "sketches": []}
