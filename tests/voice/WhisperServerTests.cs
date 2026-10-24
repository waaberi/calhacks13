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

        static List<RecognitionResult> Utter(WhisperServerRecognizer whisper, int samples = 16000, bool silent = false)
        {
            var heard = new List<RecognitionResult>();
            whisper.Recognized += heard.Add;
            whisper.Start(16000);
            whisper.AcceptAudio(silent ? new short[samples] : Tone(samples), samples);
            whisper.Stop();
            return heard;
        }

        /// <summary>Every <see cref="IReportsNoResult.NoResult"/> the recognizer raises from now on.</summary>
        static List<NoResultReason> Reasons(IReportsNoResult recognizer)
        {
            var reasons = new List<NoResultReason>();
            recognizer.NoResult += reasons.Add;
            return reasons;
        }

        /// <summary>A 200 Hz tone, RMS about 1,400 (-27 dBFS): loud enough for the speech gate, like a voice.</summary>
        static short[] Tone(int samples, float amplitude = 2000f)
        {
            var tone = new short[samples];
            for (int i = 0; i < samples; i++)
                tone[i] = (short)(amplitude * Math.Sin(2 * Math.PI * 200 * i / 16000.0));
            return tone;
        }

        static string Reply(string text) => "{\"text\":\"" + text + "\"}";

        /// <summary>A stand-in for Vosk in the fast path: raises <see cref="OnStop"/> at Stop.</summary>
        sealed class FakeVosk : ISpeechRecognizer
        {
            public readonly List<RecognitionResult> OnStop = new List<RecognitionResult>();
            public event Action<RecognitionResult> Recognized;
            public void SetGrammar(IReadOnlyList<string> phrases) { }
            public void Start(int sampleRate) { }
            public void AcceptAudio(short[] samples, int count) { }

            public void Stop()
            {
                foreach (RecognitionResult r in OnStop)
                    Recognized?.Invoke(r);
            }

            public void Dispose() { }
        }

        static readonly string[] Commands = { "add a cone", "undo", "you", "[unk]" };

        [Fact]
        public void ASilentPressIsNotSentAndRaisesNothing()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(" you")) })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                whisper.SetGrammar(Commands);
                List<NoResultReason> reasons = Reasons(whisper);
                Assert.Empty(Utter(whisper, silent: true)); // a second of digital silence, like the Unity run's press
                Assert.Equal(new[] { NoResultReason.Silence }, reasons); // said nowhere, only shown
                Assert.True(whisper.LastWasSilence);
                Assert.False(whisper.LastStopFailed);
                Assert.Empty(server.Requests);
            }
        }

        [Fact]
        public void AQuietRoomIsSilenceButQuietSpeechIsSent()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(" Undo.")) })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                whisper.SetGrammar(Commands);
                var heard = new List<RecognitionResult>();
                whisper.Recognized += heard.Add;
                List<NoResultReason> reasons = Reasons(whisper);

                whisper.Start(16000);
                whisper.AcceptAudio(Tone(16000, amplitude: 40f), 16000); // RMS 28, -61 dBFS: room noise
                whisper.Stop();
                Assert.Empty(heard);
                Assert.Empty(server.Requests);
                Assert.Equal(new[] { NoResultReason.Silence }, reasons);

                whisper.Start(16000);
                whisper.AcceptAudio(Tone(16000, amplitude: 300f), 16000); // RMS 212: quieter than any real clip measured
                whisper.Stop();
                Assert.Equal("undo", Assert.Single(heard).Text);
                Assert.Single(server.Requests);
                Assert.Single(reasons); // a result, so no reason
            }
        }

        [Fact]
        public void TheSpeechGateNeedsThreeLoudFrames()
        {
            var samples = new short[16000];
            Array.Copy(Tone(960), 0, samples, 4800, 960); // two 30 ms frames of sound
            Assert.False(WhisperServerRecognizer.HasSpeech(samples, 16000, WhisperServerRecognizer.DefaultMinSpeechRms));
            Array.Copy(Tone(1440), 0, samples, 4800, 1440); // three
            Assert.True(WhisperServerRecognizer.HasSpeech(samples, 16000, WhisperServerRecognizer.DefaultMinSpeechRms));
            Assert.True(WhisperServerRecognizer.HasSpeech(new short[16000], 16000, 0f)); // 0 turns the gate off
        }

        [Theory]
        [InlineData(" you")]
        [InlineData(" You.")]
        [InlineData(" Thank you.")]
        [InlineData(" Thanks for watching!")]
        [InlineData(" Bye.")]
        [InlineData("[BLANK_AUDIO]")]
        [InlineData(" (wind blowing)")]
        [InlineData(" Um.")]
        public void SilenceHallucinationsRaiseNothing(string transcript)
        {
            Assert.True(WhisperServerRecognizer.IsSilenceHallucination(transcript));
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(transcript)) })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                whisper.SetGrammar(Commands); // "you" is a grammar word, as in the host's grammar
                List<NoResultReason> reasons = Reasons(whisper);
                Assert.Empty(Utter(whisper));
                Assert.Equal(new[] { NoResultReason.Silence }, reasons);
                Assert.True(whisper.LastWasHallucination);
                Assert.True(whisper.LastWasSilence);
            }
        }

        [Theory]
        [InlineData(" Undo.")]
        [InlineData(" Add a cone.")]
        [InlineData(" You add a cone.")]
        [InlineData(" Thank you, add a cone.")]
        [InlineData("")]
        public void CommandsAreNotHallucinations(string transcript) =>
            Assert.False(WhisperServerRecognizer.IsSilenceHallucination(transcript));

        [Fact]
        public void TheFastPathDropsAHallucinationVoskDidntHear()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(" you")) })
            {
                var vosk = new FakeVosk();
                var hybrid = new FastPathRecognizer(vosk, new WhisperServerRecognizer(server.Port));
                hybrid.SetGrammar(Commands);
                var heard = new List<RecognitionResult>();
                hybrid.Recognized += heard.Add;
                List<NoResultReason> reasons = Reasons(hybrid);

                hybrid.Start(16000);
                hybrid.AcceptAudio(Tone(16000), 16000); // noise loud enough for the gate; Vosk heard no words
                hybrid.Stop();
                Assert.Empty(heard);
                Assert.Equal(FastPathOutcome.Silence, hybrid.LastOutcome);
                Assert.Equal(new[] { NoResultReason.Silence }, reasons);

                vosk.OnStop.Add(new RecognitionResult("you", 0.7f)); // Vosk heard speech too: "you" is what was said
                hybrid.Start(16000);
                hybrid.AcceptAudio(Tone(16000), 16000);
                hybrid.Stop();
                Assert.Equal("you", Assert.Single(heard).Text);
                Assert.Equal(FastPathOutcome.Slow, hybrid.LastOutcome);
                Assert.Single(reasons);
            }
        }

        [Fact]
        public void TheFastPathSaysNothingForASilentPressAndNoResultForChatter()
        {
            string reply = " you";
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(reply)) })
            {
                var vosk = new FakeVosk();
                vosk.OnStop.Add(new RecognitionResult("undo", 0.4f));
                var hybrid = new FastPathRecognizer(vosk, new WhisperServerRecognizer(server.Port));
                hybrid.SetGrammar(Commands);
                var heard = new List<RecognitionResult>();
                hybrid.Recognized += heard.Add;
                List<NoResultReason> reasons = Reasons(hybrid);

                hybrid.Start(16000);
                hybrid.AcceptAudio(new short[16000], 16000); // silence: Whisper isn't asked, Vosk's guess doesn't go out
                hybrid.Stop();
                Assert.Empty(heard);
                Assert.Equal(FastPathOutcome.Silence, hybrid.LastOutcome);
                Assert.Empty(server.Requests);
                Assert.Equal(new[] { NoResultReason.Silence }, reasons);

                reply = " This is our project.";
                hybrid.Start(16000);
                hybrid.AcceptAudio(Tone(16000), 16000);
                hybrid.Stop();
                Assert.Empty(heard); // speech that is no command: no result, and "didn't catch that"
                Assert.Equal(new[] { NoResultReason.Silence, NoResultReason.NotUnderstood }, reasons);
                Assert.Equal(FastPathOutcome.Slow, hybrid.LastOutcome);
            }
        }

        [Fact]
        public void TheFastPathCallsAHallucinationThatSnapsToNothingSilence()
        {
            // Whisper keeps hallucinations in the fast path and snaps them: "thanks for watching" snaps onto no phrase,
            // which alone would be "didn't catch that". Vosk heard nothing, so it is an accidental press after all.
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(" Thanks for watching!")) })
            {
                var hybrid = new FastPathRecognizer(new FakeVosk(), new WhisperServerRecognizer(server.Port));
                hybrid.SetGrammar(Commands);
                var heard = new List<RecognitionResult>();
                hybrid.Recognized += heard.Add;
                List<NoResultReason> reasons = Reasons(hybrid);
                hybrid.Start(16000);
                hybrid.AcceptAudio(Tone(16000), 16000);
                hybrid.Stop();
                Assert.Empty(heard);
                Assert.Equal(new[] { NoResultReason.Silence }, reasons);
                Assert.Equal(FastPathOutcome.Silence, hybrid.LastOutcome);
            }
        }

        [Fact]
        public void ACommandSaidWhileAskingReachesTheSessionAsThatCommand()
        {
            string reply = "";
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(reply)) })
            {
                var session = new VoiceSession(new VoiceSessionOptions { AskHost = true }, () => DateTime.UtcNow);
                session.SetObjects(new[] { new SceneObject("id-cube", "Cube") });
                session.SetHostGrammar(new[] { "make copies", "make it thicker", "shade smooth" });
                var vosk = new FakeVosk();
                var hybrid = new FastPathRecognizer(vosk, new WhisperServerRecognizer(server.Port));
                var heard = new List<RecognitionResult>();
                hybrid.Recognized += heard.Add;
                List<NoResultReason> reasons = Reasons(hybrid);
                hybrid.SetGrammar(session.GrammarPhrases());

                void Ask()
                {
                    VoiceTurn sent = session.Hear(new RecognitionResult("make copies", 1f));
                    session.ResolveSent(sent.Resolve, "msg1");
                    VoiceTurn asked = session.HostAnswered("msg1", new VoiceCandidates("res1", VoiceDecision.Ask, null, 30, new[]
                    {
                        new VoiceCandidate(1, "Array", "object.modifier_add", needsTarget: true),
                        new VoiceCandidate(2, "duplicate", "object.duplicate", needsTarget: true),
                    }));
                    Assert.True(asked.GrammarChanged);
                    hybrid.SetGrammar(session.GrammarPhrases()); // what the adapter does: answers only
                }

                RecognitionResult Say(string voskHeard, float voskConfidence, string whisperWrote)
                {
                    vosk.OnStop.Clear();
                    vosk.OnStop.Add(new RecognitionResult(voskHeard, voskConfidence));
                    reply = whisperWrote;
                    heard.Clear();
                    hybrid.Start(16000);
                    hybrid.AcceptAudio(Tone(16000), 16000);
                    hybrid.Stop();
                    return Assert.Single(heard);
                }

                Ask();
                RecognitionResult command = Say("[unk]", 1f, " Make it thicker."); // Vosk had only the answers
                Assert.Equal("make it thicker", command.Text);
                Assert.Equal(1f, command.Confidence);
                VoiceTurn turn = session.Hear(command);
                Assert.True(turn.ChoiceDismissed);
                Assert.Equal("make it thicker", turn.Resolve.Text); // to the host, as a new command
                Assert.Null(session.Choice);
                hybrid.SetGrammar(session.GrammarPhrases()); // GrammarChanged: the full grammar again
                Assert.Contains("make it thicker", hybrid.SlowGrammar);

                Ask();
                RecognitionResult answer = Say("two", 0.6f, " Two."); // Vosk isn't sure: Whisper still hears the answer
                Assert.Equal("two", answer.Text);
                VoiceTurn picked = session.Hear(answer);
                Assert.Equal(CommandKind.Run, picked.Command.Kind);
                Assert.Equal(2, picked.Command.Choice);
                Assert.Empty(reasons);
            }
        }

        [Fact]
        public void WhenWhisperFailsAndVoskHeardNothingTheFastPathGivesNoReason()
        {
            var hybrid = new FastPathRecognizer(new FakeVosk(), new WhisperServerRecognizer(FreePort(), timeoutMs: 1000));
            hybrid.SetGrammar(Commands);
            var heard = new List<RecognitionResult>();
            hybrid.Recognized += heard.Add;
            List<NoResultReason> reasons = Reasons(hybrid);
            hybrid.Start(16000);
            hybrid.AcceptAudio(Tone(16000), 16000);
            hybrid.Stop();
            Assert.Empty(heard);
            Assert.Empty(reasons); // VoiceInput reports it as silence: it may have been noise
            Assert.Equal(FastPathOutcome.SlowFailed, hybrid.LastOutcome);
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
                Assert.Equal(WhisperServerRecognizer.DefaultGuessConfidence, heard[0].Confidence); // "at" became "add": a guess
                Assert.InRange(whisper.LastSnap.Similarity, PhraseSnapper.DefaultThreshold, 0.99f);
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

        [Theory]
        [InlineData(" Add a cone, please.", "add a cone", 0.6f, 0.99f)] // words left out, none replaced
        [InlineData(" Add a cone.", "add a cone", 1f, 1f)]
        public void WordForWordSnapsKeepTheirSimilarity(string transcript, string expected, float min, float max)
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, "{\"text\":\"" + transcript + "\"}") })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                whisper.SetGrammar(new[] { "add a cone", "undo", "[unk]" });
                RecognitionResult heard = Assert.Single(Utter(whisper));
                Assert.Equal(expected, heard.Text);
                Assert.InRange(heard.Confidence, min, max);
            }
        }

        [Fact]
        public void GuessesMayRunWhenAllowed()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, "{\"text\":\" At a cone.\"}") })
            {
                var whisper = new WhisperServerRecognizer(server.Port, guessConfidence: 1f);
                whisper.SetGrammar(new[] { "add a cone", "undo" });
                RecognitionResult heard = Assert.Single(Utter(whisper));
                Assert.False(whisper.LastSnap.WordForWord);
                Assert.Equal(whisper.LastSnap.Similarity, heard.Confidence);
            }
        }

        [Fact]
        public void ChatterRaisesNoResult()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, "{\"text\":\" This is our project.\"}") })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                whisper.SetGrammar(new[] { "add a cone", "undo", "[unk]" });
                List<NoResultReason> reasons = Reasons(whisper);
                Assert.Empty(Utter(whisper)); // speech, but no command: "didn't catch that"
                Assert.Equal(new[] { NoResultReason.NotUnderstood }, reasons);
                Assert.False(whisper.LastWasSilence);
                Assert.False(whisper.LastStopFailed);
                Assert.False(whisper.LastSnap.Accepted);
            }
        }

        [Fact]
        public void ThroughVoiceInputChatterSaysDidntCatchThatAndASilentPressSaysNothing()
        {
            using (var server = new FakeHttpServer { Respond = _ => (200, Reply(" This is our project.")) })
            {
                var whisper = new WhisperServerRecognizer(server.Port);
                var input = new VoiceInput(() => whisper, 16000, 0, 0);
                var session = new VoiceSession();
                try
                {
                    Assert.True(input.WaitIdle(TimeSpan.FromSeconds(5)) && input.Ready, input.Error);
                    input.SetGrammar(session.GrammarPhrases());

                    void Press(float amplitude)
                    {
                        var audio = new float[16000];
                        for (int i = 0; i < audio.Length; i++)
                            audio[i] = amplitude * (float)Math.Sin(2 * Math.PI * 200 * i / 16000.0);
                        input.StartUtterance();
                        input.Write(audio, audio.Length, 16000);
                        input.StopUtterance();
                        Assert.True(input.WaitIdle(TimeSpan.FromSeconds(10)));
                        Assert.False(input.TryGetResult(out _));
                    }

                    Press(0.06f); // speech that is no command
                    Assert.True(input.TryGetNoResult(out NoResultReason reason));
                    Assert.Equal(NoResultReason.NotUnderstood, reason);
                    Assert.Equal(new[] { Prompt.LowConfidence.Id }, Fixture.Prompts(session.NothingRecognized(reason)));

                    Press(0f); // an accidental press
                    Assert.True(input.TryGetNoResult(out reason));
                    Assert.Equal(NoResultReason.Silence, reason);
                    Assert.Empty(session.NothingRecognized(reason).Prompts);
                    Assert.Single(server.Requests); // the silent press never reached Whisper
                }
                finally
                {
                    input.Dispose();
                }
            }
        }

        [Fact]
        public void NoServerFailsTheUtterance()
        {
            var whisper = new WhisperServerRecognizer(FreePort(), timeoutMs: 1000);
            whisper.SetGrammar(new[] { "undo" });
            List<NoResultReason> reasons = Reasons(whisper);
            Assert.Empty(Utter(whisper));
            Assert.Empty(reasons); // it may have been noise: VoiceInput counts it as silence
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
                List<NoResultReason> reasons = Reasons(whisper);
                Assert.Empty(Utter(whisper, samples: 800)); // 50 ms
                Assert.Equal(new[] { NoResultReason.Silence }, reasons);
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
        public void AnswersTellsAListeningPortFromAClosedOne()
        {
            using (var running = new FakeHttpServer())
                Assert.True(WhisperServer.Answers(running.Port, 300));
            var clock = Stopwatch.StartNew();
            Assert.False(WhisperServer.Answers(FreePort(), 300));
            Assert.InRange(clock.ElapsedMilliseconds, 0, 2000);
        }

        [Fact]
        public void TheCudaBuildIsRecognizedByItsLibrary()
        {
            string dir = Path.Combine(Path.GetTempPath(), "whisper-gpu-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            try
            {
                string exe = Path.Combine(dir, "whisper-server.exe");
                File.WriteAllText(exe, "");
                Assert.False(WhisperServer.HasGpuBuild(exe)); // the CPU build: -ng, whatever the PC has
                File.WriteAllText(Path.Combine(dir, "ggml-cuda.dll"), "");
                Assert.True(WhisperServer.HasGpuBuild(exe)); // fetch-whisper.sh --cuda
                Assert.False(WhisperServer.HasGpuBuild(null));
                Assert.Null(new VoiceRecognizerSettings().WhisperUseGpu); // auto: the GPU only with the CUDA build
            }
            finally
            {
                Directory.Delete(dir, true);
            }
        }

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

        [Fact]
        public void AReusedServerThatWentAwayNeedsAStartAndAFailedRestartIsNotRetried()
        {
            string dir = Path.Combine(Path.GetTempPath(), "no-whisper-" + Guid.NewGuid().ToString("N"));
            var running = new FakeHttpServer { Respond = _ => (200, "{\"text\":\" Undo.\"}") };
            var server = new WhisperServer(Path.Combine(dir, WhisperServer.ExecutableName), Path.Combine(dir, "m.bin"), running.Port);
            using (var whisper = new WhisperServerRecognizer(running.Port) { Server = server })
            {
                server.EnsureRunning(); // failed on CI when Answers used ConnectAsync().Wait(300) (see Answers)
                Assert.False(server.NeedsStart);
                whisper.SetGrammar(new[] { "undo", "redo" });
                Assert.Equal("undo", Assert.Single(Utter(whisper)).Text);

                running.Dispose(); // the other app's server quit
                Assert.True(server.NeedsStart);
                Assert.Empty(Utter(whisper)); // tries to start its own: there is none here
                Assert.True(whisper.LastStopFailed);
                Assert.Contains("No whisper-server", whisper.LastError);

                var clock = Stopwatch.StartNew();
                Assert.Empty(Utter(whisper)); // no second start: fails at once, so Vosk answers without waiting
                Assert.True(whisper.LastStopFailed);
                Assert.Contains("could not be restarted", whisper.LastError);
                Assert.True(clock.ElapsedMilliseconds < 150, clock.ElapsedMilliseconds + " ms");
            }
        }

        [Fact]
        public void TheVisualCppRuntimeIsLookedForInEveryFolder()
        {
            string first = Directory.CreateTempSubdirectory("dlls").FullName, second = Directory.CreateTempSubdirectory("dlls").FullName;
            try
            {
                string[] runtime = { "msvcp140.dll", "vcruntime140.dll" };
                Assert.Equal("msvcp140.dll", WhisperServer.MissingLibrary(runtime, new[] { first, second }));
                File.WriteAllText(Path.Combine(first, "msvcp140.dll"), "");
                Assert.Equal("vcruntime140.dll", WhisperServer.MissingLibrary(runtime, new[] { first, second }));
                File.WriteAllText(Path.Combine(second, "vcruntime140.dll"), "");
                Assert.Null(WhisperServer.MissingLibrary(runtime, new[] { first, second }));
            }
            finally
            {
                Directory.Delete(first, true);
                Directory.Delete(second, true);
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
                Process started = Assert.Single(Process.GetProcesses(), p => SafeCommandLine(p).Contains(exe));
                Assert.Equal(ProcessPriorityClass.BelowNormal, started.PriorityClass); // VR rendering comes first

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
