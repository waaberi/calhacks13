using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using SpatialModeling.VoiceCore.Whisper;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>
    /// WhisperServerRecognizer's HTTP client and WhisperServer's process handling, against fakes: a TcpListener that
    /// answers like whisper-server, and (on Linux and macOS) a Python stand-in for the whisper-server executable.
    /// </summary>
    public class WhisperServerTests
    {
        /// <summary>Answers each connection with <see cref="Respond"/>(request) and closes it, like whisper-server.</summary>
        sealed class FakeHttpServer : IDisposable
        {
            readonly TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
            readonly Thread thread;
            volatile bool stopped;
            public readonly List<string> Requests = new List<string>();
            public Func<string, (int status, string body)> Respond = _ => (200, "{\"text\":\"\"}");
            public int DelayMs;

            public FakeHttpServer()
            {
                listener.Start();
                Port = ((IPEndPoint)listener.LocalEndpoint).Port;
                thread = new Thread(Loop) { IsBackground = true };
                thread.Start();
            }

            public int Port { get; }

            void Loop()
            {
                while (!stopped)
                {
                    TcpClient client;
                    try
                    {
                        client = listener.AcceptTcpClient();
                    }
                    catch (SocketException)
                    {
                        return;
                    }
                    using (client)
                    {
                        NetworkStream stream = client.GetStream();
                        string request = ReadRequest(stream);
                        lock (Requests)
                            Requests.Add(request);
                        Thread.Sleep(DelayMs);
                        (int status, string body) = Respond(request);
                        byte[] bytes = Encoding.UTF8.GetBytes(body);
                        byte[] head = Encoding.ASCII.GetBytes("HTTP/1.1 " + status + " X\r\nContent-Type: application/json\r\nContent-Length: " +
                                                              bytes.Length + "\r\nConnection: close\r\n\r\n");
                        try
                        {
                            stream.Write(head, 0, head.Length);
                            stream.Write(bytes, 0, bytes.Length);
                        }
                        catch (IOException)
                        {
                            // The client gave up (timeout test).
                        }
                    }
                }
            }

            static string ReadRequest(NetworkStream stream)
            {
                var data = new MemoryStream();
                var buffer = new byte[65536];
                int headerEnd = -1, length = 0;
                while (headerEnd < 0 || data.Length < headerEnd + 4 + length)
                {
                    int n = stream.Read(buffer, 0, buffer.Length);
                    if (n <= 0)
                        break;
                    data.Write(buffer, 0, n);
                    string sofar = Encoding.Latin1.GetString(data.ToArray());
                    if (headerEnd < 0 && (headerEnd = sofar.IndexOf("\r\n\r\n", StringComparison.Ordinal)) >= 0)
                    {
                        string lengthLine = sofar.Substring(0, headerEnd).Split("\r\n")
                            .FirstOrDefault(l => l.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase));
                        length = lengthLine == null ? 0 : int.Parse(lengthLine.Substring(15).Trim());
                    }
                }
                return Encoding.Latin1.GetString(data.ToArray());
            }

            public void Dispose()
            {
                stopped = true;
                listener.Stop();
            }
        }

        static int FreePort()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0);
            probe.Start();
            int port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            return port;
        }

        static List<RecognitionResult> Utter(WhisperServerRecognizer whisper, int samples = 16000)
        {
            var heard = new List<RecognitionResult>();
            whisper.Recognized += heard.Add;
            whisper.Start(16000);
            whisper.AcceptAudio(new short[samples], samples);
            whisper.Stop();
            return heard;
        }

        [Fact]
        public void PostsTheUtteranceWithThePromptAndSnapsTheTranscript()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, "{\"text\":\" At a cone.\\n\"}") })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                whisper.SetGrammar(new[] { "add a cone", "undo", "[unk]" });
                List<RecognitionResult> heard = Utter(whisper);

                Assert.Equal("add a cone", Assert.Single(heard).Text);
                Assert.InRange(heard[0].Confidence, PhraseSnapper.DefaultThreshold, 0.99f);
                Assert.Equal("At a cone.", whisper.LastTranscript);
                Assert.False(whisper.LastStopFailed);
                string request = Assert.Single(server.Requests);
                Assert.StartsWith("POST /inference HTTP/1.1", request);
                Assert.Contains("name=\"prompt\"\r\n\r\n" + WhisperServerRecognizer.BlenderPrompt, request);
                Assert.Contains("name=\"temperature_inc\"\r\n\r\n0\r\n", request);
                Assert.Contains("name=\"file\"; filename=\"utterance.wav\"", request);
                Assert.Contains("RIFF", request);
                Assert.Contains("WAVEfmt ", request);
            }
        }

        [Fact]
        public void ChatterRaisesNothing()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, "{\"text\":\" This is our project.\"}") })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                whisper.SetGrammar(new[] { "add a cone", "undo", "[unk]" });
                Assert.Empty(Utter(whisper));
                Assert.False(whisper.LastStopFailed);
                Assert.False(whisper.LastSnap.Accepted);
            }
        }

        [Fact]
        public void NoServerFailsTheUtterance()
        {
            var whisper = new WhisperServerRecognizer(FreePort(), timeoutMs: 1000);
            whisper.SetGrammar(new[] { "undo" });
            Assert.Empty(Utter(whisper));
            Assert.True(whisper.LastStopFailed);
            Assert.NotNull(whisper.LastError);
        }

        [Fact]
        public void AnHttpErrorFailsTheUtterance()
        {
            using (var server = new FakeHttpServer { Respond = _ => (500, "{\"error\":\"boom\"}") })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                Assert.Empty(Utter(whisper));
                Assert.True(whisper.LastStopFailed);
                Assert.Contains("500", whisper.LastError);
            }
        }

        [Fact]
        public void ASlowServerTimesOut()
        {
            using (var server = new FakeHttpServer { DelayMs = 3000, Respond = _ => (200, "{\"text\":\"undo\"}") })
            {
                var whisper = new WhisperServerRecognizer(server.Port, timeoutMs: 300);
                whisper.SetGrammar(new[] { "undo" });
                var clock = Stopwatch.StartNew();
                Assert.Empty(Utter(whisper));
                Assert.True(whisper.LastStopFailed);
                Assert.True(clock.ElapsedMilliseconds < 2500, clock.ElapsedMilliseconds + " ms");
            }
        }

        [Fact]
        public void AClickIsNotSent()
        {
            using (var server = new FakeHttpServer())
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                Assert.Empty(Utter(whisper, samples: 800)); // 50 ms
                Assert.False(whisper.LastStopFailed);
                Assert.Empty(server.Requests);
            }
        }

        [Fact]
        public void WithoutAGrammarTheWordsGoOutAsTheyAre()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, "{\"text\":\" Rotate it 90 degrees.\"}") })
                Assert.Equal("rotate it ninety degrees", Assert.Single(Utter(new WhisperServerRecognizer(server.Port))).Text);
        }

        [Theory]
        [InlineData("{\"text\":\" Undo.\\n\"}", " Undo.\n")]
        [InlineData("{\"text\":\"say \\\"hi\\\" \\u00e9\\\\\"}", "say \"hi\" é\\")]
        [InlineData("{\"x\":1, \"text\" : \"\"}", "")]
        public void ReadsTheTextOfTheReply(string json, string expected) =>
            Assert.Equal(expected, WhisperServerRecognizer.JsonText(json));

        [Fact]
        public void TheWavHeaderDescribesTheSamples()
        {
            byte[] wav = WhisperServerRecognizer.Wav(new short[] { 1, -1, 300 }, 16000);
            Assert.Equal(44 + 6, wav.Length);
            Assert.Equal("RIFF", Encoding.ASCII.GetString(wav, 0, 4));
            Assert.Equal(16000, BitConverter.ToInt32(wav, 24));
            Assert.Equal(6, BitConverter.ToInt32(wav, 40));
            Assert.Equal(300, BitConverter.ToInt16(wav, 48));
        }

        [Fact]
        public void ThePromptNamesTheGrammarWordsItDoesntHaveYet()
        {
            string prompt = WhisperServerRecognizer.PromptFor(WhisperServerRecognizer.BlenderPrompt,
                new[] { "base plate", "cube", "x", "two", "[unk]" });
            Assert.StartsWith(WhisperServerRecognizer.BlenderPrompt, prompt);
            Assert.EndsWith(" base, plate, two.", prompt);

            var many = Enumerable.Range(0, 500).Select(i => "word" + NumberWords.ToWords(i % 1000).Replace(" ", "")).ToList();
            Assert.True(WhisperServerRecognizer.PromptFor(WhisperServerRecognizer.BlenderPrompt, many).Length <= WhisperServerRecognizer.MaxPromptChars);
            Assert.Equal("Choices.", WhisperServerRecognizer.PromptFor("Choices.", new[] { "x" }));
        }

        [Fact]
        public void TheRecognizerUsesTheGrammarPromptOnlyWhenAsked()
        {
            var plain = new WhisperServerRecognizer(1, promptWithGrammar: false);
            plain.SetGrammar(new[] { "gearbox" });
            Assert.Equal(WhisperServerRecognizer.BlenderPrompt, plain.Prompt);
            var withGrammar = new WhisperServerRecognizer(1, promptWithGrammar: true);
            withGrammar.SetGrammar(new[] { "gearbox" });
            Assert.EndsWith("gearbox.", withGrammar.Prompt);
        }

        // WhisperServer ------------------------------------------------------------------------------------------

        [Fact]
        public void AMissingExecutableIsReported()
        {
            string dir = Path.Combine(Path.GetTempPath(), "no-whisper-" + Guid.NewGuid().ToString("N"));
            using (var server = new WhisperServer(Path.Combine(dir, WhisperServer.ExecutableName), Path.Combine(dir, "m.bin"), FreePort()))
                Assert.Throws<FileNotFoundException>(server.EnsureRunning);
        }

        [Fact]
        public void APortTakenBySomethingElseIsReported()
        {
            using (var other = new FakeHttpServer { Respond = _ => (404, "not found") })
            using (var server = new WhisperServer("whisper-server", "model.bin", other.Port, startTimeoutMs: 2000))
                Assert.Contains("not like whisper-server", Assert.Throws<IOException>(server.EnsureRunning).Message);
        }

        [Fact]
        public void AServerAlreadyRunningIsReusedAndLeftRunning()
        {
            using (var running = new FakeHttpServer())
            {
                var server = new WhisperServer("whisper-server", "model.bin", running.Port);
                server.EnsureRunning();
                Assert.False(server.Owned);
                Assert.Contains(running.Requests, r => r.StartsWith("GET /health"));
                Assert.Contains(running.Requests, r => r.StartsWith("POST /inference")); // the warm-up
                server.Dispose();
                Assert.True(WhisperServer.Answers(running.Port, 1000));
            }
        }

        /// <summary>A Python stand-in for whisper-server: same arguments, /health and /inference.</summary>
        static string FakeExecutable(string dir, string transcript, int exitCode = -1)
        {
            string python = new[] { "/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3" }.FirstOrDefault(File.Exists);
            Skip.If(RuntimeInformation.IsOSPlatform(OSPlatform.Windows) || python == null, "Needs python3 on Linux or macOS");
            string script = Path.Combine(dir, WhisperServer.ExecutableName);
            File.WriteAllText(script, "#!" + python + @"
import sys, json, time
from http.server import BaseHTTPRequestHandler, HTTPServer
args = sys.argv[1:]
assert args[args.index('-m') + 1].endswith('.bin') and '-ng' in args, args
if " + exitCode + @" >= 0:
    print('error: failed to initialize whisper context', file=sys.stderr); sys.exit(" + exitCode + @")
time.sleep(0.3)  # loading the model
class H(BaseHTTPRequestHandler):
    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self): self.reply({'status': 'ok'})
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length'])); self.reply({'text': " + "\"" + transcript + "\"" + @"})
    def log_message(self, *a): pass
HTTPServer(('127.0.0.1', int(args[args.index('--port') + 1])), H).serve_forever()
");
            if (!OperatingSystem.IsWindows())
                File.SetUnixFileMode(script, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            File.WriteAllText(Path.Combine(dir, WhisperServer.TinyModel), "not a real model");
            return script;
        }

        [SkippableFact]
        public void StartsTheServerWaitsForItAndKillsItOnDispose()
        {
            string dir = Directory.CreateTempSubdirectory("whisper-fake").FullName;
            try
            {
                string exe = FakeExecutable(dir, " Undo.");
                int port = FreePort();
                var log = new List<string>();
                var server = new WhisperServer(exe, Path.Combine(dir, WhisperServer.TinyModel), port, log: log.Add);
                server.EnsureRunning();
                Assert.True(server.Owned);
                Assert.True(WhisperServer.Answers(port, 1000));
                Assert.Contains(log, l => l.Contains("ready on port " + port));

                var whisper = new WhisperServerRecognizer(port) { Server = server };
                whisper.SetGrammar(new[] { "undo", "redo" });
                Assert.Equal("undo", Assert.Single(Utter(whisper)).Text);

                whisper.Dispose(); // disposes the server it owns
                Assert.False(WhisperServer.Answers(port, 500));
            }
            finally
            {
                Directory.Delete(dir, true);
            }
        }

        [SkippableFact]
        public void AServerThatExitsAtOnceIsReportedWithItsOutput()
        {
            string dir = Directory.CreateTempSubdirectory("whisper-fake").FullName;
            try
            {
                string exe = FakeExecutable(dir, "", exitCode: 3);
                using (var server = new WhisperServer(exe, Path.Combine(dir, WhisperServer.TinyModel), FreePort()))
                {
                    var error = Assert.Throws<IOException>(server.EnsureRunning);
                    Assert.Contains("exited with code 3", error.Message);
                }
            }
            finally
            {
                Directory.Delete(dir, true);
            }
        }

        [SkippableFact]
        public void ACrashedServerIsRestartedAtTheNextUtterance()
        {
            string dir = Directory.CreateTempSubdirectory("whisper-fake").FullName;
            try
            {
                string exe = FakeExecutable(dir, " Redo.");
                int port = FreePort();
                using (var whisper = new WhisperServerRecognizer(port) { Server = new WhisperServer(exe, Path.Combine(dir, WhisperServer.TinyModel), port) })
                {
                    whisper.Server.EnsureRunning();
                    foreach (Process p in Process.GetProcesses().Where(p => SafeCommandLine(p).Contains(exe)))
                        p.Kill();
                    for (int i = 0; i < 50 && !whisper.Server.HasExited; i++)
                        Thread.Sleep(50);
                    Assert.True(whisper.Server.HasExited);

                    whisper.SetGrammar(new[] { "undo", "redo" });
                    Assert.Equal("redo", Assert.Single(Utter(whisper)).Text);
                }
                Assert.False(WhisperServer.Answers(port, 500));
            }
            finally
            {
                Directory.Delete(dir, true);
            }
        }

        static string SafeCommandLine(Process p)
        {
            try
            {
                return File.ReadAllText("/proc/" + p.Id + "/cmdline").Replace('\0', ' ');
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                return "";
            }
        }

        // VoiceRecognizers ---------------------------------------------------------------------------------------

        [Fact]
        public void WithoutAVoskModelTheFactoryFailsLikeVoskAlone()
        {
            string dir = Path.Combine(Path.GetTempPath(), "no-models-" + Guid.NewGuid().ToString("N"));
            var settings = VoiceRecognizerSettings.ForStreamingAssets(dir);
            settings.WhisperPort = FreePort();
            Assert.Throws<DirectoryNotFoundException>(() => VoiceRecognizers.Create(settings));
            settings.Kind = RecognizerKind.Vosk;
            Assert.Throws<DirectoryNotFoundException>(() => VoiceRecognizers.Create(settings));
        }

        [Fact]
        public void SettingsPointIntoStreamingAssetsAndFallBackToTheOtherModel()
        {
            string assets = Directory.CreateTempSubdirectory("streaming-assets").FullName;
            try
            {
                var settings = VoiceRecognizerSettings.ForStreamingAssets(assets);
                Assert.Equal(Path.Combine(assets, "vosk-model-small-en-us-0.15"), settings.VoskModelPath);
                Assert.Equal(Path.Combine(assets, "whisper", WhisperServer.ExecutableName), settings.ExecutablePath());
                Assert.Equal(Path.Combine(assets, "whisper", WhisperServer.TinyModel), settings.ModelPath()); // neither exists
                Directory.CreateDirectory(settings.WhisperFolder);
                File.WriteAllText(Path.Combine(settings.WhisperFolder, WhisperServer.BaseModel), "");
                Assert.Equal(Path.Combine(assets, "whisper", WhisperServer.BaseModel), settings.ModelPath());
            }
            finally
            {
                Directory.Delete(assets, true);
            }
        }
    }
}
