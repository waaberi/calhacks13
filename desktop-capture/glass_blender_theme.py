"""Ephemeral glass companion palette for a factory-startup PRIVATE Blender only.

No file loading, document mutation, preference save or process/window manipulation.
Blender owns native widget shapes. RNA-supported roundness is applied when present.
"""


def apply_private_theme(bpy):
    preferences = bpy.context.preferences
    preferences.use_preferences_save = False
    theme = preferences.themes[0]
    applied = []
    for name in ("wcol_regular", "wcol_tool", "wcol_toolbar_item", "wcol_radio",
                 "wcol_toggle", "wcol_option", "wcol_text", "wcol_num",
                 "wcol_numslider", "wcol_menu", "wcol_pulldown", "wcol_menu_back",
                 "wcol_menu_item", "wcol_scroll", "wcol_list_item", "wcol_box"):
        widget = getattr(theme.user_interface, name, None)
        if widget is None:
            continue
        for key, value in {"inner": (.105, .125, .16, 1),
                           "inner_sel": (.14, .30, .25, 1),
                           "outline": (.32, .38, .47, 1),
                           "text": (.94, .96, .99),
                           "text_sel": (1, 1, 1),
                           "roundness": .8}.items():
            if not hasattr(widget, key):
                continue
            current = getattr(widget, key)
            try:
                setattr(widget, key, value[:len(current)] if isinstance(value, tuple) else value)
                applied.append(name + "." + key)
            except (TypeError, ValueError, AttributeError):
                # A supported theme can expose a read-only/shorter color property.
                # Preserve its existing value instead of guessing an RNA mutation.
                continue
    return {"profile": "ephemeral_private_factory_startup", "applied": applied,
            "personal_preferences_saved": False, "native_shape_limit":
            "Blender controls layout, popup borders, editor separators and icon geometry"}
