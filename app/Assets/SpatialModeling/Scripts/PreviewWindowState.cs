using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    public static class PreviewWindowState
    {
        public static long Positive(JToken token)
        {
            if (token?.Type != JTokenType.Integer) return 0;
            try { long value = (long)token; return value > 0 ? value : 0; } catch (System.Exception) { return 0; }
        }
        public static long RootPid(JObject state)
        {
            var window = state?["selection"] as JObject;
            return Positive(window?["blender_pid"] ?? window?["pid"]);
        }
        public static long RootStamp(JObject state) => Positive((state?["selection"] as JObject)?["blender_process_started"]
            ?? (state?["geometry"] as JObject)?["blender_process_started"]);
        static bool SameText(JObject a, JObject b, string key) => a?[key]?.Type == JTokenType.String
            && b?[key]?.Type == JTokenType.String && !string.IsNullOrEmpty((string)a[key])
            && (string)a[key] == (string)b?[key];
        public static bool CanContinue(JObject before, JObject after, long nativePid) => nativePid > 0
            && SameText(before, after, "window_scope") && SameText(before, after, "capture_instance")
            && SameText(before, after, "token") && RootPid(before) == nativePid && RootPid(after) == nativePid
            && RootStamp(before) > 0 && RootStamp(before) == RootStamp(after)
            && (bool?)after?["enabled"] == true && (bool?)after?["release_error"] == false;
    }

    // Native UI reservations have no tool-telemetry TTL. Preserve only an actual
    // confirmed grant, tied to this connection/document and exact helper/root
    // lifetime. This permits raw UI input while a modal blocks native tool
    // queries; typed model/spatial actions still require fresh native telemetry.
    public sealed class NativePreviewAuthority
    {
        string identity = "", uiToken = "";
        JObject helper;
        public long ProcessId { get; private set; }
        public void Clear() { identity = uiToken = ""; helper = null; ProcessId = 0; }
        static bool Owned(NativeEditSession session, JObject native)
        {
            var id = session.RequestIdentity;
            if (!session.Ready || !session.CanEdit || !session.SceneCurrent || id == null
                || (bool?)native?["input_allowed"] != true || (bool?)native?["ui_ending"] == true
                || string.IsNullOrEmpty((string)native?["ui_session_id"])
                || (string)(native?["ui_owner"] as JObject)?["actor_id"] != session.ActorId) return false;
            foreach (string key in new[] { "session_id", "host_epoch", "document_id", "open_epoch" })
                if ((string)native[key] != (string)id[key]) return false;
            return true;
        }
        public bool Capture(NativeEditSession session, JObject native, JObject state)
        {
            Clear();
            long pid = PreviewWindowState.Positive(native?["process_id"]);
            if (!Owned(session, native) || (bool?)state?["ready"] != true
                || !PreviewWindowState.CanContinue(state, state, pid)) return false;
            ProcessId = pid; uiToken = (string)native["ui_session_id"];
            identity = session.RequestIdentity.ToString(Newtonsoft.Json.Formatting.None);
            helper = (JObject)state.DeepClone();
            return true;
        }
        public bool Matches(NativeEditSession session, JObject native, JObject state) => helper != null
            && Owned(session, native) && uiToken == (string)native["ui_session_id"]
            && ProcessId == PreviewWindowState.Positive(native["process_id"])
            && identity == session.RequestIdentity.ToString(Newtonsoft.Json.Formatting.None)
            && PreviewWindowState.CanContinue(helper, state, ProcessId);
    }
}
