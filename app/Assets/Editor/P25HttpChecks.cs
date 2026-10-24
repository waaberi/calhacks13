using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEditor;
using UnityEngine;

// Actual UnityWebRequest + production coroutine checks against a loopback fake.
// Inactive components never start OnEnable, a native host, desktop input or XR.
// Run with -batchmode -nographics -executeMethod P25HttpChecks.Run, WITHOUT -quit.
public static class P25HttpChecks
{
    const string FakeSession = "p25-http-fixture-session";
    const string FakeToken = "p25-http-fixture-token";
    const string FakeInstance = "p25-http-fixture-instance";
    static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static readonly Stack<IEnumerator> routines = new Stack<IEnumerator>();
    static readonly JArray results = new JArray();
    static object waiting;
    static double deadline;
    static string output;
    static string previousPort;

    static void Check(bool value, string message)
    { if (!value) throw new Exception("P25_HTTP: " + message); }
    static object Field(object target, string name) => target.GetType().GetField(name, Private).GetValue(target);
    static void Set(object target, string name, object value) => target.GetType().GetField(name, Private).SetValue(target, value);
    static IEnumerator Routine(object target, string name, params object[] args) =>
        (IEnumerator)target.GetType().GetMethod(name, Private).Invoke(target, args);
    static void Record(string name, string evidence)
    {
        results.Add(new JObject { ["name"] = name, ["passed"] = true, ["evidence"] = evidence });
        Debug.Log("P25_HTTP_CASE PASS " + name + " " + evidence);
    }

    public static void Run()
    {
        Check(routines.Count == 0, "only one HTTP fixture may own this Editor");
        output = Environment.GetEnvironmentVariable("CALHACKS_P25_HTTP_RESULTS");
        Check(!string.IsNullOrWhiteSpace(output) && Path.IsPathRooted(output), "set an absolute external CALHACKS_P25_HTTP_RESULTS path");
        output = Path.GetFullPath(output);
        Check(!File.Exists(output), "preserve earlier HTTP evidence");
        for (var directory = new DirectoryInfo(Path.GetDirectoryName(output)); directory != null; directory = directory.Parent)
            Check(!File.Exists(Path.Combine(directory.FullName, ".git")) && !Directory.Exists(Path.Combine(directory.FullName, ".git"))
                && !directory.Name.StartsWith("OneDrive", StringComparison.OrdinalIgnoreCase), "HTTP evidence must stay outside Git and OneDrive");
        Directory.CreateDirectory(Path.GetDirectoryName(output));
        previousPort = Environment.GetEnvironmentVariable("CALHACKS_CAPTURE_PORT");
        deadline = EditorApplication.timeSinceStartup + 90;
        results.Clear(); waiting = null;
        routines.Push(Suite());
        EditorApplication.update += Tick;
        Debug.Log("P25_HTTP_START fake loopback only; no native process, OS input or Player");
    }

    static void Tick()
    {
        try
        {
            Check(EditorApplication.timeSinceStartup < deadline, "bounded HTTP suite timed out");
            if (waiting is AsyncOperation operation && !operation.isDone) return;
            if (waiting is CustomYieldInstruction custom && custom.keepWaiting) return;
            waiting = null;
            if (routines.Count == 0) { Finish(null); return; }
            var iterator = routines.Peek();
            if (!iterator.MoveNext())
            {
                (routines.Pop() as IDisposable)?.Dispose();
                return;
            }
            var next = iterator.Current;
            if (next is IEnumerator nested && !(next is CustomYieldInstruction)) routines.Push(nested);
            else waiting = next;
        }
        catch (Exception error) { Finish(error); }
    }

    static void Finish(Exception failure)
    {
        EditorApplication.update -= Tick;
        while (routines.Count > 0)
        {
            try { (routines.Pop() as IDisposable)?.Dispose(); }
            catch (Exception cleanup) { if (failure == null) failure = cleanup; }
        }
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", previousPort);
        var record = new JObject {
            ["passed"] = failure == null, ["cases"] = results,
            ["transport"] = "actual UnityWebRequest and production IEnumerators; fake TCP loopback responses",
            ["native_process_launched"] = false, ["desktop_input_injected"] = false,
            ["player_launched"] = false, ["native_ui_acceptance"] = false,
            ["error"] = failure?.ToString()
        };
        try { File.WriteAllText(output, record.ToString()); }
        catch (Exception writeError) { failure = writeError; }
        if (failure == null) Debug.Log("P25_HTTP_CHECKS PASS cases=" + results.Count + " actual native/VR acceptance=False");
        else Debug.LogError(failure);
        EditorApplication.Exit(failure == null ? 0 : 1);
    }

