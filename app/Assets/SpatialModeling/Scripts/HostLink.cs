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

namespace SpatialModeling
{
    // One connection to the host, reconnecting every 2 s, on its own thread. It reads, decodes and pings
    // there, so a large snapshot or a paused main thread doesn't stall the heartbeat. HostScene drains
    // Events on the main thread. Uses no Unity API besides value types (Vector3, Quaternion, Color).
    sealed class HostLink
    {
        public const int MaxLineBytes = 16 * 1024 * 1024;   // contract: a line over 16 MiB is refused
        const int PingMs = 2000, RetryMs = 2000;
        static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);

        public readonly ConcurrentQueue<HostEvent> Events = new ConcurrentQueue<HostEvent>();

        readonly string host;
        readonly int port;
        readonly JObject hello;
        readonly object writeLock = new object();
        readonly Stopwatch clock = Stopwatch.StartNew();
        readonly Thread thread;
        readonly Timer pingTimer;
        volatile bool running = true;
        volatile TcpClient client;
        volatile NetworkStream stream;
        long lastReceiveMs;

        public HostLink(string host, int port, JObject helloPayload)
        {
            this.host = host;
            this.port = port;
            hello = helloPayload;
            thread = new Thread(Run) { IsBackground = true, Name = "HostLink" };
            thread.Start();
            pingTimer = new Timer(_ => Send("ping", new JObject()), null, PingMs, PingMs);
        }

        public bool SocketOpen => stream != null;
        public long SilenceMs => clock.ElapsedMilliseconds - Interlocked.Read(ref lastReceiveMs);

        public void Reconnect() { try { client?.Close(); } catch (SocketException) { } }

        // Ends this link for good: its thread exits and it never posts another event.
        public void Stop()
        {
            running = false;
            pingTimer.Dispose();
            try { client?.Close(); } catch { }
        }

        void Run()
        {
            while (running)
            {
                string reason;
                try
                {
                    using (var c = new TcpClient())
                    {
                        client = c;
                        c.Connect(host, port);
                        c.NoDelay = true;
                        var ns = c.GetStream();
                        Interlocked.Exchange(ref lastReceiveMs, clock.ElapsedMilliseconds);
                        stream = ns;
                        Post(new HostEvent(HostEventKind.Opened));
                        Send("hello", hello);
                        reason = ReadLines(ns);
                    }
                }
                catch (Exception e) { reason = e.Message; }

                stream = null;
                client = null;
                if (!running) return;
                Post(new HostEvent(HostEventKind.Closed) { Text = reason });
                for (int i = 0; i < RetryMs / 100 && running; i++) Thread.Sleep(100);
            }
        }

        string ReadLines(Stream s)
        {
            var buf = new byte[64 * 1024];
            var line = new MemoryStream();
            while (running)
            {
                int n = s.Read(buf, 0, buf.Length);
                if (n <= 0) return "The host closed the connection.";
                Interlocked.Exchange(ref lastReceiveMs, clock.ElapsedMilliseconds);
                int start = 0;
                for (int i = 0; i < n; i++)
                {
                    if (buf[i] != (byte)'\n') continue;
                    line.Write(buf, start, i - start);
                    start = i + 1;
                    if (line.Length > MaxLineBytes) return "The host sent a message over 16 MiB.";
                    Dispatch(line.GetBuffer(), (int)line.Length);
                    line.SetLength(0);
                }
                line.Write(buf, start, n - start);
                if (line.Length > MaxLineBytes) return "The host sent a message over 16 MiB.";
            }
            return "Stopped.";
        }

        void Post(HostEvent e)
        {
            if (running) Events.Enqueue(e);
        }

        void Warn(string text) => Post(new HostEvent(HostEventKind.Warning) { Text = text });
        public string Send(string type, JObject payload)
        {
            var s = stream;
            if (s == null) return null;
            string id = Guid.NewGuid().ToString("N");
            var msg = new JObject { ["v"] = 1, ["type"] = type, ["id"] = id, ["payload"] = payload };
            var bytes = Utf8.GetBytes(msg.ToString(Formatting.None) + "\n");
            lock (writeLock) { try { s.Write(bytes, 0, bytes.Length); } catch { return null; } }   // a dead socket shows up on the read side
            return id;
        }

