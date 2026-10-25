"""Native Client edit-turn controls; ordinary Blender keeps all modeling tools."""
import bpy


def _client():
    from .. import remote_client
    return remote_client.native_client if remote_client.native_mode_requested else None


class SPATIAL_OT_native_take_turn(bpy.types.Operator):
    bl_idname = "spatial_modeling.native_take_turn"
    bl_label = "Take edit turn"
    bl_description = "Reserve the shared document before using ordinary Blender tools"

    @classmethod
    def poll(cls, _context):
        client = _client()
        return client is not None and client.connected and not client.is_editing

    def execute(self, _context):
        client = _client()
        if not client.take_edit_turn():
            self.report({"WARNING"}, client.error or "Waiting for the host")
            return {"CANCELLED"}
        return {"FINISHED"}


class SPATIAL_OT_native_finish_turn(bpy.types.Operator):
    bl_idname = "spatial_modeling.native_finish_turn"
    bl_label = "Finish edit turn"
    bl_description = "Publish settled native changes, await acknowledgement, then release the document"

    @classmethod
    def poll(cls, _context):
        return _client() is not None and _client().is_editing

    def execute(self, _context):
        return {"FINISHED"} if _client().finish_edit_turn() else {"CANCELLED"}


class SPATIAL_OT_native_save_copy(bpy.types.Operator):
    bl_idname = "spatial_modeling.native_save_copy"
    bl_label = "Save local copy"
    bl_description = "Save the retained native draft or current original document as a separate .blend"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    @classmethod
    def poll(cls, _context):
        client = _client()
        return (client is not None and (client.has_native_document or client.initial_local_work)
                and not client.applying)

    def invoke(self, context, _event):
        self.filepath = "native-local-copy.blend"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, _context):
        try:
            _client().save_copy(bpy.path.ensure_ext(self.filepath, ".blend"))
        except (OSError, ValueError, RuntimeError):
            self.report({"ERROR"}, "Could not save local native copy")
            return {"CANCELLED"}
        return {"FINISHED"}


class SPATIAL_OT_native_reload(bpy.types.Operator):
    bl_idname = "spatial_modeling.native_reload"
    bl_label = "Reload host document"
    bl_description = "Retain a draft file, then explicitly replace local data with the current host checkpoint"

    @classmethod
    def poll(cls, _context):
        return _client() is not None and _client().connected and not _client().applying

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)

    def execute(self, _context):
        return {"FINISHED"} if _client().reload_host(discard=True) else {"CANCELLED"}


class SPATIAL_PT_native_client(bpy.types.Panel):
    bl_label = "Native shared Blender"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spatial"

    @classmethod
    def poll(cls, _context):
        return _client() is not None

    def draw(self, _context):
        client, layout = _client(), self.layout
        layout.label(text=client.status, icon="INFO")
        if client.error:
            layout.label(text=client.error, icon="ERROR")
        layout.label(text="Use normal Blender tools during your edit turn.")
        layout.label(text="Undo/Redo stays native and synchronizes after settling.")
        layout.label(text="Incoming changes wait until local Edit Mode has finished.")
        row = layout.row(align=True)
        row.operator(SPATIAL_OT_native_take_turn.bl_idname)
        row.operator(SPATIAL_OT_native_finish_turn.bl_idname)
        layout.operator(SPATIAL_OT_native_save_copy.bl_idname)
        layout.operator(SPATIAL_OT_native_reload.bl_idname)


CLASSES = (SPATIAL_OT_native_take_turn, SPATIAL_OT_native_finish_turn,
           SPATIAL_OT_native_save_copy, SPATIAL_OT_native_reload, SPATIAL_PT_native_client)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
