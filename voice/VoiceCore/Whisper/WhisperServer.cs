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

        /// <summary>See the constructor's <c>startTimeoutMs</c>.</summary>
        public const int DefaultStartTimeoutMs = 15000;

        /// <summary>
        /// The Visual C++ runtime that the prebuilt whisper-server.exe imports (voice/fetch-whisper.sh). Without it
        /// Windows shows a "DLL was not found" dialog on the desktop and the process waits until someone closes it,
        /// so it is checked before starting.
        /// </summary>
        static readonly string[] VcRuntime = { "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll" };

        /// <summary>The folder under StreamingAssets that <c>voice/fetch-whisper.sh</c> fills.</summary>
        public const string FolderName = "whisper";

        /// <summary>
        /// Models <c>voice/fetch-whisper.sh</c> downloads. tiny.en is the default on the CPU: on 1,008 real Speech
        /// Commands clips the fast path got 962 right with tiny.en and 964 with base.en, and base.en takes about twice
        /// as long on the CPU (voice/README.md).
        /// </summary>
        public const string BaseModel = "ggml-base.en.bin", TinyModel = "ggml-tiny.en.bin";

        /// <summary>
        /// The default on the GPU (<c>voice/fetch-whisper.sh --cuda</c> downloads it, 488 MB): the most accurate of the
        /// three on the TTS corpus (184 of 250 commands before snapping, against 165 for tiny.en) and the one the team
        /// tried on a GPU and kept. About 0.2 s per utterance on a GPU (Vulkan, idle RTX 5070 Ti), but 2.6-4 s on 4
        /// CPU threads, so never on the CPU.
        /// </summary>
        public const string SmallModel = "ggml-small.en.bin";

        static bool IsWindows => RuntimeInformation.IsOSPlatform(OSPlatform.Windows);

        /// <summary>
        /// The folder of <paramref name="executable"/> holds a CUDA build of whisper.cpp (ggml-cuda.dll, from
        /// <c>voice/fetch-whisper.sh --cuda</c>, or libggml-cuda.so from a Linux build).
        /// </summary>
        public static bool HasGpuBuild(string executable)
        {
            if (string.IsNullOrEmpty(executable))
                return false;
            string folder = Path.GetDirectoryName(Path.GetFullPath(executable)) ?? "";
            return File.Exists(Path.Combine(folder, "ggml-cuda.dll")) || File.Exists(Path.Combine(folder, "libggml-cuda.so"));
        }

        /// <summary>whisper-server.exe on Windows, whisper-server elsewhere.</summary>
        public static string ExecutableName => IsWindows ? "whisper-server.exe" : "whisper-server";

        readonly string executable;
        readonly string model;
        readonly int threads;
        readonly int startTimeoutMs;
        readonly bool useGpu;
        readonly Action<string> log;
        readonly Queue<string> lastLines = new Queue<string>();
        Process process;

        /// <param name="executable">Path of whisper-server(.exe); its DLLs sit next to it.</param>
        /// <param name="model">Path of a ggml model, for example StreamingAssets/whisper/ggml-base.en.bin.</param>
        /// <param name="threads">CPU threads per decode. 4 was measured; the demo PC also renders VR.</param>
        /// <param name="startTimeoutMs">Longest wait for the model to load and the warm-up to finish. Voice input waits
        /// this long at most before it falls back to Vosk alone; the measured start is 0.5 s (tiny.en) to 1 s (base.en).</param>
        /// <param name="log">Progress and errors, for example Unity's Debug.Log. May be called on any thread.</param>
        /// <param name="useGpu">Let a GPU build (whisper.cpp's CUDA zip, see <see cref="HasGpuBuild"/>) decode on the
        /// GPU. False passes <c>-ng</c>: the CPU decodes even with a GPU build.</param>
        public WhisperServer(string executable, string model, int port = DefaultPort, int threads = 4,
            int startTimeoutMs = DefaultStartTimeoutMs, Action<string> log = null, bool useGpu = false)
        {
            this.useGpu = useGpu;
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

        /// <summary>
        /// Nothing serves the port any more: the process this object started has exited, or the server it found
        /// already running (a crashed run's, another app's) went away. <see cref="EnsureRunning"/> starts a new one.
        /// </summary>
        public bool NeedsStart => process != null ? HasExited : !Answers(Port, 200);

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

        /// <summary>
        /// Whether something accepts TCP connections on 127.0.0.1:<paramref name="port"/>. A non-blocking connect and
        /// a poll, not ConnectAsync().Wait(): that needs a thread-pool thread to finish, and on a busy machine (CI)
        /// it missed a server that was listening, so a second one was started.
        /// </summary>
        public static bool Answers(int port, int timeoutMs)
        {
            try
            {
                using (var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp))
                {
                    socket.Blocking = false;
                    try
                    {
                        socket.Connect(System.Net.IPAddress.Loopback, port);
                        return true;
                    }
                    catch (SocketException e) when (e.SocketErrorCode == SocketError.WouldBlock ||
                                                    e.SocketErrorCode == SocketError.InProgress)
                    {
                        // Connecting: wait below.
                    }
                    if (!socket.Poll(Math.Max(0, timeoutMs) * 1000, SelectMode.SelectWrite))
                        return false; // no answer in time (or refused, on Windows: that shows as an error)
                    return (int)socket.GetSocketOption(SocketOptionLevel.Socket, SocketOptionName.Error) == 0;
                }
            }
            catch (SocketException)
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
            if (IsWindows)
            {
                string missing = MissingLibrary(VcRuntime, LibraryFolders(Path.GetDirectoryName(Path.GetFullPath(executable))));
                if (missing != null)
                    throw new FileNotFoundException("whisper-server.exe needs " + missing + " from the Microsoft Visual C++ " +
                                                    "2015-2022 Redistributable (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe", missing);
            }
            Process previous = process;
            previous?.Dispose();

            var start = new ProcessStartInfo
            {
                FileName = executable,
                // -ng: not the GPU unless asked (useGpu, a CUDA build). Decode options come with each request.
                Arguments = "-m " + Quote(model) + " --host 127.0.0.1 --port " + Port.ToString(CultureInfo.InvariantCulture) +
                            " -t " + threads.ToString(CultureInfo.InvariantCulture) + " -l en -nt" + (useGpu ? "" : " -ng"),
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
            try
            {
                // A decode keeps 4 cores busy for about half a second; the VR frame must not wait for it.
                process.PriorityClass = ProcessPriorityClass.BelowNormal;
            }
            catch (Exception e) when (e is InvalidOperationException || e is System.ComponentModel.Win32Exception ||
                                      e is NotSupportedException)
            {
                log("whisper-server runs at normal priority (" + e.GetType().Name + ": " + e.Message + ")");
            }
        }

        /// <summary>The first of <paramref name="libraries"/> that none of <paramref name="folders"/> holds, or null.</summary>
        internal static string MissingLibrary(IEnumerable<string> libraries, IReadOnlyList<string> folders)
        {
            foreach (string library in libraries)
            {
                bool found = false;
                foreach (string folder in folders)
                    found |= File.Exists(Path.Combine(folder, library));
                if (!found)
                    return library;
            }
            return null;
        }

        /// <summary>Where Windows looks for an executable's DLLs: its folder, System32, the Windows folder and PATH.</summary>
        static IReadOnlyList<string> LibraryFolders(string executableFolder)
        {
            var folders = new List<string>
            {
                executableFolder, Environment.SystemDirectory, Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            };
            foreach (string folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
                if (folder.Trim().Length > 0 && folder.IndexOfAny(Path.GetInvalidPathChars()) < 0)
                    folders.Add(folder.Trim());
            return folders;
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
            var silence = new WhisperServerRecognizer(Port, prompt: "", promptWithGrammar: false, timeoutMs: Math.Max(5000, startTimeoutMs),
                minSpeechRms: 0f); // silence on purpose: the speech gate would skip the request
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
