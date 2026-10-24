using System;
using System.Collections.Generic;
using System.Diagnostics;
using Newtonsoft.Json;
using Unity.Profiling;
using Unity.Profiling.LowLevel.Unsafe;
using UnityEngine;
using UnityEngine.XR;
using Debug = UnityEngine.Debug;

namespace SpatialModeling
{
    // Isolated experiment only. Wall-clock stages and discovered engine counters;
    // texture assignment must never be relabeled as headset presentation.
    public sealed class P1PipelineProfile : MonoBehaviour
    {
        public static readonly bool Enabled = Array.IndexOf(Environment.GetCommandLineArgs(), "--p1-profile") >= 0;
        static readonly Dictionary<string, Sample> samples = new Dictionary<string, Sample>();
        static readonly List<object> requestTrace = new List<object>();
        readonly List<(string name, string unit, ProfilerRecorder recorder)> recorders = new List<(string, string, ProfilerRecorder)>();
        int frames;
        double began, intervalBegan, previousFrame;
        static string[] args => Environment.GetCommandLineArgs();
        public static bool UseClaims => !Enabled || Array.IndexOf(args, "--p1-profile-legacy-fetch") < 0;

        sealed class Sample
        {
            public long count;
            public double total, max;
        }

        public static long Now() => Enabled ? Stopwatch.GetTimestamp() : 0;
        static double Seconds() => (double)Stopwatch.GetTimestamp() / Stopwatch.Frequency;

        public static void End(string name, long at)
        {
            if (!Enabled) return;
            Add(name, (Stopwatch.GetTimestamp() - at) * 1000.0 / Stopwatch.Frequency);
        }

        public static void Add(string name, double value)
        {
            if (!Enabled) return;
            if (!samples.TryGetValue(name, out var sample)) samples[name] = sample = new Sample();
            sample.count++; sample.total += value; sample.max = Math.Max(sample.max, value);
        }

        public static double ElapsedMs(long at) => Enabled
            ? (Stopwatch.GetTimestamp() - at) * 1000.0 / Stopwatch.Frequency : 0;

        public static void TraceRequest(int lane, long at, double firstHeaderMs, bool beforeComplete,
            string tag, string captured, long code, string result, bool discard)
        {
            if (!Enabled || requestTrace.Count >= 4096) return;
            requestTrace.Add(new { lane, started_ms = at * 1000.0 / Stopwatch.Frequency,
                first_header_ms = firstHeaderMs, header_before_complete = beforeComplete,
                elapsed_ms = ElapsedMs(at), tag, captured, code, result, discard, claims_enabled = UseClaims });
        }

        public static string CaptureUrl()
        {
            int port = 8766;
            if (Enabled) foreach (string arg in args)
                if (arg.StartsWith("--p1-profile-port=") && int.TryParse(arg.Substring(18), out var requested)
                    && requested > 0 && requested < 65536) port = requested;
            return "http://127.0.0.1:" + port + "/frame";
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (Enabled) new GameObject("P1 isolated pipeline profiler").AddComponent<P1PipelineProfile>();
        }

        void Start()
        {
            began = intervalBegan = previousFrame = Seconds();
            var handles = new List<ProfilerRecorderHandle>();
            ProfilerRecorderHandle.GetAvailable(handles);
            foreach (var handle in handles)
            {
                var description = ProfilerRecorderHandle.GetDescription(handle);
                string name = description.Name;
                string lower = name.ToLowerInvariant();
                if (!lower.Contains("upload") && !lower.Contains("decode") && !lower.Contains("jpeg")
                    && !lower.Contains("createtexture") && name != "Main Thread" && name != "Render Thread"
                    && !name.Contains("Thread Frame Time") && name != "GPU Frame Time"
                    && name != "Texture Memory" && name != "Texture Count") continue;
                Debug.Log("P1_PROFILE_AVAILABLE " + name + " unit=" + description.UnitType);
                var recorder = ProfilerRecorder.StartNew(description.Category, name, 1);
                if (recorder.Valid) recorders.Add((name, description.UnitType.ToString(), recorder));
            }
            Debug.Log("P1_PROFILE_BEGIN " + CaptureUrl() + " gpu=" + SystemInfo.graphicsDeviceType);
        }

        void LateUpdate()
        {
            double now = Seconds();
            Add("main_frame_elapsed_ms", (now - previousFrame) * 1000); previousFrame = now;
            frames++;
            foreach (var item in recorders) if (item.recorder.Count > 0)
                Add("engine/" + item.name + "/" + item.unit, item.recorder.LastValue);
            if (now - intervalBegan >= 2)
            {
                var rows = new Dictionary<string, object>();
                foreach (var pair in samples)
                    rows[pair.Key] = new { count = pair.Value.count, mean = pair.Value.total / pair.Value.count, max = pair.Value.max };
                Debug.Log("P1_PIPELINE_PROFILE " + JsonConvert.SerializeObject(new {
                    elapsed = now - began, frame_rate = frames / (now - intervalBegan),
                    eye_width = XRSettings.eyeTextureWidth, eye_height = XRSettings.eyeTextureHeight,
                    stages = rows, note = "Engine counters retain stated units; assignment is not headset presentation"
                }));
                samples.Clear(); frames = 0; intervalBegan = now;
            }
            double duration = 60;
            foreach (string arg in args) if (arg.StartsWith("--p1-profile-duration="))
                double.TryParse(arg.Substring(22), out duration);
            if (now - began >= duration) WorkspaceShutdown.Quit();
        }

        void OnDisable()
        {
            for (int first = 0; first < requestTrace.Count; first += 128)
                Debug.Log("P1_REQUEST_TRACE " + JsonConvert.SerializeObject(
                    requestTrace.GetRange(first, Math.Min(128, requestTrace.Count - first))));
            requestTrace.Clear();
            foreach (var item in recorders) item.recorder.Dispose();
            recorders.Clear();
        }
    }
}
