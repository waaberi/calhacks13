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
        // P4 voice (#146): the host resolver's messages, and errors answering any request (not only commands).
        public event Action Welcomed;
        public event Action<string, string> VoiceCandidatesReceived;   // (re, payload JSON)
        public event Action<string, string> VoiceGrammarReceived;      // (re, payload JSON)
        public event Action<string, string> RequestFailed;             // (re, error code)

        string sessionId = "", hostEpoch = "", actorId = "";
        // The document named by welcome. Kept apart from HostScene.documentId/openEpoch, which track
        // the applied snapshot: P2 compares those to reset the scene and placement on a new document.
        string welcomeDocumentId = "", welcomeOpenEpoch = "";
        bool canEdit;
        bool welcomed;   // welcome arrived on this connection: voice.* requests may go before the snapshot
        readonly Dictionary<string, long> generations = new Dictionary<string, long>();
        readonly Dictionary<string, string> pendingOps = new Dictionary<string, string>();

        // True only while the scene is current and the host lets this connection edit.
        public bool CanSend => link != null && link.SocketOpen && connected && canEdit && status == Status.Connected;

        internal void Handle(HostEvent e)
        {
            bool wasConnected = connected;
            HandleCore(e);
            switch (e.Kind)
            {
                case HostEventKind.Welcome:
                    bool newDocument = welcomeDocumentId.Length > 0 && (welcomeDocumentId != e.DocumentId || welcomeOpenEpoch != e.OpenEpoch);
                    welcomed = true;
                    sessionId = e.SessionId; hostEpoch = e.HostEpoch; actorId = e.ActorId; canEdit = e.CanEdit;
                    welcomeDocumentId = e.DocumentId; welcomeOpenEpoch = e.OpenEpoch;
                    pendingOps.Clear();
                    if (newDocument) DocumentChanged?.Invoke();
                    Welcomed?.Invoke();
                    break;
                case HostEventKind.VoiceCandidates: VoiceCandidatesReceived?.Invoke(e.Re, e.Text); break;
                case HostEventKind.VoiceGrammar: VoiceGrammarReceived?.Invoke(e.Re, e.Text); break;
                case HostEventKind.Closed:
                    canEdit = false; welcomed = false;
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
                    foreach (var o in e.Objects) generations[o.Id] = o.Generation;
                    SceneChanged?.Invoke();
                    break;
                case HostEventKind.Result:
                    Answer(e.Re, e.Op, e.Outcome, e.Code, e.Text, e.Revision);
                    break;
                case HostEventKind.Error:
                    if (e.Re.Length > 0) { Answer(e.Re, null, "rejected", e.Code, e.Text, null); RequestFailed?.Invoke(e.Re, e.Code); }
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
                ["document_id"] = welcomeDocumentId,
                ["open_epoch"] = welcomeOpenEpoch,
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

        // A voice.* request (voice.grammar_query, voice.resolve): the request ID, or null when it could not be sent.
        public string SendVoice(string type, JObject payload)
        {
            if (link == null || !link.SocketOpen || !welcomed) return null;
            return link.Send(type, payload ?? new JObject());
        }

        public bool TryGetGeneration(string id, out long generation)
        {
            generation = 0;
            return id != null && generations.TryGetValue(id, out generation);
        }

        // The object is in the current scene (its generation is known, so a command can target it).
        public bool HasObject(string id) => id != null && generations.ContainsKey(id);
        public bool HasCurrentScene => connected && status == Status.Connected;

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