    static IEnumerator Suite()
    {
        yield return DisabledHelperState();
        yield return StateRecovery();
        yield return SendAcknowledgement(false);
        yield return SendAcknowledgement(true);
        yield return CleanupAcknowledgement("empty", false, false);
        yield return CleanupAcknowledgement("wrong_sequence", false, false);
        yield return CleanupAcknowledgement("ok_false", false, false);
        yield return CleanupAcknowledgement("valid", true, false);
        yield return CleanupAcknowledgement("recover_after_empty", true, true);
    }

    static JObject State(long next = 1) => new JObject {
        ["enabled"] = true, ["ready"] = true, ["focused"] = false, ["release_error"] = false,
        ["session"] = FakeSession, ["token"] = FakeToken, ["next_seq"] = next,
        ["helper_pid"] = 42, ["capture_generation"] = 7, ["capture_instance"] = FakeInstance,
        ["capture_geometry"] = "p25-fixture-geometry", ["reason"] = "",
        ["selection"] = new JObject { ["hwnd"] = 123, ["pid"] = 456 }, ["windows"] = new JArray(),
        ["image"] = new JObject { ["width"] = 800, ["height"] = 600 }, ["frame"] = 1
    };

    static IEnumerator DisabledHelperState()
    {
        using var server = new FakeServer(request => new Reply("{\"enabled\":false,\"ready\":false,\"reason\":\"input_disabled\"}"));
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        var go = new GameObject("P25 HTTP inactive capture-only helper reader"); go.SetActive(false);
        try
        {
            var preview = go.AddComponent<PreviewInteraction>();
            var transport = (PreviewInputTransportState)Field(preview, "transport");
            // A capture-only response must also revoke a previously synchronized
            // helper's credentials instead of leaving its authority available.
            Set(preview, "session", FakeSession); Set(preview, "token", FakeToken);
            transport.Observe(FakeSession, 1);
            yield return Until(Routine(preview, "ReadState"), () => server.Gets >= 1
                && !(bool)Field(preview, "readingState") && preview.Notice.Contains("--enable-input"));
            Check(!transport.Synchronized, "compact disabled state cannot synchronize native input transport");
            Check((string)Field(preview, "session") == "" && (string)Field(preview, "token") == "",
                "capture-only helper exposes no credentials or native input authority");
            Check(!(bool)Field(preview, "readingState"), "disabled response clears the actual reader barrier");
            var events = (Queue<JObject>)Field(preview, "events");
            events.Enqueue(new JObject { ["type"] = "release" });
            var sender = Routine(preview, "SendEvents");
            try
            {
                for (int frame = 0; frame < 3; frame++)
                {
                    Check(sender.MoveNext(), "disabled sender remains alive without admitting an event");
                    yield return sender.Current;
                }
            }
            finally { (sender as IDisposable)?.Dispose(); }
            Check(server.Posts == 0 && events.Count == 1 && !(bool)Field(preview, "sendingEvent"),
                "actual sender cannot POST even a queued release without synchronized credentials");
            Check(server.Error == null, "fake server stayed healthy: " + server.Error);
            Record("state_compact_input_disabled", "actual reader showed --enable-input, cleared its barrier and revoked synchronization; actual sender POSTs=0");
        }
        finally { UnityEngine.Object.DestroyImmediate(go); }
    }

