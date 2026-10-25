using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using SpatialModeling;

// Pure event-intent checks. No Unity objects, transport, input injection or Blender.
public static class P25ShortcutChecks
{
    static void Check(bool ok, string reason)
    { if (!ok) throw new Exception("P2.5 shortcuts: " + reason); }

    static string Signature(IReadOnlyList<JObject> events)
    {
        var parts = new List<string>();
        foreach (var e in events) parts.Add((string)e["key"] + ":" + (string)e["action"]);
        return string.Join("/", parts);
    }

    public static void Run(Action<string> report)
    {
        var expected = new Dictionary<string, string> {
            ["select.all"] = "A:press", ["select.none"] = "ALT:down/A:press/ALT:up",
            ["select.invert"] = "CTRL:down/I:press/CTRL:up",
            ["object.duplicate"] = "SHIFT:down/D:press/SHIFT:up", ["mode.edit"] = "TAB:press",
            ["transform.move"] = "G:press", ["transform.rotate"] = "R:press", ["transform.scale"] = "S:press",
            ["mesh.extrude"] = "E:press", ["mesh.inset"] = "I:press",
            ["mesh.bevel"] = "CTRL:down/B:press/CTRL:up", ["mesh.loop_cut"] = "CTRL:down/R:press/CTRL:up",
            ["mesh.merge"] = "M:press", ["object.hide"] = "H:press", ["object.unhide"] = "ALT:down/H:press/ALT:up",
            ["view.frame"] = "DECIMAL:press", ["view.all"] = "HOME:press",
            ["view.front"] = "NUMPAD1:press", ["view.right"] = "NUMPAD3:press", ["view.top"] = "NUMPAD7:press",
            ["view.back"] = "CTRL:down/NUMPAD1:press/CTRL:up", ["view.left"] = "CTRL:down/NUMPAD3:press/CTRL:up",
            ["view.bottom"] = "CTRL:down/NUMPAD7:press/CTRL:up", ["view.perspective"] = "NUMPAD5:press",
            ["view.camera"] = "NUMPAD0:press", ["view.local"] = "DIVIDE:press", ["view.shading"] = "Z:press",
            ["panel.tools"] = "T:press", ["panel.sidebar"] = "N:press", ["cancel"] = "ESC:press", ["confirm"] = "ENTER:press"
        };
        var modals = new HashSet<string> { "object.duplicate", "transform.move", "transform.rotate", "transform.scale",
            "mesh.extrude", "mesh.inset", "mesh.bevel", "mesh.loop_cut", "mesh.merge", "view.shading" };
        var identifiers = new HashSet<string>();
        Check(PreviewShortcutCatalog.All.Count == expected.Count, "all specified common actions are represented");
        foreach (var item in PreviewShortcutCatalog.All)
        {
            Check(identifiers.Add(item.Id) && !string.IsNullOrEmpty(item.Label) && !string.IsNullOrEmpty(item.Group),
                "stable IDs are unique and each button has a semantic label/group");
            Check(PreviewShortcutCatalog.TryGet(item.Id, out var found) && ReferenceEquals(found, item), "lookup returns the actual catalog item");
            var events = item.BuildEvents();
            Check(Signature(events) == expected[item.Id], "named action uses its exact native Blender chord: " + item.Id);
            Check(item.RequiresEditorContext == (item.Id != "cancel" && item.Id != "confirm"),
                "context-sensitive actions cannot masquerade as global keyboard controls");
            Check(item.OpensModal == modals.Contains(item.Id), "modal/popup actions require a completion/cancel workflow");
            var held = new HashSet<string>();
            foreach (var e in events)
            {
                Check(e.Count == 3 && (string)e["type"] == "key" && e["seq"] == null && e["token"] == null,
                    "catalog outputs only key intent without sending, credentials or transport numbering");
                string key = (string)e["key"], action = (string)e["action"];
                if (action == "down") Check((key == "CTRL" || key == "SHIFT" || key == "ALT") && held.Add(key), "only balanced temporary modifiers are held");
                else if (action == "up") Check(held.Remove(key), "each modifier release follows its own down");
                else Check(action == "press" && !held.Contains(key), "ordinary keys are pressed rather than left held");
            }
            Check(held.Count == 0, "no catalog action leaks a temporary held modifier");
            events[0]["key"] = "CORRUPTED"; events[0]["token"] = "not-shared";
            var fresh = PreviewShortcutCatalog.BuildEvents(item.Id);
            Check(Signature(fresh) == expected[item.Id] && fresh[0]["token"] == null, "caller annotations cannot contaminate a later activation");
        }
        Check(!PreviewShortcutCatalog.TryGet("os.printscreen", out _) && !PreviewShortcutCatalog.TryGet(null, out _),
            "unknown/system operations cannot be selected");
        bool refused = false;
        try { PreviewShortcutCatalog.BuildEvents("not-a-button"); } catch (ArgumentException) { refused = true; }
        Check(refused, "unknown action fails closed before queue admission");
        var keys = new HashSet<string>(PreviewShortcutCatalog.FullKeyboardKeys);
        Check(keys.Count == 29 && keys.Count == PreviewShortcutCatalog.FullKeyboardKeys.Count, "explicit extended keyboard keyset is unique and bounded");
        for (int n = 1; n <= 12; n++) Check(keys.Contains("F" + n), "all twelve function keys are available");
        for (int n = 0; n <= 9; n++) Check(keys.Contains("NUMPAD" + n), "all ten native numpad digits are available");
        foreach (string key in new[] { "DECIMAL", "DIVIDE", "MULTIPLY", "ADD", "SUBTRACT", "ESC", "INSERT" })
            Check(keys.Contains(key), "numeric operators and local editing keys are available");
        Check(!keys.Contains("WIN") && !keys.Contains("PRINTSCREEN"), "keyboard does not add OS/system shortcut keys");
        report("P25_SHORTCUT_CATALOG_CHECK PASS 31 exact native key chords/context+modal labels/balanced modifiers/fresh payloads/29 keyboard keys; no transport, OS input or native GUI");
    }
}
