using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // Native key intent only: no queue, input transport, permissions or Undo.
    // The caller must first isolate its held modifiers and position a fresh
    // editor target, then atomically admit this chord and restore its modifiers.
    public sealed class PreviewShortcut
    {
        public string Id { get; }
        public string Label { get; }
        public string Group { get; }
        public bool RequiresEditorContext { get; }
        public bool OpensModal { get; }
        readonly string key;
        readonly string[] modifiers;

        internal PreviewShortcut(string id, string label, string group, string key,
            bool modal = false, bool editor = true, params string[] modifiers)
        {
            Id = id; Label = label; Group = group; this.key = key;
            OpensModal = modal; RequiresEditorContext = editor;
            var ordered = new List<string>();
            foreach (string modifier in new[] { "CTRL", "SHIFT", "ALT" })
                if (Array.IndexOf(modifiers, modifier) >= 0) ordered.Add(modifier);
            this.modifiers = ordered.ToArray();
        }

        static JObject Key(string key, string action) =>
            new JObject { ["type"] = "key", ["key"] = key, ["action"] = action };

        public IReadOnlyList<JObject> BuildEvents()
        {
            var events = new List<JObject>();
            foreach (string modifier in modifiers) events.Add(Key(modifier, "down"));
            events.Add(Key(key, "press"));
            for (int i = modifiers.Length - 1; i >= 0; i--) events.Add(Key(modifiers[i], "up"));
            // Fresh payloads on every call: transport annotations or a caller's
            // accidental edits cannot contaminate another button activation.
            return events.AsReadOnly();
        }
    }

    public static class PreviewShortcutCatalog
    {
        public static IReadOnlyList<PreviewShortcut> All { get; } = Array.AsReadOnly(new[] {
            new PreviewShortcut("select.all", "Select all", "Selection", "A"),
            new PreviewShortcut("select.none", "Deselect all", "Selection", "A", modifiers: new[] { "ALT" }),
            new PreviewShortcut("select.invert", "Invert selection", "Selection", "I", modifiers: new[] { "CTRL" }),
            new PreviewShortcut("object.duplicate", "Duplicate · place", "Modeling", "D", modal: true, modifiers: new[] { "SHIFT" }),
            new PreviewShortcut("mode.edit", "Toggle Edit Mode", "Modeling", "TAB"),
            new PreviewShortcut("transform.move", "Move", "Modeling", "G", modal: true),
            new PreviewShortcut("transform.rotate", "Rotate", "Modeling", "R", modal: true),
            new PreviewShortcut("transform.scale", "Scale", "Modeling", "S", modal: true),
            new PreviewShortcut("mesh.extrude", "Extrude", "Mesh tools", "E", modal: true),
            new PreviewShortcut("mesh.inset", "Inset", "Mesh tools", "I", modal: true),
            new PreviewShortcut("mesh.bevel", "Bevel", "Mesh tools", "B", modal: true, modifiers: new[] { "CTRL" }),
            new PreviewShortcut("mesh.loop_cut", "Loop cut", "Mesh tools", "R", modal: true, modifiers: new[] { "CTRL" }),
            new PreviewShortcut("mesh.merge", "Merge menu", "Mesh tools", "M", modal: true),
            new PreviewShortcut("object.hide", "Hide selected", "Visibility", "H"),
            new PreviewShortcut("object.unhide", "Show hidden", "Visibility", "H", modifiers: new[] { "ALT" }),
            new PreviewShortcut("view.frame", "Frame selected", "View", "DECIMAL"),
            new PreviewShortcut("view.all", "Frame all", "View", "HOME"),
            new PreviewShortcut("view.front", "Front view", "View", "NUMPAD1"),
            new PreviewShortcut("view.right", "Right view", "View", "NUMPAD3"),
            new PreviewShortcut("view.top", "Top view", "View", "NUMPAD7"),
            new PreviewShortcut("view.back", "Back view", "View", "NUMPAD1", modifiers: new[] { "CTRL" }),
            new PreviewShortcut("view.left", "Left view", "View", "NUMPAD3", modifiers: new[] { "CTRL" }),
            new PreviewShortcut("view.bottom", "Bottom view", "View", "NUMPAD7", modifiers: new[] { "CTRL" }),
            new PreviewShortcut("view.perspective", "Perspective / ortho", "View", "NUMPAD5"),
            new PreviewShortcut("view.camera", "Camera view", "View", "NUMPAD0"),
            new PreviewShortcut("view.local", "Local view", "View", "DIVIDE"),
            new PreviewShortcut("view.shading", "Shading menu", "View", "Z", modal: true),
            new PreviewShortcut("panel.tools", "Toggle toolbar", "Panels", "T"),
            new PreviewShortcut("panel.sidebar", "Toggle sidebar", "Panels", "N"),
            new PreviewShortcut("cancel", "Cancel / Escape", "Finish", "ESC", editor: false),
            new PreviewShortcut("confirm", "Confirm / Enter", "Finish", "ENTER", editor: false)
        });

        // Actual helper virtual-key names, not OS/system shortcuts. DIVIDE has
        // the Win32 extended-key flag; the other numeric operators do not.
        public static IReadOnlyList<string> FullKeyboardKeys { get; } = Array.AsReadOnly(new[] {
            "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
            "NUMPAD0", "NUMPAD1", "NUMPAD2", "NUMPAD3", "NUMPAD4", "NUMPAD5", "NUMPAD6", "NUMPAD7", "NUMPAD8", "NUMPAD9",
            "DECIMAL", "DIVIDE", "MULTIPLY", "ADD", "SUBTRACT", "ESC", "INSERT"
        });

        public static bool TryGet(string id, out PreviewShortcut shortcut)
        {
            foreach (var item in All)
                if (string.Equals(item.Id, id, StringComparison.Ordinal)) { shortcut = item; return true; }
            shortcut = null; return false;
        }

        public static IReadOnlyList<JObject> BuildEvents(string id)
        {
            if (!TryGet(id, out var shortcut)) throw new ArgumentException("Unknown preview shortcut", nameof(id));
            return shortcut.BuildEvents();
        }
    }
}