    static IEnumerator StateRecovery()
    {
        using var server = new FakeServer(request => new Reply(request.GetNumber == 1
            ? "{\"enabled\":true,\"session\":{},\"next_seq\":[],\"focused\":false}"
            : State().ToString(Newtonsoft.Json.Formatting.None)));
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        var go = new GameObject("P25 HTTP inactive state reader"); go.SetActive(false);
        try
        {
            var preview = go.AddComponent<PreviewInteraction>();
            var transport = (PreviewInputTransportState)Field(preview, "transport");
            bool invalidStateReleased = false;
            yield return Until(Routine(preview, "ReadState"), () => server.Gets >= 2 && transport.Synchronized
                && !(bool)Field(preview, "readingState"), () => {
                    if (server.Gets == 1 && !(bool)Field(preview, "readingState") && !transport.Synchronized)
                        invalidStateReleased = true;
                });
            Check(invalidStateReleased, "wrong-typed valid JSON clears the reading barrier instead of stranding it");
            Check(transport.Session == FakeSession && transport.NextSequence == 1,
                "the same actual reader recovers and observes the later valid helper state");
            Check(server.Error == null, "fake server stayed healthy: " + server.Error);
            Record("state_wrong_types_then_valid", "actual reader survived malformed state and synchronized on a later GET");
        }
        finally { UnityEngine.Object.DestroyImmediate(go); }
    }

    static IEnumerator SendAcknowledgement(bool valid)
    {
        using var server = new FakeServer(request => new Reply(valid
            ? new JObject { ["ok"] = true, ["seq"] = request.Body["seq"] }.ToString(Newtonsoft.Json.Formatting.None)
            : "{}"));
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        var go = new GameObject("P25 HTTP inactive event sender"); go.SetActive(false);
        try
        {
            var preview = go.AddComponent<PreviewInteraction>();
            var transport = (PreviewInputTransportState)Field(preview, "transport");
            Set(preview, "session", FakeSession); Set(preview, "token", FakeToken); Set(preview, "state", State());
            transport.Observe(FakeSession, 1);
            ((Queue<JObject>)Field(preview, "events")).Enqueue(new JObject { ["type"] = "release" });
            yield return Until(Routine(preview, "SendEvents"), () => server.Posts >= 1 && !(bool)Field(preview, "sendingEvent"));
            Check(transport.Synchronized == valid, valid ? "matching success acknowledgement keeps transport current"
                : "HTTP 200 with an empty body cannot acknowledge even a cleanup event");
            Check(server.Posts == 1, "a send outcome is never blindly repeated");
            Check(server.Requests.TryPeek(out var sent) && (string)sent.Body["type"] == "release"
                && (long)sent.Body["seq"] == 1, "actual sender used the cleanup event and authoritative sequence");
            Check(!(bool)Field(preview, "readingState") && !(bool)Field(preview, "sendingEvent"), "event flags are released");
            Record(valid ? "sender_valid_ack" : "sender_rejects_empty_200", "actual sender validated JSON acknowledgement; no native admission or action used");
        }
        finally { UnityEngine.Object.DestroyImmediate(go); }
    }

    static IEnumerator CleanupAcknowledgement(string mode, bool expectedCallback, bool recover)
    {
        long nextSequence = 1;
        using var server = new FakeServer(request => {
            if (request.Method == "GET") return new Reply(State(nextSequence).ToString(Newtonsoft.Json.Formatting.None));
            long received = (long)request.Body["seq"];
            Check(received == nextSequence, "cleanup retry must resynchronize from a fresh GET");
            nextSequence++;
            bool good = mode == "valid" || (recover && request.PostNumber > 1);
            string body = good ? new JObject { ["ok"] = true, ["seq"] = received }.ToString(Newtonsoft.Json.Formatting.None)
                : mode == "wrong_sequence" ? new JObject { ["ok"] = true, ["seq"] = received + 99 }.ToString(Newtonsoft.Json.Formatting.None)
                : mode == "ok_false" ? new JObject { ["ok"] = false, ["seq"] = received }.ToString(Newtonsoft.Json.Formatting.None) : "{}";
            return new Reply(body);
        });
        var go = new GameObject("P25 HTTP independent cleanup " + mode); go.SetActive(false);
        try
        {
            int released = 0;
            var cleanup = go.AddComponent<PreviewInputCleanup>();
            yield return Complete(Routine(cleanup, "Cleanup", server.Url, FakeInstance, (Action)(() => released++)));
            Check(released == (expectedCallback ? 1 : 0), "cleanup callback requires a matching successful native-input acknowledgement: " + mode);
            int expectedPosts = expectedCallback ? (recover ? 2 : 1) : 3;
            Check(server.Posts == expectedPosts, "cleanup retries are bounded and stop after confirmed release: " + mode);
            foreach (var request in server.Requests)
                if (request.Method == "POST") Check((string)request.Body["type"] == "release", "cleanup never retries a model operation");
            Check(server.Error == null, "fake server stayed healthy: " + server.Error);
            Record("cleanup_" + mode, "actual cleanup callback=" + released + " POSTs=" + server.Posts + "; only idempotent release was sent");
        }
        finally { if (go != null) UnityEngine.Object.DestroyImmediate(go); }
    }