        public void SendEnvelope(JObject envelope)
        {
            var s = stream;
            if (s == null) return;
            // Caller supplies the stable request id; retry/receipt logic must not
            // silently generate a second command with a new transaction identity.
            var bytes = Utf8.GetBytes(envelope.ToString(Formatting.None) + "\n");
            lock (writeLock) { try { s.Write(bytes, 0, bytes.Length); } catch { } }
        }

        // ---------- decoding, on this thread ----------

        void Dispatch(byte[] bytes, int length)
        {
            if (length == 0 || (length == 1 && bytes[0] == '\r')) return;
            JObject msg;
            try { msg = Parse(bytes, length); }
            catch (Exception e) { Warn("Ignored a message that isn't valid JSON: " + e.Message); return; }

            var p = msg["payload"] as JObject;
            string type = msg["type"]?.Type == JTokenType.String ? (string)msg["type"] : null;
            try
            {
                switch (type)
                {
                    case "welcome":
                        var d = p?["document"] as JObject;
                        Post(new HostEvent(HostEventKind.Welcome)
                        {
                            Text = (string)d?["name"] ?? "",
                            SessionId = (string)p?["session_id"] ?? "",
                            HostEpoch = (string)p?["host_epoch"] ?? "",
                            ActorId = (string)p?["actor_id"] ?? "",
                            CanEdit = (bool?)p?["can_edit"] ?? false,
                            DocumentId = (string)d?["id"] ?? "",
                            OpenEpoch = (string)d?["open_epoch"] ?? ""
                        });
                        break;
                    case "scene.snapshot": Post(DecodeScene(p, snapshot: true)); break;
                    case "scene.update": Post(DecodeScene(p, snapshot: false)); break;
                    case "error":
                        Post(new HostEvent(HostEventKind.Error)
                        {
                            Code = (string)p?["code"] ?? "",
                            Text = (string)p?["message"] ?? "",
                            Re = msg["re"]?.Type == JTokenType.String ? (string)msg["re"] : ""
                        });
                        break;
                    case "result":
                        Post(DecodeResult(p, msg["re"]?.Type == JTokenType.String ? (string)msg["re"] : ""));
                        break;
                    // P4 voice (#146): the host resolver's answers, passed on as JSON text for VoiceCore to parse.
                    case "voice.candidates":
                    case "voice.grammar":
                        Post(new HostEvent(type == "voice.grammar" ? HostEventKind.VoiceGrammar : HostEventKind.VoiceCandidates)
                        { Re = msg["re"]?.Type == JTokenType.String ? (string)msg["re"] : "", Text = p?.ToString(Formatting.None) ?? "" });
                        break;
                }
                // Additive consumers validate their own phase-specific payloads.
                // Scene application is queued first, so menu selection sees the
                // current native target before processing a transaction receipt.
                Post(new HostEvent(HostEventKind.Message) { RawMessage = msg });
            }
            catch (Exception e)
            {
                Warn($"Ignored a {type} message: {e.Message}");
                if (type == "scene.snapshot" || type == "scene.update")
                    Post(new HostEvent(HostEventKind.InvalidScene));
            }
        }

        static JObject Parse(byte[] bytes, int length)
        {
            using (var reader = new StrictJsonReader(new StreamReader(new MemoryStream(bytes, 0, length, false), Utf8)))
            {
                var msg = JObject.Load(reader);
                if (reader.Read()) throw new JsonReaderException("Text after the message.");
                return msg;
            }
        }

        static HostEvent DecodeResult(JObject p, string re)
        {
            if (p == null) throw new FormatException("no payload");
            var e = new HostEvent(HostEventKind.Result)
            {
                Re = re ?? "",
                Op = (string)p["op"] ?? "",
                Outcome = (string)p["outcome"] ?? "",
                Text = (string)p["summary"] ?? ""
            };
            if (p["revision"] != null && p["revision"].Type == JTokenType.Integer) e.Revision = (long)p["revision"];
            if (p["selection"] is JObject selection) { e.SelectionSpecified = true; e.SelectedId = (string)selection["id"]; }
            var err = p["error"];
            if (err is JObject eo)
            {
                e.Code = (string)eo["code"] ?? "";
                if (e.Text.Length == 0) e.Text = (string)eo["message"] ?? "";
            }
            else if (err != null && err.Type == JTokenType.String) e.Code = (string)err;
            return e;
        }

