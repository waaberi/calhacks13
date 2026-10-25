using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // A new typed sketch preserves the desktop's native selection. Its matching
    // receipt explicitly selects the new UUID for spatial drawing instead of
    // accidentally falling back to the older native-active sketch.
    public sealed class SpatialSketchTarget
    {
        public string ExplicitId { get; private set; } = "";
        public bool MissingExplicitTarget { get; private set; }
        public bool WaitingForExplicitTarget => ExplicitId.Length > 0 && !observedExplicitTarget;
        string requestId, context = "";
        bool observedExplicitTarget;

        public static string ContextKey(JObject nativeState) =>
            (string)nativeState?["sketch_id"] + "/" + (string)nativeState?["native_tool"];

        public static bool CanStartCreation(bool stateCurrent, JObject nativeState) => stateCurrent
            && (bool?)nativeState?["available"] == true && (string)nativeState?["mode"] == "OBJECT";

        public void Reset()
        { requestId = null; ExplicitId = ""; MissingExplicitTarget = false; observedExplicitTarget = false; context = ""; }

        public void ObserveContext(JObject nativeState)
        {
            string next = ContextKey(nativeState);
            if (context != next) { Reset(); context = next; }
        }

        public void BeginCreate(string id, JObject nativeState)
        { ObserveContext(nativeState); requestId = id; }

        public bool Receive(JObject message, IDictionary<string, JObject> nativeSketches)
        {
            if (requestId == null || (string)message?["type"] != "result"
                || (string)message["payload"]?["request_id"] != requestId) return false;
            var receipt = message["payload"];
            if ((string)receipt["outcome"] == "pending") return false;
            requestId = null;
            if ((string)receipt["outcome"] != "applied" || (string)receipt["op"] != "sketch.create"
                || !(receipt["created"] is JArray ids) || ids.Count == 0) return false;
            string id = (string)ids[0];
            ExplicitId = id ?? "";
            observedExplicitTarget = nativeSketches.ContainsKey(ExplicitId);
            MissingExplicitTarget = false;
            return true;
        }

        public JObject Resolve(string nativeActiveId, string selectedId, IDictionary<string, JObject> nativeSketches)
        {
            if (ExplicitId.Length > 0)
            {
                if (nativeSketches.TryGetValue(ExplicitId, out var explicitSketch))
                { observedExplicitTarget = true; MissingExplicitTarget = false; return explicitSketch; }
                // A valid receipt may arrive before its accepted scene record.
                // Wait for that exact native UUID; never fall back to A.
                if (!observedExplicitTarget) return null;
                // Target removal must not redirect the next click to a different
                // native sketch. Require a fresh target/context choice.
                ExplicitId = ""; MissingExplicitTarget = true;
            }
            if (MissingExplicitTarget) return null;
            if (!string.IsNullOrEmpty(nativeActiveId))
                return nativeSketches.TryGetValue(nativeActiveId, out var native) ? native : null;
            return nativeSketches.TryGetValue(selectedId ?? "", out var selected) ? selected : null;
        }
    }
}
