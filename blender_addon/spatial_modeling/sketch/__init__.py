"""Native CAD Sketcher adapter; imports Blender only when used by the host."""


def _adapter():
    from . import adapter
    return adapter


def apply(op, target_id, args):
    return _adapter().apply(op, target_id, args)


def snapshot():
    return _adapter().snapshot()


def snapshot_problems():
    return list(_adapter().snapshot_problems)


def find(sketch_id):
    return _adapter().find(sketch_id)


def is_sketch(obj):
    return bool(obj and getattr(obj, "type", None) == "CURVES"
                and obj.get("is_cad_sketch", False))


def is_internal(obj):
    return is_sketch(obj) or bool(obj.get("spatial_modeling_sketch_internal", False))


def linked(ids):
    return _adapter().linked(ids)


def dependency_status():
    return _adapter().dependency_status()
