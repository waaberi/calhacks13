"""Just enough of bpy/mathutils to drive remote_client + mirror outside Blender."""
import sys
import types


class Vector(list):
    pass


class Quaternion(list):
    def __init__(self, q):
        super().__init__(q)

    w = property(lambda s: s[0])
    x = property(lambda s: s[1])
    y = property(lambda s: s[2])
    z = property(lambda s: s[3])


class Matrix:
    def __init__(self, loc, rot, scale):
        self.parts = (Vector(loc), Quaternion(rot), Vector(scale))

    @classmethod
    def LocRotScale(cls, loc, rot, scale):
        return cls(loc, rot, scale)

    def decompose(self):
        loc, rot, scale = self.parts
        return Vector(loc), Quaternion(rot), Vector(scale)


class ID:
    _dead = False

    def __init__(self, name):
        object.__setattr__(self, "_props", {})
        object.__setattr__(self, "_name", name)

    def __getattribute__(self, key):
        if not key.startswith("_") and object.__getattribute__(self, "_dead"):
            raise ReferenceError("StructRNA has been removed")
        return object.__getattribute__(self, key)

    name = property(lambda s: s._name, lambda s, v: object.__setattr__(s, "_name", v))

    def __setitem__(self, k, v):
        self._props[k] = v

    def __getitem__(self, k):
        return self._props[k]

    def get(self, k, d=None):
        return self._props.get(k, d)


class Mesh(ID):
    def __init__(self, name):
        super().__init__(name)
        self.materials = []
        self.users = 1

    def clear_geometry(self):
        pass

    def from_pydata(self, *a):
        pass

    def update(self):
        pass

    def normals_split_custom_set_from_vertices(self, n):
        pass


class Node:
    def __init__(self):
        self.inputs = {"Base Color": types.SimpleNamespace(default_value=None)}


class Material(ID):
    def __init__(self, name):
        super().__init__(name)
        self.users = 1
        self.node_tree = types.SimpleNamespace(nodes={"Principled BSDF": Node()})


class Object(ID):
    def __init__(self, name, data):
        super().__init__(name)
        self.data = data
        self.type = "MESH" if data is not None else "EMPTY"
        self.matrix_world = Matrix([0, 0, 0], [1, 0, 0, 0], [1, 1, 1])
        self._selected = False
        self.hide_select = False

    def select_set(self, v):
        self._selected = v

    def select_get(self):
        return self._selected


class Collection(ID):
    def __init__(self, name):
        super().__init__(name)
        self.objects = types.SimpleNamespace(link=lambda o: None)
        self.hide_select = False


class Bucket(list):
    def __init__(self, factory):
        super().__init__()
        self.factory = factory

    def new(self, *a):
        item = self.factory(*a)
        self.append(item)
        return item

    def remove(self, item, do_unlink=False):
        list.remove(self, item)
        object.__setattr__(item, "_dead", True)

    def __contains__(self, name):
        return any(not i._dead and i.name == name for i in self)


def install():
    bpy = types.ModuleType("bpy")
    data = types.SimpleNamespace(filepath="", objects=Bucket(Object), meshes=Bucket(Mesh),
                                 materials=Bucket(Material), collections=Bucket(Collection),
                                 curves=Bucket(Mesh))
    bpy.data = data
    window = types.SimpleNamespace(modal_operators=[], screen=types.SimpleNamespace(areas=[]))
    bpy.context = types.SimpleNamespace(
        scene=types.SimpleNamespace(collection=types.SimpleNamespace(
            children=types.SimpleNamespace(link=lambda c: None)),
            unit_settings=types.SimpleNamespace(system="", scale_length=1)),
        window_manager=types.SimpleNamespace(windows=[window]),
        preferences=types.SimpleNamespace(addons={}))
    timers = set()
    bpy.app = types.SimpleNamespace(timers=types.SimpleNamespace(
        is_registered=lambda f: f in timers, register=lambda f, **k: timers.add(f),
        unregister=lambda f: timers.discard(f)), handlers=types.SimpleNamespace(load_pre=[]))
    bpy.types = types.SimpleNamespace()
    mu = types.ModuleType("mathutils")
    mu.Matrix, mu.Vector, mu.Quaternion = Matrix, Vector, Quaternion
    sys.modules["bpy"], sys.modules["mathutils"] = bpy, mu
    return bpy, window


def user_delete(bpy, obj):
    """What X does: the object is removed and every Python reference dies."""
    bpy.data.objects.remove(obj, do_unlink=True)
