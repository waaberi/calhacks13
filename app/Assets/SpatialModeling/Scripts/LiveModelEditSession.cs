using System;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // One ordinary exclusive lease, acknowledged real-native updates, one final
    // history commit. Parameters are cumulative from the frozen start, not deltas
    // from the preceding preview. No OS input, executable operators or timers.
    public sealed class LiveModelEditSession
    {
        NativeEditSession parent;
        JObject identity, operation, latestParameters, inFlightParameters, acknowledgedParameters;
        JArray targets;
        string acquireId, beginId, updateId, terminalId, leaseId;
        bool commitRequested, cancelRequested;
        string cancelReason;
        public Action<JObject> Send;
        public event Action Changed;
        public bool Busy { get; private set; }
        public bool Active => Busy && !string.IsNullOrEmpty(EditSessionId) && Phase != "committed" && Phase != "cancelled" && Phase != "conflict";
        public string EditSessionId { get; private set; }
        public string Phase { get; private set; } = "idle";
        public long Sequence { get; private set; }
        public JObject LastState { get; private set; }
        public JObject AppliedSelection => LastState?["selection"] as JObject;
        public JObject AcknowledgedParameters => acknowledgedParameters==null?null:(JObject)acknowledgedParameters.DeepClone();
        public bool OutcomeUnknown { get; private set; }
        public string Notice { get; private set; } = "Choose a native tool and current selection";

        public void Configure(NativeEditSession session)
        {
            if (Busy) throw new InvalidOperationException("Cannot replace an active native live session");
            parent = session;
        }
        static JObject Envelope(string type, JObject payload) => new JObject {
            ["v"] = 1, ["type"] = type, ["id"] = Guid.NewGuid().ToString("N"), ["payload"] = payload
        };
        void Transmit(JObject message)
        { if (Send != null) Send(message); else parent?.Send?.Invoke(message); }
        bool SameIdentity(JObject value)
        {
            if (identity == null || value == null) return false;
            foreach (string name in new[] { "session_id", "host_epoch", "document_id", "open_epoch", "actor_id" })
                if ((string)value[name] != (string)identity[name]) return false;
            return true;
        }
        bool CurrentTargets()
        {
            if (parent == null || !parent.Ready || !parent.SceneCurrent || !parent.CanEdit || !SameIdentity(parent.RequestIdentity)) return false;
            foreach (JObject target in targets)
                if (!parent.Objects.TryGetValue((string)target["id"], out var current)
                    || (long?)current["generation"] != (long?)target["generation"]) return false;
            return true;
        }
        public bool Begin(JObject requestedOperation, JArray requestedTargets)
        {
            if (parent == null || Busy || parent.Busy || !parent.Ready || !parent.SceneCurrent
                || !parent.CanEdit || parent.OutcomeUnknown || OutcomeUnknown || requestedOperation == null
                || requestedTargets == null || requestedTargets.Count == 0)
            { Notice = "Wait for an editable current scene, native input release and the previous receipt"; Changed?.Invoke(); return false; }
            identity = parent.RequestIdentity;
            if (identity == null) return false;
            operation = (JObject)requestedOperation.DeepClone(); targets = (JArray)requestedTargets.DeepClone();
            if (!CurrentTargets()) { Notice = "Native selection changed before the gesture"; Changed?.Invoke(); return false; }
            operation["_live_base_revision"] = parent.Revision;
            EditSessionId = null; Sequence = 0; LastState = null;
            latestParameters = inFlightParameters = acknowledgedParameters = null;
            acquireId = beginId = updateId = terminalId = leaseId = null;
            commitRequested = cancelRequested = false; cancelReason = null;
            Busy = true; parent.ExternalEditBusy = true; Phase = "acquiring";
            var acquire = (JObject)identity.DeepClone(); acquire["mode"] = "exclusive"; acquire["targets"] = new JArray();
            var message = Envelope("lease.acquire", acquire); acquireId = (string)message["id"];
            Notice = "Requesting native live edit ownership"; Transmit(message); Changed?.Invoke(); return true;
        }
        public bool Update(JObject cumulativeParameters)
        {
            if (!Busy || cancelRequested || commitRequested || cumulativeParameters == null) return false;
            latestParameters = (JObject)cumulativeParameters.DeepClone(); Pump(); return true;
        }
        public bool Commit()
        {
            if (!Busy || cancelRequested) return false;
            commitRequested = true; Pump(); return true;
        }
        public bool KeepAlive()
        {
            if (!Active || updateId != null || terminalId != null || beginId != null
                || acknowledgedParameters == null || commitRequested || cancelRequested) return false;
            var payload = (JObject)identity.DeepClone(); payload["edit_session_id"] = EditSessionId;
            payload["sequence"] = Sequence; payload["parameters"] = acknowledgedParameters.DeepClone();
            var message = Envelope("live.edit.update", payload); updateId = (string)message["id"];
            inFlightParameters = (JObject)acknowledgedParameters.DeepClone();
            Transmit(message); return true;
        }
        public void Cancel(string reason = "Controller cancelled the native live edit")
        {
            if (!Busy) return;
            cancelRequested = true; commitRequested = false; latestParameters = null; cancelReason = reason;
            Notice = terminalId != null ? "Native finish already sent; waiting for its actual receipt" : "Cancelling native live geometry; waiting for restored state";
            Pump(); Changed?.Invoke();
        }
        public void Timeout()
        {
            if (!Busy) return;
            OutcomeUnknown = true;
            if (Active && terminalId == null)
            {
                // A lost update ACK must not prevent cleanup. Cancel is ordered
                // behind the update on the same stream and needs no sequence.
                cancelRequested = true; commitRequested = false; latestParameters = null;
                var payload = (JObject)identity.DeepClone(); payload["edit_session_id"] = EditSessionId;
                payload["reason"] = "Native live update acknowledgment timed out";
                var message = Envelope("live.edit.cancel", payload); terminalId = (string)message["id"];
                Phase = "cancelling"; Transmit(message);
            }
            else cancelRequested = true;
            Notice = "Native acknowledgment timed out; waiting for actual cleanup or receipt, then a fresh scene";
            Changed?.Invoke();
        }
        public void Disconnect(string reason)
        {
            if (!Busy) return;
            OutcomeUnknown = true; leaseId = null; // The server disconnect hook owns cleanup/release.
            Finish("conflict", "Native live outcome unknown after disconnect. " + reason);
        }
        void Pump()
        {
            if (!Busy || !Active || beginId != null || updateId != null || terminalId != null) return;
            var payload = (JObject)identity.DeepClone(); payload["edit_session_id"] = EditSessionId;
            if (cancelRequested)
            {
                payload["reason"] = cancelReason ?? "Controller cancelled";
                var message = Envelope("live.edit.cancel", payload); terminalId = (string)message["id"];
                Phase = "cancelling"; Transmit(message); return;
            }
            if (latestParameters != null)
            {
                payload["sequence"] = Sequence + 1; payload["parameters"] = latestParameters;
                inFlightParameters = latestParameters;
                latestParameters = null;
                var message = Envelope("live.edit.update", payload); updateId = (string)message["id"];
                Phase = "updating"; Transmit(message); return;
            }
            if (commitRequested)
            {
                if (Sequence == 0) { Cancel("Released without a native live update"); return; }
                payload["sequence"] = Sequence;
                var message = Envelope("live.edit.commit", payload); terminalId = (string)message["id"];
                Phase = "committing"; Notice = "Committing one native Undo step"; Transmit(message);
            }
        }
        public bool OwnsEcho(JObject message)
            => !string.IsNullOrEmpty(EditSessionId) && (string)message?["payload"]?["live_edit"]?["id"] == EditSessionId
                && (string)message?["payload"]?["live_edit"]?["actor_id"] == (string)identity?["actor_id"];
        public void Receive(JObject message)
        {
            string type = (string)message?["type"], re = (string)message?["re"];
            var payload = message?["payload"] as JObject;
            if (type == "connection.closed" || type == "welcome")
            {
                Disconnect("Inspect a fresh scene before editing again.");
                return;
            }
            if (type == "scene.snapshot" && !Busy) { OutcomeUnknown = false; return; }
            if (!Busy || payload == null) return;
            if (type == "lease.granted" && re == acquireId)
            {
                acquireId = null; leaseId = (string)payload["lease"]?["lease_id"];
                if (string.IsNullOrEmpty(leaseId)) { Finish("conflict", "No usable native permission was granted"); return; }
                if (cancelRequested || !CurrentTargets())
                { Finish("cancelled", "Gesture ended or native target changed before any live mutation"); return; }
                var begin = (JObject)identity.DeepClone(); begin["base_revision"] = operation["_live_base_revision"];
                operation.Remove("_live_base_revision"); begin["lease"] = leaseId;
                begin["targets"] = targets; begin["operation"] = operation;
                var request = Envelope("live.edit.begin", begin); beginId = (string)request["id"];
                Phase = "beginning"; Transmit(request); Changed?.Invoke(); return;
            }
            if (type == "error" && (re == acquireId || re == beginId || re == updateId || re == terminalId))
            {
                string notice = (string)payload["message"] ?? "Native live edit refused";
                if (re == updateId && Active)
                {
                    updateId = null; Notice = notice; Cancel(notice); return;
                }
                if (re == terminalId || (string)payload["code"] == "internal_error") OutcomeUnknown = true;
                Finish(OutcomeUnknown ? "conflict" : "cancelled", notice); return;
            }
            if (type != "live.edit.state" || !SameIdentity(payload)) return;
            bool beginning = re == beginId;
            if (!beginning && (string)payload["edit_session_id"] != EditSessionId) return;
            if (beginning) { beginId = null; EditSessionId = (string)payload["edit_session_id"]; }
            else if (re == updateId)
            {
                updateId = null;
                acknowledgedParameters = inFlightParameters;
                inFlightParameters = null;
            }
            else if (re == terminalId) terminalId = null;
            else if (re != null) return;
            LastState = (JObject)payload.DeepClone(); Sequence = (long?)payload["sequence"] ?? Sequence;
            Phase = (string)payload["phase"] ?? "conflict"; Notice = (string)payload["notice"] ?? "Native live edit state received";
            if (Phase == "committed" || Phase == "cancelled" || Phase == "conflict")
            { OutcomeUnknown |= Phase == "conflict"; Finish(Phase, Notice); return; }
            Pump(); Changed?.Invoke();
        }
        void Finish(string phase, string notice)
        {
            if (leaseId != null) Transmit(Envelope("lease.release", new JObject { ["lease_id"] = leaseId }));
            acquireId = beginId = updateId = terminalId = leaseId = null;
            latestParameters = null; Busy = false; Phase = phase; Notice = notice;
            if (parent != null) parent.ExternalEditBusy = false;
            Changed?.Invoke();
        }
    }
}
