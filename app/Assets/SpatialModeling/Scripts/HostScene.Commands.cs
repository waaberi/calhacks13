using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace SpatialModeling
{
    public sealed class CommandAnswer
    {
        public string RequestId, Op, Outcome, ErrorCode, Message;
        public long? Revision;
    }

    // #96: what the voice and menu code needs from the host connection.
    public partial class HostScene
    {
        public event Action SceneChanged;
        public event Action ConnectionLost;
        public event Action DocumentChanged;
        public event Action<CommandAnswer> CommandAnswered;

        string sessionId = "", hostEpoch = "", actorId = "", documentId = "", openEpoch = "";
        bool canEdit;
        readonly Dictionary<string, long> generations = new Dictionary<string, long>();
        readonly Dictionary<string, string> pendingOps = new Dictionary<string, string>();

        // True only while the scene is current and the host lets this connection edit.
        public bool CanSend => link != null && link.SocketOpen && connected && canEdit && status == Status.Connected;

        void Handle(HostEvent e)
        {
            bool wasConnected = connected;
            HandleCore(e);
            switch (e.Kind)
            {
                case HostEventKind.Welcome:
                    bool newDocument = documentId.Length > 0 && (documentId != e.DocumentId || openEpoch != e.OpenEpoch);
                    sessionId = e.SessionId; hostEpoch = e.HostEpoch; actorId = e.ActorId; canEdit = e.CanEdit;
                    documentId = e.DocumentId; openEpoch = e.OpenEpoch;
                    pendingOps.Clear();
                    if (newDocument) DocumentChanged?.Invoke();
                    break;
                case HostEventKind.Closed:
                    canEdit = false;
                    if (wasConnected) ConnectionLost?.Invoke();
                    // contracts/README.md, Outcomes: a connection lost before the result is an unknown outcome.
                    // Report it (never replay it), so the sender can say "check the model".
                    foreach (var re in new List<string>(pendingOps.Keys))
                        Answer(re, null, "unknown", "", "The connection closed before Blender answered.", null);
                    pendingOps.Clear();
                    break;
                case HostEventKind.Scene:
                    if (e.Snapshot) generations.Clear();
                    foreach (var id in e.Removed) generations.Remove(id);
                    foreach (var o in e.Objects) if (o.Generation.HasValue) generations[o.Id] = o.Generation.Value;
                    SceneChanged?.Invoke();
                    break;
                case HostEventKind.Result:
                    Answer(e.Re, e.Op, e.Outcome, e.Code, e.Text, e.Revision);
                    break;
                case HostEventKind.Error:
                    if (e.Re.Length > 0) Answer(e.Re, null, "rejected", e.Code, e.Text, null);
                    break;
            }
        }

        void Answer(string re, string op, string outcome, string code, string text, long? rev)
        {
            if (string.IsNullOrEmpty(re) || !pendingOps.TryGetValue(re, out var sentOp)) return;
            pendingOps.Remove(re);
            CommandAnswered?.Invoke(new CommandAnswer
            {
                RequestId = re,
                Op = string.IsNullOrEmpty(op) ? sentOp : op,
                Outcome = outcome,
                ErrorCode = code,
                Message = text,
                Revision = rev
            });
        }

        // Returns the request ID, or null when it could not be sent (not connected, read-only, stale scene,
        // or the target's generation is unknown). Never retry a command whose answer is lost.
        public string SendCommand(string op, string targetId, JObject args, string source)
        {
            if (!CanSend) return null;
            var payload = new JObject
            {
                ["session_id"] = sessionId,
                ["host_epoch"] = hostEpoch,
                ["document_id"] = documentId,
                ["open_epoch"] = openEpoch,
                ["actor_id"] = actorId,
                ["base_revision"] = revision,
                ["source"] = source,
                ["op"] = op,
                ["args"] = args ?? new JObject()
            };
            if (targetId != null)
            {
                if (!generations.TryGetValue(targetId, out var generation)) return null;
                payload["target"] = new JObject { ["id"] = targetId, ["generation"] = generation };
            }
            string id = link.Send("command", payload);
            if (id != null) pendingOps[id] = op;
            return id;
        }

        // The object is in the current scene (its generation is known, so a command can target it).
        public bool HasObject(string id) => id != null && generations.ContainsKey(id);

        // (object ID, name) of every object that is shown with a mesh: what the voice grammar may refer to.
        public void GetShownObjects(List<KeyValuePair<string, string>> into)
        {
            into.Clear();
            foreach (var pair in objects)
            {
                var renderer = pair.Value.GetComponent<MeshRenderer>();
                if (pair.Value.activeSelf && renderer != null && renderer.enabled)
                    into.Add(new KeyValuePair<string, string>(pair.Key, pair.Value.name));
            }
        }
        public bool TryGetBounds(string id, out Bounds bounds)
        {
            bounds = default;
            if (!objects.TryGetValue(id, out var go) || go == null) return false;
            var r = go.GetComponent<MeshRenderer>();
            if (r == null) return false;
            bounds = r.bounds;
            return true;
        }
    }
}