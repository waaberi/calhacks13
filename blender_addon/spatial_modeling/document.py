"""The document open in the host Blender: its identity, revision and units.

See "Identity, revisions and units" in contracts/README.md. host.py makes a new
Document whenever its server starts: after every file load or revert, and when
the add-on is enabled or switched to Host role. So each Document is one open
epoch, and its revision counter starts at 0.

The document ID lives in a custom property on every scene, so it is saved with
the .blend. It is read on first use rather than in __init__, because the add-on's
register() may not touch bpy.data. Writing it doesn't mark the file as changed;
store() runs again before every save, in case an Undo removed it.
"""

import re
import uuid

import bpy

ID_PROPERTY = "spatial_modeling_document_id"
_UUID = re.compile(r"[0-9a-f]{32}")
# The values envelope.schema.json allows; anything else is reported as the default.
_SYSTEMS = {"NONE", "METRIC", "IMPERIAL"}
_LENGTH_UNITS = {
    "ADAPTIVE", "KILOMETERS", "METERS", "CENTIMETERS", "MILLIMETERS", "MICROMETERS",
    "MILES", "FEET", "INCHES", "THOU",
}


def _scene():
    return bpy.context.scene or bpy.data.scenes[0]


def _stored_id():
    for scene in (_scene(), *bpy.data.scenes):
        value = scene.get(ID_PROPERTY)
        if isinstance(value, str) and _UUID.fullmatch(value):
            return value
    return None


def units(scene):
    """The scene's unit settings as `units` in envelope.schema.json. Display only."""
    settings = scene.unit_settings
    return {
        "system": settings.system if settings.system in _SYSTEMS else "NONE",
        "length_unit": settings.length_unit if settings.length_unit in _LENGTH_UNITS else "ADAPTIVE",
        "rotation_unit": "RADIANS" if settings.system_rotation == "RADIANS" else "DEGREES",
        "scale_length": float(f"{settings.scale_length:.7g}"),  # a float32: 0.001, not 0.0010000000475
    }


class Document:
    def __init__(self):
        self.open_epoch = uuid.uuid4().hex
        self.revision = 0  # P2: goes up with every accepted change
        self._id = None

    @property
    def id(self):
        if self._id is None:
            self._id = _stored_id() or uuid.uuid4().hex
            self.store()
        return self._id

    def store(self):
        """Write the ID into every local scene that lacks it, so the next save keeps it."""
        for scene in bpy.data.scenes:
            if scene.library is None and scene.get(ID_PROPERTY) != self.id:
                scene[ID_PROPERTY] = self.id

    def describe(self):
        """The `document` object that welcome and scene.snapshot carry."""
        return {
            "id": self.id,
            "open_epoch": self.open_epoch,
            "name": bpy.path.basename(bpy.data.filepath) or None,
            "revision": self.revision,
            "dirty": bpy.data.is_dirty,
            "units": units(_scene()),
        }