        internal static HostEvent DecodeScene(JObject p, bool snapshot)
        {
            if (p == null) throw new FormatException("no payload");
            var e = new HostEvent(HostEventKind.Scene) { Snapshot = snapshot };
            e.LiveEdit = p["live_edit"] is JObject liveEdit ? (JObject)liveEdit.DeepClone() : null;
            if (p["document"] is JObject d && d["revision"]?.Type == JTokenType.Integer)
            {
                e.Revision = (long)d["revision"];
                e.DocumentId = (string)d["id"] ?? "";
                e.OpenEpoch = (string)d["open_epoch"] ?? "";
            }
            if (!Guid.TryParseExact(e.DocumentId, "N", out _) || !Guid.TryParseExact(e.OpenEpoch, "N", out _)
                || !e.Revision.HasValue || e.Revision < 0)
                throw new FormatException("invalid document identity/revision");
            var units = p["document"]?["units"];
            double scale = (double?)units?["scale_length"] ?? double.NaN;
            if (double.IsNaN(scale) || double.IsInfinity(scale) || scale <= 0)
                throw new FormatException("invalid document units");
            if (p["removed"] is JArray removed)
                foreach (var r in removed) e.Removed.Add((string)r);
            if (p["objects"] is JArray objects)
            {
                foreach (var o in objects)
                {
                    // Never label an incomplete snapshot current or lose one delta.
                    e.Objects.Add(DecodeObject(o as JObject ?? throw new FormatException("not an object")));
                }
            }
            else throw new FormatException("objects array is missing");
            var ids = new HashSet<string>();
            foreach (var obj in e.Objects)
                if (!ids.Add(obj.Id)) throw new FormatException("duplicate object ID");
            return e;
        }

        static ObjectRecord DecodeObject(JObject o)
        {
            var r = new ObjectRecord { Id = (string)o["id"] };
            if (!Guid.TryParseExact(r.Id, "N", out _)) throw new FormatException("invalid object id");
            r.Name = (string)o["name"] ?? r.Id;
            r.ParentId = (string)o["parent"];
            if (o["generation"]?.Type != JTokenType.Integer || (long)o["generation"] < 0)
                throw new FormatException("invalid object generation");
            r.Generation = (long)o["generation"];
            if (r.ParentId != null && !Guid.TryParseExact(r.ParentId, "N", out _))
                throw new FormatException("invalid parent id");
            r.Visible = (bool?)o["visible"] ?? true;

            if (o["transform"] is JObject t)
            {
                var loc = Floats(t["location"], "location", 3, 3);
                var rot = Floats(t["rotation"], "rotation", 4, 4);
                var sc = Floats(t["scale"], "scale", 3, 3);
                r.HasTransform = true;
                r.Position = BlenderFrame.Point(loc[0], loc[1], loc[2]);
                r.Rotation = BlenderFrame.Rotation(rot[0], rot[1], rot[2], rot[3]);
                r.Scale = BlenderFrame.Point(sc[0], sc[1], sc[2]);
            }
            else throw new FormatException("transform is missing");

            // Linear RGBA, or null: no material.
            var c = o["color"];
            if (c != null && c.Type != JTokenType.Null)
            {
                var f = Floats(c, "color", 3, 4);
                r.Color = new Color(f[0], f[1], f[2], f.Length > 3 ? f[3] : 1f);
            }

            // Left out: the mesh didn't change. null: nothing to draw (camera, light, empty).
            var m = o["mesh"];
            if (m != null)
            {
                r.HasMesh = true;
                if (m.Type != JTokenType.Null) r.Mesh = DecodeMesh(m as JObject ?? throw new FormatException("mesh is not an object"));
            }
            return r;
        }

