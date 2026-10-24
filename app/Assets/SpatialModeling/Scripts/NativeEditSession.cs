using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // Main-thread state machine. Drafts never change geometry or acquire permissions.
    // Only a matching native receipt can turn Pending into Applied.
    public sealed class NativeEditSession
    {
        public readonly Dictionary<string, JObject> Objects = new Dictionary<string, JObject>();
        public readonly Dictionary<string, JObject> Sketches = new Dictionary<string, JObject>();
        public JArray Leases { get; private set; } = new JArray();
        public JArray Participants { get; private set; } = new JArray();
        public JObject Document { get; private set; } = new JObject();
        public JObject Draft { get; private set; }
        public JObject LastReceipt { get; private set; }
        public string SelectedId { get; private set; } = "";
        public string ActorId { get; private set; } = "";
        public string Notice { get; private set; } = "Waiting for Blender snapshot";
        public string Mode { get; set; } = "exclusive";
        public bool Ready { get; private set; }
        public bool SceneCurrent { get; set; } = true; // Bridge binds this to HostScene's accepted render state.
        public bool CanEdit { get; private set; }
        public bool SketchAvailable { get; private set; }
        public bool Busy => acquireId != null || commandId != null;
        public bool OutcomeUnknown { get; private set; }
        public long Revision => (long?)Document["revision"] ?? 0;
        public Action<JObject> Send;
        public event Action Changed;

        JObject identity, pendingCommand;
        string acquireId, commandId, leaseId;
        bool cancelAcquire;
        readonly HashSet<string> cancelledAcquisitions = new HashSet<string>();
        public JObject Selected => Objects.TryGetValue(SelectedId, out var o) ? o : Sketches.TryGetValue(SelectedId, out var s) ? s : null;

        public void Disconnect(string reason)
        {
            if (Busy) OutcomeUnknown = true;
            Ready = CanEdit = false;
            Draft = null;
            acquireId = commandId = leaseId = null;
            pendingCommand = null;
            cancelledAcquisitions.Clear(); // A disconnected actor's permissions are released by the host.
            Leases = new JArray();
            Notice = "Connection lost. " + (OutcomeUnknown ? "Last edit outcome unknown; wait for a fresh snapshot. " : "Edits disabled. ") + reason;
            Changed?.Invoke();
        }

        public void Receive(JObject message)
        {
            var p = message["payload"] as JObject;
            var type = (string)message["type"];
            if (type == "connection.closed") { Disconnect((string)p?["reason"] ?? ""); return; }
            if (p == null) return;
            switch (type)
            {
                case "welcome":
                    Ready = false;
                    identity = new JObject {
                        ["session_id"] = p["session_id"], ["host_epoch"] = p["host_epoch"],
                        ["document_id"] = p["document"]?["id"], ["open_epoch"] = p["document"]?["open_epoch"],
                        ["actor_id"] = p["actor_id"]
                    };
                    ActorId = (string)p["actor_id"] ?? "";
                    CanEdit = (bool?)p["can_edit"] ?? false;
                    // Host must explicitly advertise a working native adapter.
                    SketchAvailable = (bool?)p["capabilities"]?["sketch"] ?? false;
                    Document = (JObject)p["document"].DeepClone();
                    Leases = new JArray();
                    Notice = "Connected; waiting for current native scene";
                    break;
                case "scene.snapshot":
                case "scene.update":
                    bool snapshot = type == "scene.snapshot";
                    if (p["document"] is JObject d)
                    {
                        bool different = identity != null && ((string)d["id"] != (string)identity["document_id"]
                            || (string)d["open_epoch"] != (string)identity["open_epoch"]);
                        if (different) { Disconnect("Document changed; reconnect required."); return; }
                        Document = (JObject)d.DeepClone();
                    }
                    if (snapshot) { Objects.Clear(); Sketches.Clear(); }
                    if (p["removed"] is JArray removed) foreach (var id in removed) { Objects.Remove((string)id); Sketches.Remove((string)id); }
                    Store(p["objects"] as JArray, Objects);
                    Store(p["sketches"] as JArray, Sketches);
                    if (snapshot && identity != null && (!Ready || OutcomeUnknown))
                    {
                        Ready = true;
                        OutcomeUnknown = false;
                        Draft = null;
                        acquireId = commandId = leaseId = null;
                        pendingCommand = null;
                        Notice = CanEdit ? "Native scene current. Select an object to edit." : "Read-only participant";
                    }
                    if (Selected == null) SelectedId = "";
                    break;
                case "session.update":
                    Participants = (JArray)(p["participants"]?.DeepClone() ?? new JArray());
                    Leases = (JArray)(p["leases"]?.DeepClone() ?? new JArray());
                    break;
                case "lease.granted":
                    if (cancelledAcquisitions.Remove((string)message["re"] ?? ""))
                    {
                        var lateId = (string)p["lease"]?["lease_id"];
                        if (lateId != null) Send?.Invoke(Envelope("lease.release", new JObject { ["lease_id"] = lateId }));
                        if ((string)message["re"] == acquireId) { acquireId = null; pendingCommand = null; }
                        break;
                    }
                    if ((string)message["re"] != acquireId) break;
                    acquireId = null;
                    leaseId = (string)p["lease"]?["lease_id"];
                    if (cancelAcquire || OutcomeUnknown || !Ready || !SceneCurrent || pendingCommand == null)
                    { Release(); pendingCommand = null; Notice = "Cancelled before native mutation"; break; }
                    if (string.IsNullOrEmpty(leaseId)) { Fail("Host granted no usable permission"); break; }
                    pendingCommand["payload"]["lease"] = leaseId;
                    commandId = (string)pendingCommand["id"];
                    Notice = "Waiting for Blender to confirm the native edit…";
                    Send?.Invoke(pendingCommand);
                    break;
                case "result":
                    if ((string)p["request_id"] != commandId) break;
                    LastReceipt = (JObject)p.DeepClone();
                    string outcome = (string)p["outcome"];
                    if (outcome == "pending") break;
                    commandId = null;
                    pendingCommand = null;
                    Release();
                    Draft = null;
                    if (outcome == "unknown") Freeze("Native outcome unknown. Reconnect for a fresh snapshot.");
                    else if (outcome == "applied")
                    {
                        Notice = (string)p["summary"] ?? "Applied in Blender";
                        if (p["created"] is JArray created && created.Count > 0
                            && (Objects.ContainsKey((string)created[0]) || Sketches.ContainsKey((string)created[0]))) SelectedId = (string)created[0];
                    }
                    else Notice = ErrorText(p["error"] as JObject);
                    break;
                case "error":
                    if ((string)p["code"] == "internal_error") { Freeze(ErrorText(p)); break; }
                    if ((string)message["re"] == acquireId || (string)message["re"] == commandId)
                        Fail(ErrorText(p));
                    break;
            }
            Changed?.Invoke();
        }

        static void Store(JArray values, Dictionary<string, JObject> records)
        {
            if (values == null) return;
            foreach (JObject value in values)
            {
                string id = (string)value["id"];
                if (id == null) continue;
                if (!records.TryGetValue(id, out var previous)) records[id] = (JObject)value.DeepClone();
                else previous.Merge(value, new JsonMergeSettings { MergeArrayHandling = MergeArrayHandling.Replace, MergeNullValueHandling = MergeNullValueHandling.Merge });
            }
        }

        public void Select(string id)
        {
            if (Busy) { Notice = "Wait for the current native receipt before changing target"; Changed?.Invoke(); return; }
            SelectedId = Objects.ContainsKey(id) || Sketches.ContainsKey(id) ? id : "";
            Draft = null;
            Notice = Selected == null ? "No target selected" : "Selected " + (string)Selected["name"];
            Changed?.Invoke();
        }

        public bool BeginDraft(string op, JObject args, bool targeted)
        {
            if (!Ready || !SceneCurrent || !CanEdit || OutcomeUnknown || Busy) return Reject("Wait for a current editable scene and the previous receipt");
            if (targeted && Selected == null) return Reject("Select the native target first");
            var p = (JObject)identity.DeepClone();
            p["base_revision"] = Revision; p["source"] = "ui"; p["op"] = op; p["args"] = args.DeepClone();
            if (targeted) p["target"] = new JObject { ["id"] = SelectedId, ["generation"] = Selected["generation"] };
            Draft = p;
            Notice = "Draft only. Apply changes Blender; Cancel discards it.";
            Changed?.Invoke();
            return true;
        }

        public bool Apply()
        {
            if (!Ready || !SceneCurrent || !CanEdit || OutcomeUnknown || Busy || Draft == null) return Reject("No ready native draft to apply");
            string target = (string)Draft["target"]?["id"];
            string owner = ConflictOwner(target);
            if (owner != null) return Reject(owner + " owns this edit. Inspection remains available.");
            // Freeze the draft's original generation/revision. A new snapshot must never silently retarget Apply.
            pendingCommand = Envelope("command", (JObject)Draft.DeepClone());
            var acquire = (JObject)identity.DeepClone();
            acquire["mode"] = Mode == "shared" && target != null ? "shared" : "exclusive";
            acquire["targets"] = target != null && (string)acquire["mode"] == "shared" ? new JArray(target) : new JArray();
            var request = Envelope("lease.acquire", acquire);
            acquireId = (string)request["id"];
            cancelAcquire = false;
            Notice = "Requesting permission before changing Blender…";
            Send?.Invoke(request);
            Changed?.Invoke();
            return true;
        }

        public void Cancel()
        {
            if (commandId != null) { Notice = "Native transaction executing; wait for its receipt. Undo is available after completion."; Changed?.Invoke(); return; }
            Draft = null;
            cancelAcquire = acquireId != null;
            if (!cancelAcquire) Release();
            Notice = cancelAcquire ? "Cancelling permission request; no native edit sent" : "Draft cancelled. Native geometry unchanged.";
            Changed?.Invoke();
        }

        public void Timeout()
        {
            if (acquireId != null) { cancelledAcquisitions.Add(acquireId); cancelAcquire = true; pendingCommand = null; }
            if (Busy) Freeze("No native acknowledgement. Outcome unknown; reconnect before editing. The request will not be repeated.");
            Changed?.Invoke();
        }

        public string ConflictOwner(string target)
        {
            foreach (JObject lease in Leases)
            {
                if ((string)lease["owner"]?["actor_id"] == ActorId) continue;
                bool covers = target == null || (string)lease["mode"] == "exclusive";
                if (lease["targets"] is JArray targets) foreach (var id in targets) covers |= (string)id == target;
                if (covers) return (string)lease["owner"]?["name"] ?? "Another participant";
            }
            return null;
        }

        public bool OtherEditorActive { get { foreach (JObject l in Leases) if ((string)l["owner"]?["actor_id"] != ActorId) return true; return false; } }
        void Release()
        {
            if (leaseId != null && identity != null)
                Send?.Invoke(Envelope("lease.release", new JObject { ["lease_id"] = leaseId }));
            leaseId = null;
        }
        void Fail(string text) { acquireId = commandId = null; pendingCommand = null; Release(); Notice = text; }
        void Freeze(string text) { OutcomeUnknown = true; Ready = false; Draft = null; Notice = text; }
        bool Reject(string text) { Notice = text; Changed?.Invoke(); return false; }
        static string ErrorText(JObject error) => (string)error?["message"] ?? "Blender rejected the edit";
        public static JObject Envelope(string type, JObject payload) => new JObject { ["v"] = 1, ["type"] = type, ["id"] = Guid.NewGuid().ToString("N"), ["payload"] = payload };
    }
}
