using System;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // Validate wire data before it can mutate the input owner. A successful HTTP
    // status alone is not an acknowledgement that held native input was released.
    public static class PreviewInputProtocol
    {
        static bool Text(JToken value, bool nonempty = false, int limit = 1024) =>
            value?.Type == JTokenType.String && ((string)value).Length <= limit
            && (!nonempty || ((string)value).Length > 0);

        static bool Number(JToken value, long minimum, long maximum)
        {
            if (value?.Type != JTokenType.Integer) return false;
            try { long number = (long)value; return number >= minimum && number <= maximum; }
            catch (Exception) { return false; }
        }

        static bool Window(JToken value)
        {
            if (!(value is JObject) || !Number(value["hwnd"], 1, long.MaxValue)
                || !Number(value["pid"], 1, uint.MaxValue)) return false;
            if (value["blender_pid"] != null && !Number(value["blender_pid"], 1, uint.MaxValue)) return false;
            if (value["blender_hwnd"] != null && !Number(value["blender_hwnd"], 1, long.MaxValue)) return false;
            foreach (string name in new[] { "blender_process_started", "input_process_started" })
                if (value[name] != null && !Number(value[name], 1, long.MaxValue)) return false;
            foreach (string name in new[] { "owner_hwnd", "parent_hwnd", "menu_owner_hwnd" })
                if (value[name] != null && !Number(value[name], 0, long.MaxValue)) return false;
            if (value["title"] != null && !Text(value["title"])) return false;
            if (value["window_class"] != null && !Text(value["window_class"], true, 256)) return false;
            if (value["kind"] != null && (value["kind"]?.Type != JTokenType.String
                || ((string)value["kind"] != "blender" && (string)value["kind"] != "dialog" && (string)value["kind"] != "popup"))) return false;
            return true;
        }

        static bool Parse(string json, out JObject result)
        {
            result = null;
            if (string.IsNullOrEmpty(json) || json.Length > 1024 * 1024) return false;
            try { result = JObject.Parse(json); return true; }
            catch (Exception) { return false; }
        }

        public static bool TryState(string json, out JObject state)
        {
            state = null;
            if (!Parse(json, out var p)) return false;
            // The capture-only helper deliberately exposes no input credentials
            // or identity. Admit its exact disabled shape for setup guidance;
            // it cannot synchronize transport or authorize any native event.
            if (p.Count == 3 && p["enabled"]?.Type == JTokenType.Boolean && !(bool)p["enabled"]
                && p["ready"]?.Type == JTokenType.Boolean && !(bool)p["ready"]
                && p["reason"]?.Type == JTokenType.String && (string)p["reason"] == "input_disabled")
            { state = p; return true; }
            foreach (string name in new[] { "enabled", "ready", "focused", "release_error" })
                if (p[name]?.Type != JTokenType.Boolean) return false;
            bool enabled = (bool)p["enabled"], ready = (bool)p["ready"];
            if (!Text(p["session"], true) || !Number(p["next_seq"], 1, long.MaxValue - 1)
                || !Number(p["helper_pid"], 1, uint.MaxValue)
                || !Number(p["capture_generation"], 0, long.MaxValue)
                || !Text(p["capture_instance"], true) || !Text(p["reason"])) return false;
            if (enabled ? !Text(p["token"], true) : p["token"]?.Type != JTokenType.Null && !Text(p["token"])) return false;
            if (ready && (!enabled || !Window(p["selection"]) || !Text(p["capture_geometry"], true))) return false;
            if (!ready && (p["selection"]?.Type != JTokenType.Null && !Window(p["selection"]))) return false;
            if (!ready && (p["capture_geometry"]?.Type != JTokenType.Null && !Text(p["capture_geometry"]))) return false;
            if (!(p["windows"] is JArray windows)) return false;
            foreach (var window in windows) if (!Window(window)) return false;
            if (p["window_scope"] != null && !Text(p["window_scope"], true)) return false;
            if (p["follow_windows"] != null && p["follow_windows"]?.Type != JTokenType.Boolean) return false;
            if (p["geometry"] != null && p["geometry"].Type != JTokenType.Null)
            {
                if (!(p["geometry"] is JObject geometry)) return false;
                if (geometry["blender_process_started"] != null && !Number(geometry["blender_process_started"], 1, long.MaxValue)) return false;
                if (geometry["blender_pid"] != null && !Number(geometry["blender_pid"], 1, uint.MaxValue)) return false;
            }
            state = p;
            return true;
        }

        public static bool Acknowledged(string json, long expectedSequence)
        {
            return expectedSequence > 0 && Parse(json, out var p)
                && p["ok"]?.Type == JTokenType.Boolean && (bool)p["ok"]
                && Number(p["seq"], expectedSequence, expectedSequence);
        }
    }
}