        static MeshData DecodeMesh(JObject m)
        {
            var pos = Floats(m["positions"], "positions", 0, int.MaxValue);
            if (pos.Length % 3 != 0) throw new FormatException("positions is not a multiple of 3");
            int n = pos.Length / 3;
            var data = new MeshData { Positions = new Vector3[n] };
            for (int i = 0; i < n; i++) data.Positions[i] = BlenderFrame.Point(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]);

            if (m["normals"] is JArray)
            {
                var nor = Floats(m["normals"], "normals", pos.Length, pos.Length);
                data.Normals = new Vector3[n];
                for (int i = 0; i < n; i++) data.Normals[i] = BlenderFrame.Point(nor[3 * i], nor[3 * i + 1], nor[3 * i + 2]);
            }

            var idx = m["indices"] as JArray ?? throw new FormatException("no indices");
            if (idx.Count % 3 != 0) throw new FormatException("indices is not a multiple of 3");
            data.Indices = new int[idx.Count];
            for (int i = 0; i < idx.Count; i++)
            {
                if (idx[i].Type != JTokenType.Integer) throw new FormatException("an index is not an integer");
                long v = (long)idx[i];
                if (v < 0 || v >= n) throw new FormatException($"index {v} is out of range");
                data.Indices[i] = (int)v;
            }
            BlenderFrame.FlipTriangles(data.Indices);
            return data;
        }

        static float[] Floats(JToken token, string field, int min, int max)
        {
            if (!(token is JArray a)) throw new FormatException($"{field} is missing");
            if (a.Count < min || a.Count > max) throw new FormatException($"{field} has {a.Count} numbers");
            var f = new float[a.Count];
            for (int i = 0; i < f.Length; i++)
            {
                var t = a[i];
                if (t.Type != JTokenType.Float && t.Type != JTokenType.Integer) throw new FormatException($"{field} holds a non-number");
                f[i] = (float)(double)t;
                if (float.IsNaN(f[i]) || float.IsInfinity(f[i])) throw new FormatException($"{field} holds a non-finite number");
            }
            return f;
        }

        // Plain JSON only: no NaN or Infinity (the contract rejects them) and no date guessing on strings.
        sealed class StrictJsonReader : JsonTextReader
        {
            public StrictJsonReader(TextReader r) : base(r)
            {
                DateParseHandling = DateParseHandling.None;
                FloatParseHandling = FloatParseHandling.Double;
            }

            public override bool Read()
            {
                bool more = base.Read();
                if (TokenType == JsonToken.Float && Value is double d && (double.IsNaN(d) || double.IsInfinity(d)))
                    throw new JsonReaderException("NaN and Infinity are not JSON.");
                return more;
            }
        }
    }

    enum HostEventKind { Opened, Closed, Welcome, Scene, Error, Warning, InvalidScene, Message, Result, VoiceCandidates, VoiceGrammar }

    sealed class HostEvent
    {
        public readonly HostEventKind Kind;
        public string Text = "";   // Closed: why. Welcome: document name. Error: the host's message. Warning.
        public string Code = "";   // Error
        public string DocumentId = "", OpenEpoch = "";
        public JObject RawMessage;
        public JObject LiveEdit;
        public bool Snapshot;      // Scene
        public long? Revision;
        public string Re = "", Op = "", Outcome = "";                                    // Result, Error
        public string SessionId = "", HostEpoch = "", ActorId = "";   // Welcome (DocumentId and OpenEpoch above)
        public bool SelectionSpecified;
        public string SelectedId;
        public bool CanEdit;                                                              // Welcome
        public readonly List<string> Removed = new List<string>();
        public readonly List<ObjectRecord> Objects = new List<ObjectRecord>();

        public HostEvent(HostEventKind kind) { Kind = kind; }
    }

    // One wire object, already in Unity's frame.
    sealed class ObjectRecord
    {
        public string Id, Name, ParentId;
        public long Generation;
        public bool Visible;
        public bool HasTransform;
        public Vector3 Position, Scale;
        public Quaternion Rotation;
        public Color? Color;        // null: no material
        public bool HasMesh;        // false: unchanged
        public MeshData Mesh;       // null with HasMesh: nothing to draw
    }

    sealed class MeshData
    {
        public Vector3[] Positions, Normals;   // Normals null: recalculate
        public int[] Indices;                  // already flipped
    }
}
