"""Spatial Modeling: edit this Blender project from VR and from a second Blender.

One add-on, two roles chosen in the add-on preferences:

- Host (Talia's PC) owns the document. It serves the Unity app on localhost and
  Client-role add-ons on the LAN, and applies every edit in Blender.
- Client (Lee Jae-yeon's PC) joins a host, mirrors its scene and sends edits
  as requests. Lives in remote_client/.

Sockets run on a background thread; every bpy call happens on the main thread
through bpy.app.timers. Never execute received data as Python.
"""

import bpy


class SpatialModelingPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    role: bpy.props.EnumProperty(
        name="Role",
        items=[
            ("HOST", "Host", "This Blender owns the shared document"),
            ("CLIENT", "Client", "Join a host on another computer"),
        ],
        default="HOST",
    )

    def draw(self, context):
        self.layout.prop(self, "role", expand=True)


def register():
    bpy.utils.register_class(SpatialModelingPreferences)


def unregister():
    bpy.utils.unregister_class(SpatialModelingPreferences)
