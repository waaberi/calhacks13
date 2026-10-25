"""Native Client edit-turn controls; ordinary Blender keeps all modeling tools."""
import bpy


def _client():
    from .. import remote_client
    return remote_client.native_client if remote_client.native_mode_requested else None


def _host_service(context):
    from .. import host
    addon = context.preferences.addons.get(__package__.rsplit(".", 1)[0])
    if addon is None or addon.preferences.role != "HOST":
        return None
    return getattr(host._server, "native_sync", None)


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
    check_existing: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_glob: bpy.props.StringProperty(default="*.blend", options={"HIDDEN"})

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
        if not self.filepath:
            self.report({"WARNING"}, "Choose a separate .blend destination first")
            return {"CANCELLED"}
        try:
            _client().save_copy(bpy.path.ensure_ext(self.filepath, ".blend"))
        except (OSError, ValueError, RuntimeError):
            self.report({"ERROR"}, "Could not save local native copy")
            return {"CANCELLED"}
        return {"FINISHED"}


class SPATIAL_OT_native_checked_document(bpy.types.Operator):
    bl_idname = "spatial_modeling.native_checked_document"
    bl_label = "I checked the shared document"
    bl_description = "Record the inspected current native document without replaying an unknown request"

    @classmethod
    def poll(cls, context):
        service = _host_service(context)
        return service is not None and service.has_unknown

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event,
            title="Inspect the shared document",
            message=("Only continue after inspecting the current Blender document. "
                     "Previous unknown request will not be replayed."),
            confirm_text="I checked the shared document", icon="QUESTION")

    def execute(self, context):
        service = _host_service(context)
        if service is None or not service.has_unknown:
            return {"CANCELLED"}
        try:
            service.reconcile_unknown()
        except (OSError, RuntimeError, ValueError):
            self.report({"ERROR"}, "Could not record the inspected document; finish the active native operation first")
            return {"CANCELLED"}
        self.report({"INFO"}, "Current document recorded; previous unknown requests were not replayed")
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


class SPATIAL_PT_native_host_recovery(bpy.types.Panel):
    bl_label = "Native sharing recovery"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spatial"

    @classmethod
    def poll(cls, context):
        service = _host_service(context)
        return service is not None and (service.has_unknown or bool(service.error))

    def draw(self, context):
        service, layout = _host_service(context), self.layout
        if service.error:
            layout.label(text=service.error, icon="ERROR")
        if service.has_unknown:
            layout.label(text="Inspect the current shared Blender document first.", icon="INFO")
            layout.label(text="Previous unknown requests will not be replayed.")
            layout.operator(SPATIAL_OT_native_checked_document.bl_idname)


CLASSES = (SPATIAL_OT_native_take_turn, SPATIAL_OT_native_finish_turn,
           SPATIAL_OT_native_save_copy, SPATIAL_OT_native_reload,
           SPATIAL_OT_native_checked_document, SPATIAL_PT_native_client,
           SPATIAL_PT_native_host_recovery)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
