using System;
using UnityEngine;

namespace SpatialModeling
{
    // Runs after HostScene: its decoder applies each scene before delivering the raw receipt.
    [DefaultExecutionOrder(50)]
    public sealed class NativeEditBridge : MonoBehaviour
    {
        public NativeEditSession Session { get; } = new NativeEditSession();
        HostScene scene;
        bool connected;
        double pendingSince = -1;

        void OnEnable()
        {
            scene = FindFirstObjectByType<HostScene>();
            if (scene == null) return;
            scene.HostEventReceived += OnHostEvent;
            Session.Send = envelope => scene.Link?.SendEnvelope(envelope);
        }

        void OnHostEvent(HostEvent e)
        {
            Session.SceneCurrent = scene.IsCurrent;
            if (e.Kind == HostEventKind.Closed) { connected = false; Session.Disconnect(e.Text); }
            if (e.Kind == HostEventKind.InvalidScene) { Session.Disconnect("Native scene was rejected; waiting for a valid reconnect snapshot"); return; }
            if (e.RawMessage != null) Session.Receive(e.RawMessage);
        }

        void Update()
        {
            if (scene == null) return;
            Session.SceneCurrent = scene.IsCurrent;
            bool alive = scene.Link != null && scene.Link.SocketOpen && scene.Link.SilenceMs <= 6000;
            if (!alive && connected) Session.Disconnect("Blender is not responding");
            connected = alive;
            if (!Session.Busy) pendingSince = -1;
            else if (pendingSince < 0) pendingSince = Time.realtimeSinceStartupAsDouble;
            else if (Time.realtimeSinceStartupAsDouble - pendingSince > 15 && !Session.OutcomeUnknown) Session.Timeout();
        }

        void OnDisable()
        {
            if (scene != null) scene.HostEventReceived -= OnHostEvent;
            Session.Send = null;
            Session.Disconnect("Editing interface closed");
        }
    }
}
