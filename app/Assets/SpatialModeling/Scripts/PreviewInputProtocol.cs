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

        static bool Window(JToken value) => value is JObject
            && Number(value["hwnd"], 1, long.MaxValue) && Number(value["pid"], 1, uint.MaxValue);

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
