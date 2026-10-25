using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // A draft builder only. NativeEditSession owns permissions, receipts, history
    // and transmission; the bridge owns fresh native mode/modal admission.
    public sealed class NativeObjectTools : IDisposable
    {
        readonly NativeEditSession session;
        static readonly double[] moveSteps = { .001, .01, .1 };
        static readonly int[] turnSteps = { 15, 45, 90 };
        static readonly double[] primitiveSizes = { .02, .05, .1 };
        int moveIndex = 1, turnIndex = 1, sizeIndex = 1;
        string identity = "", ownAddRequest, previousSubmittedId;
        JObject ownAddDraft;
        bool seenTarget, invalidatedTarget, disposed;

        public string TargetId { get; private set; } = "";
        public string Notice { get; private set; } = "Choose a native object";
        public double MoveStepMeters => moveSteps[moveIndex];
        public int TurnDegrees => turnSteps[turnIndex];
        public double PrimitiveSizeMeters => primitiveSizes[sizeIndex];
        public bool TargetAvailable => !invalidatedTarget && TargetId.Length > 0 && session.Objects.ContainsKey(TargetId);
        public string TargetLabel
        {
            get
            {
                if (TargetId.Length == 0) return "No object selected";
                if (invalidatedTarget) return "Removed object · choose another target";
                if (!session.Objects.TryGetValue(TargetId, out var target)) return "Waiting for the created object's native scene record";
                return (string)target["name"] ?? TargetId;
            }
        }

        public NativeObjectTools(NativeEditSession session)
        {
            this.session = session ?? throw new ArgumentNullException(nameof(session));
            identity = IdentityKey();
            session.Changed += Synchronize;
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            session.Changed -= Synchronize;
        }

        public void CycleMoveStep() { moveIndex = (moveIndex + 1) % moveSteps.Length; }
        public void CycleTurnDegrees() { turnIndex = (turnIndex + 1) % turnSteps.Length; }
        public void CyclePrimitiveSize() { sizeIndex = (sizeIndex + 1) % primitiveSizes.Length; }

        string IdentityKey()
        {
            var value = session.RequestIdentity;
            return value == null ? "" : string.Join("/", new[] { (string)value["session_id"], (string)value["host_epoch"],
                (string)value["document_id"], (string)value["open_epoch"], (string)value["actor_id"] });
        }

        void ClearTarget()
        {
            TargetId = ""; seenTarget = invalidatedTarget = false;
            ownAddDraft = null; ownAddRequest = previousSubmittedId = null;
            Notice = "Choose a native object";
        }

        public void Reset() { ClearTarget(); identity = IdentityKey(); }

        void Synchronize()
        {
            string current = IdentityKey();
            if (identity != current || !session.Ready)
            {
                ClearTarget(); identity = current;
                return;
            }
            // Apply assigns the ID while retaining the exact draft instance.
            // Capture it here, before a result can clear Draft. Another tool's
            // later draft or receipt must never be mistaken for this creation.
            if (ownAddDraft != null)
            {
                if (!ReferenceEquals(session.Draft, ownAddDraft)) ownAddDraft = null;
                else if (session.Busy && !string.IsNullOrEmpty(session.LastSubmittedId)
                    && session.LastSubmittedId != previousSubmittedId)
                { ownAddRequest = session.LastSubmittedId; ownAddDraft = null; }
            }
            if (TargetId.Length == 0 || invalidatedTarget) return;
            if (session.Objects.ContainsKey(TargetId)) seenTarget = true;
            else if (seenTarget)
            { invalidatedTarget = true; Notice = "The selected object was removed; choose a new target"; }
        }

        public bool SelectRelative(int direction)
        {
            Synchronize();
            if (direction == 0 || !session.Ready || session.Busy) return false;
            var ids = new List<string>(session.Objects.Keys);
            ids.Sort((a, b) => {
                int names = StringComparer.OrdinalIgnoreCase.Compare((string)session.Objects[a]["name"] ?? a,
                    (string)session.Objects[b]["name"] ?? b);
                return names != 0 ? names : StringComparer.Ordinal.Compare(a, b);
            });
            if (ids.Count == 0) { Notice = "No native objects are available"; return false; }
            int at = ids.IndexOf(TargetId);
            long start = at >= 0 ? at : direction > 0 ? -1 : 0;
            int next = (int)(((start + direction) % ids.Count + ids.Count) % ids.Count);
            session.Select(ids[next]);
            if (session.SelectedId != ids[next]) return false;
            TargetId = ids[next]; seenTarget = true; invalidatedTarget = false;
            ownAddDraft = null; ownAddRequest = null;
            Notice = "Selected " + TargetLabel;
            return true;
        }

        public bool Stage(string action)
        {
            Synchronize();
            string op;
            JObject args;
            bool targeted = true;
            if (action == "add.cube" || action == "add.sphere" || action == "add.cylinder")
            {
                op = "object.add"; targeted = false;
                double size = PrimitiveSizeMeters;
                // All lengths are native world metres. For a cylinder X/Y are
                // its diameter and Z its depth; this palette makes them equal.
                args = new JObject { ["primitive"] = action.Substring(4), ["location"] = new JArray(0, 0, 0),
                    ["dimensions"] = new JArray(size, size, size) };
            }
            else if (action != null && (action.StartsWith("move.", StringComparison.Ordinal)
                || action.StartsWith("turn.", StringComparison.Ordinal)) && action.Length == 7
                && "xyz".IndexOf(action[5]) >= 0 && (action[6] == '+' || action[6] == '-'))
            {
                int axis = "xyz".IndexOf(action[5]);
                int sign = action[6] == '+' ? 1 : -1;
                if (action.StartsWith("move.", StringComparison.Ordinal))
                {
                    var by = new double[3]; by[axis] = sign * MoveStepMeters;
                    op = "object.move"; args = new JObject { ["by"] = new JArray(by) };
                }
                else
                {
                    op = "object.rotate";
                    args = new JObject { ["by"] = new JObject { ["axis"] = "XYZ"[axis].ToString(),
                        ["angle"] = sign * TurnDegrees * Math.PI / 180.0 } };
                }
            }
            else if (action == "scale.down" || action == "scale.up")
            {
                double factor = action == "scale.up" ? 1.1 : 1.0 / 1.1;
                op = "object.scale"; args = new JObject { ["by"] = new JArray(factor, factor, factor) };
            }
            else if (action == "delete") { op = "object.delete"; args = new JObject(); }
            else { Notice = "Unknown object action"; return false; }

            if (targeted)
            {
                if (!TargetAvailable) { Notice = TargetLabel + "; explicitly choose a current native object"; return false; }
                session.Select(TargetId);
                if (session.SelectedId != TargetId) return false;
            }
            if (!session.BeginDraft(op, args, targeted)) { Notice = session.Notice; return false; }
            ownAddDraft = op == "object.add" ? session.Draft : null;
            ownAddRequest = null; previousSubmittedId = session.LastSubmittedId;
            Notice = "Native object draft staged; Apply still requires the shared transaction";
            return true;
        }

        // Called after NativeEditSession.Receive. It observes, never sends or
        // acquires permissions and never changes native geometry optimistically.
        public void Observe(JObject message)
        {
            Synchronize();
            if ((string)message?["type"] == "welcome" || (string)message?["type"] == "connection.closed")
            { ClearTarget(); return; }
            if (TargetId.Length > 0 && message?["payload"]?["removed"] is JArray removed)
                foreach (var id in removed)
                    if ((string)id == TargetId)
                    { invalidatedTarget = true; Notice = "The selected object was removed; choose a new target"; }
            if (!session.Ready || ownAddRequest == null || (string)message?["type"] != "result") return;
            var receipt = message["payload"] as JObject;
            if (receipt == null || (string)receipt["request_id"] != ownAddRequest
                || session.LastSubmittedId != ownAddRequest || !JToken.DeepEquals(session.LastReceipt, receipt)) return;
            if ((string)receipt["outcome"] == "pending") return;
            ownAddRequest = null;
            if ((string)receipt["outcome"] != "applied" || (string)receipt["op"] != "object.add"
                || !(receipt["created"] is JArray ids) || ids.Count == 0 || ids[0].Type != JTokenType.String
                || !Guid.TryParseExact((string)ids[0], "N", out _)) return;
            TargetId = (string)ids[0]; invalidatedTarget = false;
            seenTarget = session.Objects.ContainsKey(TargetId);
            Notice = seenTarget ? "Selected created " + TargetLabel : "Waiting for the created object's exact native UUID";
        }
    }
}
