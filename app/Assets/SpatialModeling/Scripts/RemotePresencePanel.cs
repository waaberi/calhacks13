using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace SpatialModeling
{
    // #109: who is in the session, who is editing what, what the others just did, and a stale-scene warning.
    // Created at startup next to HostScene, so no scene edit is needed.
    public class RemotePresencePanel : MonoBehaviour
    {
        public HostScene host;
        public Vector3 offset = new Vector3(0.55f, 0.20f, 1.1f);   // head space: right of HostScene's status panel
        public float activitySeconds = 6f;

        TextMesh text;
        string shown = "";
        string activityLine = "";
        float activityUntil;
        string identity = "";
        bool visible, hadRemoteParticipant;
        // Remember only this session's live reservations, not every historical lease.
        readonly HashSet<string> seenLeases = new HashSet<string>();
        readonly HashSet<string> editors = new HashSet<string>();
        readonly Dictionary<string, TextMesh> tags = new Dictionary<string, TextMesh>();
        readonly HashSet<string> wanted = new HashSet<string>();
        readonly List<KeyValuePair<string, string>> shownObjects = new List<KeyValuePair<string, string>>();
        readonly StringBuilder sb = new StringBuilder();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Create()
        {
            var h = FindAnyObjectByType<HostScene>();
            if (h == null) return;
            new GameObject("RemotePresencePanel").AddComponent<RemotePresencePanel>().host = h;
        }

        void Awake()
        {
            text = gameObject.AddComponent<TextMesh>();
            text.fontSize = 48; text.characterSize = 0.006f; text.anchor = TextAnchor.UpperLeft;
            text.color = Color.white;
            VoiceUiAdapter.SetupText(text, gameObject);
        }

        void Start()
        {
            if (host == null) host = FindAnyObjectByType<HostScene>();
            if (host == null) { enabled = false; return; }
            host.ActivityReceived += OnActivity;
            host.SessionChanged += OnSession;
        }

        void OnDestroy()
        {
            if (host != null)
            {
                host.ActivityReceived -= OnActivity;
                host.SessionChanged -= OnSession;
            }
            foreach (var tag in tags.Values) if (tag != null) Destroy(tag.gameObject);
            tags.Clear();
        }

        void OnActivity(ActivityNote n)
        {
            activityLine = n.ActorName + ": " + (n.Summary.Length > 0 ? n.Summary : n.Op);
            activityUntil = Time.time + activitySeconds;
        }

        // A lease you haven't seen before is the notice that someone started editing (contracts/README.md).
        void OnSession()
        {
            string currentIdentity = host.MyActorId;
            if (identity != currentIdentity)
            {
                identity = currentIdentity;
                seenLeases.Clear(); activityLine = ""; activityUntil = 0;
                hadRemoteParticipant = false;
            }
            if (HasRemoteParticipant) hadRemoteParticipant = true;
            else if (!host.SceneIsStale) hadRemoteParticipant = false;
            var live = new HashSet<string>();
            foreach (var l in host.Leases) live.Add(l.Id);
            seenLeases.RemoveWhere(id => !live.Contains(id));
            foreach (var l in host.Leases)
                if (seenLeases.Add(l.Id) && l.Owner.Id != host.MyActorId)
                {
                    activityLine = l.Owner.Name + " started editing " + TargetNames(l);
                    activityUntil = Time.time + activitySeconds;
                }
        }

        bool IsShown(string id)
        {
            foreach (var o in shownObjects) if (o.Key == id) return true;
            return false;
        }

        string TargetNames(LeaseInfo l)
        {
            if (l.Mode == "exclusive") return "the whole document";
            var names = new List<string>();
            foreach (var t in l.Targets) { string n = host.ObjectName(t); if (n != null) names.Add(n); }
            return names.Count > 0 ? string.Join(", ", names) : "objects";
        }

        public bool HasRemoteParticipant
        {
            get
            {
                if (host == null) return false;
                foreach (var p in host.Participants)
                    if (p.Id != host.MyActorId && p.Role != "host") return true;
                return false;
            }
        }

        string BuildText()
        {
            // The host desktop and its local VR preview are connections, not two people.
            if (!HasRemoteParticipant && !(hadRemoteParticipant && host.SceneIsStale)) return "";
            sb.Length = 0;
            if (host.SceneIsStale)
                sb.Append("Disconnected: this scene is stale.\nEdits are off until Blender is back.");
            else
            {
                sb.Append("Session connections: ").Append(host.Participants.Count);
                foreach (var p in host.Participants)
                    sb.Append('\n').Append(p.Name).Append(p.Id == host.MyActorId ? " (you)" : " (" + p.Role + ")");
                editors.Clear();
                foreach (var l in host.Leases)
                {
                    editors.Add(l.Owner.Id);
                    if (l.Owner.Id != host.MyActorId)
                        sb.Append('\n').Append(l.Owner.Name).Append(" is editing: ").Append(TargetNames(l));
                }
                // contracts/README.md, Leases and presence.
                if (editors.Count >= 2) sb.Append("\n").Append(editors.Count).Append(" active writers");
            }
            if (activityLine.Length > 0 && Time.time < activityUntil) sb.Append("\n\n").Append(activityLine);
            return sb.ToString();
        }

        void LateUpdate()
        {
            var cam = Camera.main;
            if (host == null || cam == null) return;
            var head = cam.transform;
            host.GetShownObjects(shownObjects);
            string t = BuildText();
            bool show = t.Length > 0;
            if (show && !visible)
            {
                transform.position = head.TransformPoint(offset);
                transform.rotation = Quaternion.LookRotation(transform.position - head.position, head.up);
            }
            visible = show;
            if (t != shown) { shown = t; text.text = t; VoiceUiAdapter.FitBacking(text); }
            text.color = host.SceneIsStale ? new Color(1f, 0.7f, 0.25f) : Color.white;
            UpdateTags(head);
        }

        // The owner's name over every object another participant is editing.
        void UpdateTags(Transform head)
        {
            wanted.Clear();
            foreach (var l in host.Leases)
            {
                if (!HasRemoteParticipant || host.SceneIsStale || l.Owner.Id == host.MyActorId || l.Mode == "exclusive") continue;
                foreach (var id in l.Targets)
                {
                    // Only over objects drawn with a mesh: a camera or a hidden object has nowhere to put it.
                    if (!IsShown(id) || !host.TryGetBounds(id, out Bounds b)) continue;
                    wanted.Add(id);
                    if (!tags.TryGetValue(id, out var tm) || tm == null)
                    {
                        var go = new GameObject("LeaseTag");
                        tm = go.AddComponent<TextMesh>();
                        tm.fontSize = 48; tm.characterSize = 0.008f; tm.anchor = TextAnchor.LowerCenter;
                        tm.color = new Color(1f, 0.45f, 0.7f);
                        VoiceUiAdapter.SetupText(tm, go);
                        tags[id] = tm;
                    }
                    if (tm.text != l.Owner.Name) { tm.text = l.Owner.Name; VoiceUiAdapter.FitBacking(tm); }
                    var pos = new Vector3(b.center.x, b.max.y + 0.03f, b.center.z);
                    tm.transform.position = pos;
                    tm.transform.rotation = Quaternion.LookRotation(pos - head.position, head.up);
                }
            }
            var drop = new List<string>();
            foreach (var kv in tags) if (!wanted.Contains(kv.Key)) drop.Add(kv.Key);
            foreach (var id in drop)
            {
                if (tags[id] != null) Destroy(tags[id].gameObject);
                tags.Remove(id);
            }
        }
    }
}
