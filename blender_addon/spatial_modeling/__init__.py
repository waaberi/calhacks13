"""Spatial Modeling: edit this Blender project from VR and from a second Blender.

One add-on, two roles chosen in the add-on preferences:

- Host (Talia's PC) owns the document. It serves the Unity app on localhost and
  Client-role add-ons on the LAN, and applies every edit in Blender. Lives in
  host.py (lifecycle), server.py (networking, no bpy) and lan.py (the LAN
  port's session token and TLS, shared with the Client role). gate.py holds
  back the host desktop's own edits while someone else's lease covers them.
- Client (Lee Jae-yeon's PC) joins a host, mirrors its scene and sends edits
  as requests. Lives in remote_client/.

Sockets run on a background thread; every bpy call happens on the main thread
through bpy.app.timers. Never execute received data as Python.
"""

import bpy

from . import gate, host, lan, remote_client, remote_edit_ui, remote_test_ui


def _sync_roles(self, context):
    remote_client.disconnect()
    host.sync()


def _restart(self, context):
    host.restart()


class SpatialModelingPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    role: bpy.props.EnumProperty(
        name="Role",
        items=[
            ("HOST", "Host", "This Blender owns the shared document"),
            ("CLIENT", "Client", "Join a host on another computer"),
        ],
        default="HOST",
        update=_sync_roles,
    )
    lan_enabled: bpy.props.BoolProperty(
        name="Let a Client-role Blender join over the LAN",
        description=f"Listen on port {lan.PORT} for a second Blender with the session token",
        default=False,
        update=_restart,
    )
    lan_address: bpy.props.StringProperty(
        name="Listen on",
        description=(
            f"{lan.ALL_INTERFACES} listens on every network interface of this PC. "
            "Enter one of this PC's addresses to listen only there"
        ),
        default=lan.ALL_INTERFACES,
        update=_restart,
    )
    lan_security: bpy.props.EnumProperty(
        name="Security",
        items=[
            (
                "TLS",
                "TLS with the token",
                "Encrypted. Only a Blender with the session token completes the handshake",
            ),
            (
                "TOKEN",
                "Token only, no TLS",
                "Fallback if TLS fails: the token is sent in hello, unencrypted. Isolated routes only",
            ),
        ],
        default="TLS",
        update=_restart,
    )
    session_token: bpy.props.StringProperty(
        name="Session token",
        description=(
            "Give this to the Client-role user. Generated when the LAN port starts if empty. "
            "Kept in your Blender preferences, never in the project"
        ),
        update=_restart,
    )
    # The hosting session's ID (welcome.session_id), made on first start and kept with
    # the token so it survives restarts. Not secret, and not shown.
    session_id: bpy.props.StringProperty(name="Session ID")
    host_name: bpy.props.StringProperty(
        name="Your name",
        description="Shown to the others as the person at this Blender. Blank: Host Blender",
        maxlen=256,
        update=lambda self, context: host.rename(),
    )
    client_edits: bpy.props.BoolProperty(
        name="Let the Client role edit (test only)",
        description=(
            "Unfinished: lets a Client-role Blender send edit commands. Keep it off in "
            "normal use. Changing it disconnects everyone; they reconnect"
        ),
        default=False,
        update=_restart,
    )

    spacetime_where: bpy.props.EnumProperty(
        name="SpacetimeDB",
        items=(
            ("LOCAL", "This PC", "A SpacetimeDB server on this PC decides leases. Remote "
             "Blenders join over the LAN"),
            ("CLOUD", "Maincloud", "SpacetimeDB on Maincloud decides leases and carries "
             "remote Blenders' connections through the bridge, from any network "
             "(spacetime/README.md)"),
        ),
        default="LOCAL",
        update=_restart,
    )

    spacetime_url: bpy.props.StringProperty(
        name="Server",
        description=(
            "Server that gets a copy of the participants and leases, for the Unity app to "
            "subscribe to. Run it on this PC with `spacetime start --listen-addr "
            "127.0.0.1:3000`. Blank: don't use SpacetimeDB"
        ),
        default="http://127.0.0.1:3000",
        update=_restart,
    )

    spacetime_database: bpy.props.StringProperty(
        name="Database",
        description="The database the module is published as on this PC's server",
        default="spatial-modeling",
        update=_restart,
    )

    cloud_database: bpy.props.StringProperty(
        name="Database",
        description="The database the module is published as on Maincloud (names are global)",
        default="",
        update=_restart,
    )

    client_address: bpy.props.StringProperty(name="Host address", default="127.0.0.1")
    client_port: bpy.props.IntProperty(name="Host port", default=lan.PORT, min=1, max=65535)
    client_token: bpy.props.StringProperty(name="Session token", subtype="PASSWORD")
    client_tls: bpy.props.BoolProperty(name="Use TLS with the token", default=True)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "role", expand=True)
        if self.role != "HOST":
            layout.label(text="Read-only mirror — use a separate empty, unsaved session")
            layout.prop(self, "host_name")  # the name the host, VR and lease owners show
            layout.prop(self, "client_address")
            layout.prop(self, "client_port")
            layout.prop(self, "client_token")
            layout.prop(self, "client_tls")
            row = layout.row(align=True)
            row.operator(ConnectReadOnly.bl_idname)
            row.operator(DisconnectReadOnly.bl_idname)
            layout.label(text=remote_client.state.status,
                         icon="CHECKMARK" if remote_client.state.current else "ERROR")
            return
        layout.prop(self, "host_name")
        layout.label(text=f"VR app: {host.status}")
        for actor in host.participants():
            layout.label(text=f"Connected: {actor['name']} ({actor['role']})", icon="USER")
        layout.row().prop(self, "spacetime_where", expand=True)
        if self.spacetime_where == "CLOUD":
            layout.prop(self, "cloud_database")
            name = self.cloud_database.strip() or "<database>"
            layout.label(text=f"Remote Blenders: run `npm run bridge -- host --database {name}`")
        else:
            layout.prop(self, "spacetime_url")
            layout.prop(self, "spacetime_database")
        layout.label(text=host.spacetime_status())
        box = layout.box()
        box.prop(self, "lan_enabled")
        col = box.column()
        col.active = self.lan_enabled
        col.prop(self, "lan_address")
        col.row().prop(self, "lan_security", expand=True)
        row = col.row(align=True)
        row.prop(self, "session_token")
        row.operator(CopySessionToken.bl_idname, text="", icon="COPYDOWN")
        row.operator(NewSessionToken.bl_idname, text="", icon="FILE_REFRESH")
        col.prop(self, "client_edits")
        col.label(text=f"LAN: {host.lan_status}")
        if self.lan_security == "TOKEN":
            col.label(text="Without TLS anyone on the network can read the token.", icon="ERROR")


