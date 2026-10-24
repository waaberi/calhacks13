using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Threading;

namespace SpatialModeling.VoiceCore.Whisper
{
    /// <summary>
    /// Starts whisper.cpp's <c>whisper-server</c> without a human: from a known folder (StreamingAssets/whisper,
    /// filled by <c>voice/fetch-whisper.sh</c>), with the model, port and thread count, unless something already
    /// answers on the port. It waits until the model is loaded, warms it up with a short silent request (the first
    /// decode is slow) and kills the process on <see cref="Dispose"/> if it started it. A server left over from a
    /// crashed run keeps answering on the port and is reused. Blocks while starting: call it on VoiceInput's worker
    /// thread, which is where <see cref="VoiceRecognizers.Create"/> runs.
    /// </summary>
    public sealed class WhisperServer : IDisposable
    {
        public const int DefaultPort = 8178;

        /// <summary>The folder under StreamingAssets that <c>voice/fetch-whisper.sh</c> fills.</summary>
        public const string FolderName = "whisper";

        /// <summary>Models <c>voice/fetch-whisper.sh</c> downloads. base.en is the default (see voice/README.md).</summary>
        public const string BaseModel = "ggml-base.en.bin", TinyModel = "ggml-tiny.en.bin";

        static bool IsWindows => RuntimeInformation.IsOSPlatform(OSPlatform.Windows);

        /// <summary>whisper-server.exe on Windows, whisper-server elsewhere.</summary>
        public static string ExecutableName => IsWindows ? "whisper-server.exe" : "whisper-server";

        readonly string executable;
        readonly string model;
        readonly int threads;
        readonly int startTimeoutMs;
        readonly Action<string> log;
        readonly Queue<string> lastLines = new Queue<string>();
        Process process;

        /// <param name="executable">Path of whisper-server(.exe); its DLLs sit next to it.</param>
        /// <param name="model">Path of a ggml model, for example StreamingAssets/whisper/ggml-base.en.bin.</param>
        /// <param name="threads">CPU threads per decode. 4 was measured; the demo PC also renders VR.</param>
        /// <param name="startTimeoutMs">Longest wait for the model to load and the warm-up to finish.</param>
        /// <param name="log">Progress and errors, for example Unity's Debug.Log. May be called on any thread.</param>
        public WhisperServer(string executable, string model, int port = DefaultPort, int threads = 4,
            int startTimeoutMs = 30000, Action<string> log = null)
        {
            this.executable = executable;
            this.model = model;
            Port = port;
            this.threads = threads;
            this.startTimeoutMs = startTimeoutMs;
            this.log = log ?? (_ => { });
        }

        public int Port { get; }

        /// <summary>This object started the process (and kills it on <see cref="Dispose"/>).</summary>
        public bool Owned => process != null;

        /// <summary>The process this object started has exited, for example after a crash.</summary>
        public bool HasExited
        {
            get
            {
                try
                {
                    return process != null && process.HasExited;
                }
                catch (InvalidOperationException)
                {
                    return true;
                }
            }
        }

        /// <summary>Milliseconds the last <see cref="EnsureRunning"/> took, including the warm-up.</summary>
        public double StartMilliseconds { get; private set; }

        /// <summary>
        /// Makes sure a warmed-up server answers on <see cref="Port"/>, starting one if nothing listens there.
        /// Throws <see cref="FileNotFoundException"/> if the executable or model is missing and
        /// <see cref="IOException"/> if the server doesn't come up.
        /// </summary>
        public void EnsureRunning()
        {
            var clock = Stopwatch.StartNew();
            if (!Answers(Port, 300))
            {
                Launch();
                WaitUntilHealthy(clock);
            }
            else
            {
                log("whisper-server already answers on port " + Port + "; using it");
                WaitUntilHealthy(clock);
            }
            WarmUp();
            StartMilliseconds = clock.Elapsed.TotalMilliseconds;
            log("whisper-server ready on port " + Port + " in " + StartMilliseconds.ToString("0", CultureInfo.InvariantCulture) + " ms");
        }

