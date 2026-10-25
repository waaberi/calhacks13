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
        public bool SelectionSpecified;
        public string SelectedId;
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
        readonly HashSet<string> queuedCommands = new HashSet<string>();
        readonly HashSet<string> queuedAiCommands = new HashSet<string>();
        readonly HashSet<string> pendingVoiceHandoffs = new HashSet<string>();

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
                    queuedCommands.Clear(); queuedAiCommands.Clear();
                    pendingVoiceHandoffs.Clear();
                    if (newDocument) DocumentChanged?.Invoke();
                    Welcomed?.Invoke();
                    break;
                case HostEventKind.VoiceCandidates: VoiceCandidatesReceived?.Invoke(e.Re, e.Text); break;
                case HostEventKind.VoiceGrammar: VoiceGrammarReceived?.Invoke(e.Re, e.Text); break;
                case HostEventKind.Closed:
                    canEdit = false; welcomed = false;
                    pendingVoiceHandoffs.Clear();
                    if (wasConnected) ConnectionLost?.Invoke();
                    // contracts/README.md, Outcomes: a connection lost before the result is an unknown outcome.
                    // Report it (never replay it), so the sender can say "check the model".
                    foreach (var re in new List<string>(pendingOps.Keys))
                        if (queuedAiCommands.Contains(re))
                            Answer(re, null, "cancelled", "cancelled_before_send", "AI edit cancelled before native input release. No edit was sent.", null);
                        else Answer(re, null, "unknown", "", "The connection closed before Blender answered.", null);
                    pendingOps.Clear();
                    queuedCommands.Clear(); queuedAiCommands.Clear();
                    break;
                case HostEventKind.Scene:
                    if (e.Snapshot) generations.Clear();
                    foreach (var id in e.Removed) generations.Remove(id);
                    foreach (var o in e.Objects) generations[o.Id] = o.Generation;
                    SceneChanged?.Invoke();
                    break;
                case HostEventKind.Result:
                    Answer(e.Re, e.Op, e.Outcome, e.Code, e.Text, e.Revision, e.SelectionSpecified, e.SelectedId);
                    break;
                case HostEventKind.Error:
                    if (e.Re.Length > 0) { Answer(e.Re, null, "rejected", e.Code, e.Text, null); RequestFailed?.Invoke(e.Re, e.Code); }
                    break;
            }
        }

        void Answer(string re, string op, string outcome, string code, string text, long? rev, bool selectionSpecified = false, string selectedId = null)
        {
            if (string.IsNullOrEmpty(re) || !pendingOps.TryGetValue(re, out var sentOp)) return;
            pendingOps.Remove(re);
            queuedCommands.Remove(re); queuedAiCommands.Remove(re);
            CommandAnswered?.Invoke(new CommandAnswer
            {
                RequestId = re,
                Op = string.IsNullOrEmpty(op) ? sentOp : op,
                Outcome = outcome,
                ErrorCode = code,
                Message = text,
                SelectionSpecified = selectionSpecified,
                SelectedId = selectedId,
                Revision = rev
            });
        }

        // Returns the request ID, or null when it could not be sent (not connected, read-only, stale scene,
        // or the target's generation is unknown). Never retry a command whose answer is lost.
        public string SendCommand(string op, string targetId, JObject args, string source)
            => SendCommandCore(op,targetId,args,source,false,null);

        // The AI adapter owns cancellation only until this exact reviewed run
        // crosses the wire. Ordinary voice/menu commands retain their owners.
        public string SendAiCommand(string op, string targetId, JObject args, string source, Func<bool> stillCurrent = null)
            => op == "voice.run" ? SendCommandCore(op,targetId,args,source,true,stillCurrent) : null;

        public bool IsCommandQueued(string id) => id != null && pendingOps.ContainsKey(id) && queuedCommands.Contains(id);
        public bool IsCommandInFlight(string id) => id != null && pendingOps.ContainsKey(id) && !queuedCommands.Contains(id);
        public bool CancelQueuedAiCommand(string id, string reason = null)
        {
            if (id == null || !queuedAiCommands.Contains(id) || !IsCommandQueued(id)) return false;
            Answer(id,null,"cancelled","cancelled_before_send",
                string.IsNullOrEmpty(reason) ? "AI edit cancelled before native input release. No edit was sent." : reason, null);
            return true;
        }

        string SendCommandCore(string op, string targetId, JObject args, string source, bool aiOwned, Func<bool> stillCurrent)
        {
            if (!CanSend) return null;
            var preview = PreviewInteraction.Current;
            if (preview == null || !preview.NeedsNativeCommandHandoff)
                return SendCommandNow(op, targetId, args, source);
            string id = Guid.NewGuid().ToString("N");
            string identity = CommandIdentity;
            long queuedGeneration = 0;
            if (targetId != null && !generations.TryGetValue(targetId, out queuedGeneration)) return null;
            var frozenArgs = (JObject)(args ?? new JObject()).DeepClone();
            pendingOps[id] = op;
            queuedCommands.Add(id);
            if(aiOwned)queuedAiCommands.Add(id);
            preview.HandoffNativeCommand(() =>
            {
                // Cancellation/disconnection removes the exact queued token.
                // Native cleanup still finishes, but this callback cannot replay it.
                if (!pendingOps.ContainsKey(id) || !queuedCommands.Contains(id)) return;
                if(aiOwned&&stillCurrent!=null&&!stillCurrent())
                {Answer(id,op,"cancelled","cancelled_before_send","AI context changed before native input release. No edit was sent.",null);return;}
                string contextError = CommandHandoffContextError(identity, targetId, queuedGeneration);
                if (contextError != null)
                { Answer(id, op, "rejected", "stale_context", contextError, null); return; }
                if (SendCommandNow(op, targetId, frozenArgs, source, id) == null)
                    Answer(id, op, "rejected", "not_connected", "The scene or target changed before input cleanup finished; no edit was sent.", null);
            }, reason =>
            {
                // Defer synchronous admission failures until the caller has
                // registered this request ID (voice tracks only returned IDs).
                StartCoroutine(ReportHandoffFailure(id, op, reason));
            });
            return id;
        }

        System.Collections.IEnumerator ReportHandoffFailure(string id, string op, string reason)
        {
            yield return null;
            Answer(id, op, "rejected", "busy", reason, null);
        }

        string CommandIdentity => sessionId + "/" + hostEpoch + "/" + welcomeDocumentId + "/" + welcomeOpenEpoch + "/" + actorId;
        string CommandHandoffContextError(string identity, string targetId, long generation)
        {
            if (identity != CommandIdentity)
                return "The native session changed during input cleanup; no edit was sent.";
            if (targetId != null && (!generations.TryGetValue(targetId, out var current) || current != generation))
                return "The target changed during input cleanup; no edit was sent. Select it and issue a fresh edit.";
            return null;
        }

        string SendCommandNow(string op, string targetId, JObject args, string source, string requestId = null)
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
            string id;
            if (requestId == null) id = link.Send("command", payload);
            else
            {
                id = requestId;
                link.SendEnvelope(new JObject { ["v"] = 1, ["type"] = "command", ["id"] = id, ["payload"] = payload });
            }
            if (id != null)
            {
                pendingOps[id] = op;
                queuedCommands.Remove(id); queuedAiCommands.Remove(id);
            }
            return id;
        }

        // A voice.* request (voice.grammar_query, voice.resolve): the request ID, or null when it could not be sent.
        public string SendVoice(string type, JObject payload)
        {
            if (link == null || !link.SocketOpen || !welcomed) return null;
            var preview = PreviewInteraction.Current;
            if (type != "voice.resolve" || preview == null || !preview.NeedsNativeCommandHandoff)
                return link.Send(type, payload ?? new JObject());

            // Resolve after the same acknowledged input release as voice.run.
            // A plan must capture the fresh native scene, never the preview's
            // still-owned state. Keep the original target generation and refuse
            // a changed context rather than silently retargeting the words.
            string id = Guid.NewGuid().ToString("N");
            string identity = CommandIdentity;
            var frozen = (JObject)(payload ?? new JObject()).DeepClone();
            pendingVoiceHandoffs.Add(id);
            preview.HandoffNativeCommand(() =>
            {
                if (!pendingVoiceHandoffs.Remove(id)) return;
                if (VoiceHandoffContextError(identity, frozen) != null
                    || link == null || !link.SocketOpen || !welcomed)
                { RequestFailed?.Invoke(id, "stale_context"); return; }
                link.SendEnvelope(new JObject { ["v"] = 1, ["type"] = type, ["id"] = id, ["payload"] = frozen });
            }, reason => StartCoroutine(ReportVoiceHandoffFailure(id)));
            return id;
        }

        string VoiceHandoffContextError(string identity, JObject payload)
        {
            var target = payload?["target"];
            return CommandHandoffContextError(identity, (string)target?["id"], (long?)target?["generation"] ?? 0);
        }

        System.Collections.IEnumerator ReportVoiceHandoffFailure(string id)
        {
            // VoiceSession registers a request only after SendVoice returns.
            yield return null;
            if (pendingVoiceHandoffs.Remove(id)) RequestFailed?.Invoke(id, "busy");
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
        // AI data/pose tools can target visible native objects without a drawn
        // mesh (armatures, cameras, lights). Keep basic voice grammar unchanged.
        public void GetVisibleNativeObjects(List<KeyValuePair<string,string>> into)
        {
            into.Clear();
            foreach(var pair in objects)
                if(pair.Value!=null&&pair.Value.activeSelf)
                    into.Add(new KeyValuePair<string,string>(pair.Key,pair.Value.name));
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
