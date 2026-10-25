using System;
using System.Collections.Generic;
using System.Reflection;
using SpatialModeling;
using UnityEngine;

public static class MultiUserIntegrationChecks
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static void Check(bool value, string why) { if (!value) throw new Exception("MULTI_USER: " + why); }
    static void Set(object target, string field, object value) => target.GetType().GetField(field, Private).SetValue(target, value);
    static string Text(RemotePresencePanel p) => (string)typeof(RemotePresencePanel).GetMethod("BuildText", Private).Invoke(p, null);
    public static void Run()
    {
        var go = new GameObject("isolated collaboration host");
        var panelGo = new GameObject("isolated collaboration panel");
        try
        {
            var h = go.AddComponent<HostScene>();
            var panel = panelGo.AddComponent<RemotePresencePanel>(); panel.host = h;
            Set(h, "actorId", "local-vr");
            var participants = (List<ActorInfo>)typeof(HostScene).GetField("participants", Private).GetValue(h);
            var leases = (List<LeaseInfo>)typeof(HostScene).GetField("leases", Private).GetValue(h);
            var local = new ActorInfo { Id = "local-vr", Name = "Talia", Role = "vr" };
            var desktop = new ActorInfo { Id = "host", Name = "Desktop", Role = "host" };
            participants.Add(desktop); participants.Add(local);
            leases.Add(new LeaseInfo { Id = "native-preview", Mode = "exclusive", Owner = desktop });
            Check(!panel.HasRemoteParticipant && Text(panel) == "", "host plus same-user VR/native preview adds no competing-person UI");
            var foreign = new ActorInfo { Id = "foreign", Name = "Lee", Role = "blender-client" };
            participants.Add(foreign);
            leases.Add(new LeaseInfo { Id = "foreign-reservation", Mode = "shared", Owner = foreign });
            Check(panel.HasRemoteParticipant && Text(panel).Contains("Lee") && Text(panel).Contains("active writers"), "real remote writer and conflict ownership remain visible");
            Check(!Text(panel).Contains("Two people"), "connection counts never invent human identity");
            // Exercise actual HostScene disconnect/welcome handlers, preserving their existing cancellations.
            var eventType = typeof(HostScene).Assembly.GetType("SpatialModeling.HostEvent");
            var kindType = typeof(HostScene).Assembly.GetType("SpatialModeling.HostEventKind");
            Action<string> handle = kind => {
                var e = Activator.CreateInstance(eventType, new object[] { Enum.Parse(kindType, kind) });
                typeof(HostScene).GetMethod("Handle", Private).Invoke(h, new[] { e });
            };
            handle("Closed");
            Check(h.Participants.Count == 0 && h.Leases.Count == 0, "disconnect clears foreign session and lease display");
            participants.Add(foreign); leases.Add(new LeaseInfo { Id = "stale", Owner = foreign });
            handle("Welcome");
            Check(h.Participants.Count == 0 && h.Leases.Count == 0, "new welcome cannot inherit old host/document reservations");
            Debug.Log("MULTI_USER_INTEGRATION_CHECK PASS single-user native preview hidden/foreign writer visible/honest connection identity/disconnect+new-welcome clearing; no network or native model edits");
        }
        finally { UnityEngine.Object.DestroyImmediate(panelGo); UnityEngine.Object.DestroyImmediate(go); }
    }
}