        /// <summary>Kills the process if this object started it.</summary>
        public void Dispose()
        {
            Process started = process;
            process = null;
            if (started == null)
                return;
            try
            {
                if (!started.HasExited)
                {
                    started.Kill();
                    started.WaitForExit(3000);
                }
            }
            catch (Exception e) when (e is InvalidOperationException || e is System.ComponentModel.Win32Exception)
            {
                // It exited on its own in the meantime.
            }
            started.Dispose();
        }

        /// <summary>Whether something accepts TCP connections on 127.0.0.1:<paramref name="port"/>.</summary>
        public static bool Answers(int port, int timeoutMs)
        {
            try
            {
                using (var client = new TcpClient())
                    return client.ConnectAsync("127.0.0.1", port).Wait(timeoutMs) && client.Connected;
            }
            catch (Exception e) when (e is SocketException || e is AggregateException)
            {
                return false;
            }
        }

        void Launch()
        {
            if (!File.Exists(executable))
                throw new FileNotFoundException("No whisper-server at " + executable + "; run voice/fetch-whisper.sh", executable);
            if (!File.Exists(model))
                throw new FileNotFoundException("No Whisper model at " + model + "; run voice/fetch-whisper.sh", model);
            Process previous = process;
            previous?.Dispose();

            var start = new ProcessStartInfo
            {
                FileName = executable,
                // -ng: never the GPU, which renders VR on the demo PC. Decode options come with each request.
                Arguments = "-m " + Quote(model) + " --host 127.0.0.1 --port " + Port.ToString(CultureInfo.InvariantCulture) +
                            " -t " + threads.ToString(CultureInfo.InvariantCulture) + " -l en -nt -ng",
                WorkingDirectory = Path.GetDirectoryName(Path.GetFullPath(executable)),
                UseShellExecute = false,
                CreateNoWindow = true, // no console window over the app
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            process = new Process { StartInfo = start, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, e) => Remember(e.Data);
            process.ErrorDataReceived += (_, e) => Remember(e.Data); // drained, or the server blocks on a full pipe
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            log("Started " + executable + " " + start.Arguments);
        }

        void WaitUntilHealthy(Stopwatch clock)
        {
            while (true)
            {
                if (HasExited)
                    throw new IOException("whisper-server exited with code " + process.ExitCode + ": " + LastLines());
                int status = Health();
                if (status == 200)
                    return;
                if (status > 0 && status != 503)
                    throw new IOException("Port " + Port + " answers, but not like whisper-server (HTTP " + status + ")");
                if (clock.ElapsedMilliseconds > startTimeoutMs)
                    throw new IOException("whisper-server didn't start within " + startTimeoutMs + " ms: " + LastLines());
                Thread.Sleep(100);
            }
        }

        /// <summary>HTTP status of GET /health: 200 ready, 503 loading, 0 nothing listening yet.</summary>
        int Health()
        {
            try
            {
                string head = "GET /health HTTP/1.1\r\nHost: 127.0.0.1:" + Port + "\r\nConnection: close\r\n\r\n";
                return Http.Send("127.0.0.1", Port, head, null, 2000).status;
            }
            catch (Exception e) when (e is IOException || e is SocketException || e is AggregateException)
            {
                return 0;
            }
        }

        /// <summary>The first decode allocates its buffers; do it now with half a second of silence.</summary>
        void WarmUp()
        {
            var silence = new WhisperServerRecognizer(Port, prompt: "", promptWithGrammar: false, timeoutMs: Math.Max(5000, startTimeoutMs));
            silence.Start(16000);
            silence.AcceptAudio(new short[8000], 8000);
            silence.Stop();
            if (silence.LastStopFailed)
                throw new IOException("whisper-server's warm-up failed: " + silence.LastError);
        }

        void Remember(string line)
        {
            if (string.IsNullOrEmpty(line))
                return;
            lock (lastLines)
            {
                lastLines.Enqueue(line);
                while (lastLines.Count > 20)
                    lastLines.Dequeue();
            }
        }

        string LastLines()
        {
            lock (lastLines)
                return lastLines.Count == 0 ? "(no output)" : string.Join(" | ", lastLines);
        }

        static string Quote(string path) => "\"" + path + "\"";
    }
}