    static IEnumerator Until(IEnumerator actual, Func<bool> done, Action afterStep = null)
    {
        double until = EditorApplication.timeSinceStartup + 12;
        try
        {
            while (!done())
            {
                Check(EditorApplication.timeSinceStartup < until, "production coroutine did not reach its bounded checkpoint");
                Check(actual.MoveNext(), "production coroutine stopped before its expected recovery");
                afterStep?.Invoke();
                yield return actual.Current;
            }
        }
        finally { (actual as IDisposable)?.Dispose(); }
    }

    static IEnumerator Complete(IEnumerator actual)
    {
        double until = EditorApplication.timeSinceStartup + 16;
        try
        {
            while (actual.MoveNext())
            {
                Check(EditorApplication.timeSinceStartup < until, "bounded cleanup did not finish");
                yield return actual.Current;
            }
        }
        finally { (actual as IDisposable)?.Dispose(); }
    }

    sealed class Reply
    {
        public readonly string Body;
        public Reply(string body) { Body = body; }
    }

    sealed class Request
    {
        public string Method, Path;
        public JObject Body;
        public int GetNumber, PostNumber;
    }

    sealed class FakeServer : IDisposable
    {
        readonly TcpListener listener;
        readonly Thread worker;
        readonly Func<Request, Reply> handler;
        volatile bool stopped;
        int gets, posts;
        public readonly ConcurrentQueue<Request> Requests = new ConcurrentQueue<Request>();
        public string Error;
        public int Port { get; }
        public string Url => "http://127.0.0.1:" + Port;
        public int Gets => Volatile.Read(ref gets);
        public int Posts => Volatile.Read(ref posts);
        public FakeServer(Func<Request, Reply> respond)
        {
            handler = respond; listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
            Port = ((IPEndPoint)listener.LocalEndpoint).Port;
            worker = new Thread(Serve) { IsBackground = true, Name = "P25 fake HTTP only" }; worker.Start();
        }
        void Serve()
        {
            while (!stopped)
            {
                try
                {
                    using var client = listener.AcceptTcpClient(); client.ReceiveTimeout = client.SendTimeout = 2000;
                    using var stream = client.GetStream();
                    var header = new List<byte>();
                    while (header.Count < 32768)
                    {
                        int next = stream.ReadByte(); if (next < 0) throw new EndOfStreamException();
                        header.Add((byte)next); int n = header.Count;
                        if (n >= 4 && header[n - 4] == 13 && header[n - 3] == 10 && header[n - 2] == 13 && header[n - 1] == 10) break;
                    }
                    string[] lines = Encoding.ASCII.GetString(header.ToArray()).Split(new[] { "\r\n" }, StringSplitOptions.None);
                    var first = lines[0].Split(' '); int size = 0;
                    foreach (string line in lines) if (line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase)) size = int.Parse(line.Substring(15).Trim());
                    if (size < 0 || size > 65536) throw new InvalidDataException("Fixture request exceeds bounded size");
                    var bytes = new byte[size]; int at = 0;
                    while (at < size) { int read = stream.Read(bytes, at, size - at); if (read == 0) throw new EndOfStreamException(); at += read; }
                    var request = new Request { Method = first[0], Path = first[1], Body = size > 0 ? JObject.Parse(Encoding.UTF8.GetString(bytes)) : new JObject() };
                    if (request.Method == "GET") request.GetNumber = Interlocked.Increment(ref gets);
                    else if (request.Method == "POST") request.PostNumber = Interlocked.Increment(ref posts);
                    else throw new InvalidDataException("Unexpected fixture method");
                    Requests.Enqueue(request);
                    var reply = handler(request);
                    byte[] body = Encoding.UTF8.GetBytes(reply.Body);
                    byte[] prefix = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n");
                    stream.Write(prefix, 0, prefix.Length); stream.Write(body, 0, body.Length); stream.Flush();
                }
                catch (Exception error) { if (!stopped) { Error = error.ToString(); return; } }
            }
        }
        public void Dispose()
        { stopped = true; listener.Stop(); worker.Join(1000); }
    }
}
