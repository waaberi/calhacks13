using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace SpatialModeling
{
    // P0 (#11): connects to the host add-on (or the fake host), draws the scene it sends,
    // and shows a clear message when the connection stops.
    public class HostScene : MonoBehaviour
    {
        [Header("Host connection (localhost only)")]
        [SerializeField] string host = "127.0.0.1";
        [SerializeField] int port = 8765;
        [SerializeField] string userName = "Jihyeon";

        [Header("Display only. Never changes the native model.")]
        [SerializeField] Vector3 rootPosition = new Vector3(0f, 1f, 1.5f);
        [SerializeField] float displayScale = 5f;

        enum Status { Connecting, Connected, NotResponding, Disconnected }

        readonly ConcurrentQueue<JObject> inbox = new ConcurrentQueue<JObject>();
        readonly Dictionary<string, GameObject> objects = new Dictionary<string, GameObject>();
        readonly object writeLock = new object();
        readonly Stopwatch clock = Stopwatch.StartNew();

        Thread thread;
        volatile bool running;
        volatile bool socketUp;
        volatile NetworkStream stream;
        volatile TcpClient client;
        volatile string lastError = "";
        long lastReceiveMs;
        string appVersion;
        Transform root;
        bool everConnected, gotSnapshot;
        long revision;
        float nextPing;
        Status status = Status.Connecting;

        void Awake()
        {
            appVersion = Application.version;
            root = new GameObject("HostSceneRoot").transform;
            root.position = rootPosition;
            root.localScale = Vector3.one * displayScale;
        }

        void OnEnable()
        {
            running = true;
            thread = new Thread(Loop) { IsBackground = true };
            thread.Start();
        }

        void OnDisable()
        {
            running = false;
            try { client?.Close(); } catch { }
        }

        void Update()
        {
            while (inbox.TryDequeue(out var msg)) Handle(msg);

            if (socketUp) everConnected = true;
            long silence = clock.ElapsedMilliseconds - Interlocked.Read(ref lastReceiveMs);
            if (!socketUp) status = everConnected ? Status.Disconnected : Status.Connecting;
            else if (!gotSnapshot) status = Status.Connecting;
            else if (silence > 6000) status = Status.NotResponding;
            else status = Status.Connected;

            if (socketUp && Time.unscaledTime >= nextPing)
            {
                nextPing = Time.unscaledTime + 2f;
                Send(Make("ping", new JObject()));
            }
        }

        void OnGUI()
        {
            string text;
            switch (status)
            {
                case Status.Connected: text = $"Connected - revision {revision}"; break;
                case Status.NotResponding: text = "Blender is not responding. Edits are disabled."; break;
                case Status.Disconnected: text = $"Disconnected. Showing the last scene (stale). Reconnecting...\n{lastError}"; break;
                default: text = $"Connecting to Blender at {host}:{port} ...\n{lastError}"; break;
            }
            var style = new GUIStyle(GUI.skin.label) { fontSize = 26 };
            style.normal.textColor = status == Status.Connected ? Color.white : new Color(1f, 0.6f, 0.2f);
            GUI.Label(new Rect(20, 20, 1400, 140), text, style);
        }

        // ---------- network thread ----------

        void Loop()
        {
            while (running)
            {
                try
                {
                    using (var c = new TcpClient())
                    {
                        client = c;
                        c.Connect(host, port);
                        c.NoDelay = true;
                        var ns = c.GetStream();
                        stream = ns;
                        Interlocked.Exchange(ref lastReceiveMs, clock.ElapsedMilliseconds);
                        socketUp = true;
                        Send(Make("hello", new JObject
                        {
                            ["role"] = "vr",
                            ["name"] = userName,
                            ["app"] = new JObject { ["name"] = "SpatialModeling", ["version"] = appVersion }
                        }));
                        using (var reader = new StreamReader(ns, new UTF8Encoding(false)))
                        {
                            string line;
                            while (running && (line = reader.ReadLine()) != null)
                            {
                                Interlocked.Exchange(ref lastReceiveMs, clock.ElapsedMilliseconds);
                                if (line.Length == 0) continue;
                                try { inbox.Enqueue(JObject.Parse(line)); } catch (JsonException) { }
                            }
                        }
                        lastError = "The host closed the connection.";
                    }
                }
                catch (Exception e) { lastError = e.Message; }

                socketUp = false;
                stream = null;
                inbox.Enqueue(new JObject { ["type"] = "_closed" });
                for (int i = 0; i < 20 && running; i++) Thread.Sleep(100); // retry every 2 s
            }
        }

        static JObject Make(string type, JObject payload) => new JObject
        {
            ["v"] = 1,
            ["type"] = type,
            ["id"] = Guid.NewGuid().ToString("N"),
            ["payload"] = payload
        };

        void Send(JObject msg)
        {
            var s = stream;
            if (s == null) return;
            var bytes = Encoding.UTF8.GetBytes(msg.ToString(Formatting.None) + "\n");
            lock (writeLock) { try { s.Write(bytes, 0, bytes.Length); } catch { } }
        }

        // ---------- main thread: apply messages ----------

        void Handle(JObject msg)
        {
            string type = (string)msg["type"];
            var p = msg["payload"] as JObject;
            switch (type)
            {
                case "_closed": gotSnapshot = false; break;
                case "welcome": lastError = ""; break;
                case "scene.snapshot": ClearScene(); ApplyPayload(p); gotSnapshot = true; break;
                case "scene.update": ApplyPayload(p); break;
                case "error":
                    lastError = $"{(string)p?["code"]}: {(string)p?["message"]}";
                    Debug.LogWarning("Host error " + lastError);
                    break;
            }
        }

        void ApplyPayload(JObject p)
        {
            if (p == null) return;
            if (p["document"] is JObject d) revision = (long?)d["revision"] ?? revision;
            if (p["removed"] is JArray removed) foreach (var r in removed) Remove((string)r);
            if (p["objects"] is JArray arr) foreach (var o in arr) ApplyObject((JObject)o);
        }

        void ApplyObject(JObject o)
        {
            string id = (string)o["id"];
            if (string.IsNullOrEmpty(id)) return;

            if (!objects.TryGetValue(id, out var go))
            {
                go = GameObject.CreatePrimitive(PrimitiveType.Cube); // gives us the default URP material
                Destroy(go.GetComponent<Collider>());                // selection colliders come in P2
                go.GetComponent<MeshFilter>().sharedMesh = null;
                go.transform.SetParent(root, false);
                objects[id] = go;
            }
            go.name = (string)o["name"] ?? id;
            go.SetActive((bool?)o["visible"] ?? true);

            // Wire transforms are world space, so objects stay flat under the display root.
            if (o["transform"] is JObject t)
            {
                var loc = (JArray)t["location"]; var rot = (JArray)t["rotation"]; var sc = (JArray)t["scale"];
                go.transform.localPosition = ToUnity((float)loc[0], (float)loc[1], (float)loc[2]);
                // Blender quaternion is [w, x, y, z]; Y and Z swap, so the vector part flips sign.
                go.transform.localRotation = new Quaternion(-(float)rot[1], -(float)rot[3], -(float)rot[2], (float)rot[0]);
                go.transform.localScale = new Vector3((float)sc[0], (float)sc[2], (float)sc[1]);
            }

            var mf = go.GetComponent<MeshFilter>();
            var mr = go.GetComponent<MeshRenderer>();
            if (o["mesh"] is JObject m)
            {
                if (mf.sharedMesh != null) Destroy(mf.sharedMesh);
                mf.sharedMesh = BuildMesh(m, go.name);
                mr.enabled = true;
            }
            else if (o["mesh"] != null && o["mesh"].Type == JTokenType.Null)
            {
                if (mf.sharedMesh != null) Destroy(mf.sharedMesh);
                mf.sharedMesh = null;   // camera, light, empty: nothing to draw
                mr.enabled = false;
            }

            if (o["color"] is JArray c && c.Count >= 3)
                mr.material.color = new Color((float)c[0], (float)c[1], (float)c[2], c.Count > 3 ? (float)c[3] : 1f).gamma;
        }

        // The one place that converts Blender (right-handed, Z up) to Unity (left-handed, Y up).
        // PROVISIONAL: Waaberi documents the official conversion in #38. Change only here.
        static Vector3 ToUnity(float x, float y, float z) => new Vector3(x, z, y);

        static Mesh BuildMesh(JObject m, string name)
        {
            var pos = (JArray)m["positions"];
            var nor = m["normals"] as JArray;
            var idx = (JArray)m["indices"];
            int n = pos.Count / 3;

            var verts = new Vector3[n];
            for (int i = 0; i < n; i++)
                verts[i] = ToUnity((float)pos[3 * i], (float)pos[3 * i + 1], (float)pos[3 * i + 2]);

            var tris = new int[idx.Count];
            for (int i = 0; i + 2 < tris.Length; i += 3)   // swap two corners: the axis swap reverses the winding
            {
                tris[i] = (int)idx[i];
                tris[i + 1] = (int)idx[i + 2];
                tris[i + 2] = (int)idx[i + 1];
            }

            var mesh = new Mesh { name = name };
            if (n > 65535) mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
            mesh.vertices = verts;
            mesh.triangles = tris;
            if (nor != null && nor.Count == pos.Count)
            {
                var norms = new Vector3[n];
                for (int i = 0; i < n; i++)
                    norms[i] = ToUnity((float)nor[3 * i], (float)nor[3 * i + 1], (float)nor[3 * i + 2]);
                mesh.normals = norms;
            }
            else mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        void Remove(string id)
        {
            if (!objects.TryGetValue(id, out var go)) return;
            var mf = go.GetComponent<MeshFilter>();
            if (mf != null && mf.sharedMesh != null) Destroy(mf.sharedMesh);
            Destroy(go);
            objects.Remove(id);
        }

        void ClearScene()
        {
            foreach (var id in new List<string>(objects.Keys)) Remove(id);
        }
    }
}