class CopySessionToken(bpy.types.Operator):
    """Copy the session token to the clipboard"""

    bl_idname = "spatial_modeling.copy_session_token"
    bl_label = "Copy Session Token"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        context.window_manager.clipboard = prefs.session_token
        self.report({"INFO"}, "Copied the session token")  # never the token itself
        return {"FINISHED"}


class NewSessionToken(bpy.types.Operator):
    """Make a new random session token. Connected clients are disconnected"""

    bl_idname = "spatial_modeling.new_session_token"
    bl_label = "New Session Token"

    def execute(self, context):
        context.preferences.addons[__package__].preferences.session_token = lan.new_token()
        return {"FINISHED"}


class ConnectReadOnly(bpy.types.Operator):
    """Join without sending edits. Never loads into a personal file"""

    bl_idname = "spatial_modeling.connect_readonly"
    bl_label = "Connect read-only"

    def execute(self, context):
        from .session import APP
        prefs = context.preferences.addons[__package__].preferences
        if prefs.role != "CLIENT":
            return {"CANCELLED"}
        try:
            lan.normalize_token(prefs.client_token)  # a short token: say so, don't retry silently
            remote_client.connect(prefs.client_address, prefs.client_token, APP["version"],
                                  prefs.host_name or "Blender viewer", prefs.client_port,
                                  prefs.client_tls)
        except (ValueError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class DisconnectReadOnly(bpy.types.Operator):
    """Stop the connection and remove only this mirror's owned data"""

    bl_idname = "spatial_modeling.disconnect_readonly"
    bl_label = "Disconnect"

    def execute(self, context):
        remote_client.disconnect()
        return {"FINISHED"}


CLASSES = (SpatialModelingPreferences, CopySessionToken, NewSessionToken,
           ConnectReadOnly, DisconnectReadOnly)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    host.register()
    gate.register()
    remote_client.register()
    remote_test_ui.register()
    remote_edit_ui.register()
    from . import ownership
    ownership.register()


def unregister():
    from . import ownership
    ownership.unregister()
    remote_edit_ui.unregister()
    remote_test_ui.unregister()
    remote_client.unregister()
    gate.unregister()
    host.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
