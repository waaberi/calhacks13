using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using SpatialModeling.VoiceCore.Whisper;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>
    /// A real whisper-server started by <see cref="VoiceRecognizers.Create"/>, fed through VoiceInput like the app.
    /// Needs the models from <c>voice/fetch-whisper.sh --models-only</c> (or WHISPER_MODELS, a folder) and a
    /// whisper-server built for this OS in that folder (or WHISPER_SERVER); see voice/README.md. CI has neither, so
    /// these are skipped there.
    /// </summary>
    public class WhisperIntegrationTests
    {
        static string Folder =>
            Environment.GetEnvironmentVariable("WHISPER_MODELS") ?? Path.Combine(Contract.Root, "voice", "models", "whisper");

        static string Executable =>
            Environment.GetEnvironmentVariable("WHISPER_SERVER") ?? Path.Combine(Folder, WhisperServer.ExecutableName);

        static void SkipWithoutWhisper() =>
            Skip.IfNot(File.Exists(Executable) && File.Exists(Path.Combine(Folder, WhisperServer.TinyModel)),
                "No whisper-server at " + Executable + " or no " + WhisperServer.TinyModel + " in " + Folder + "; see voice/README.md");

        static int FreePort()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0);
            probe.Start();
            int port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            return port;
        }

        static VoiceRecognizerSettings Settings(RecognizerKind kind) => new VoiceRecognizerSettings
        {
            Kind = kind,
            VoskModelPath = VoskTests.ModelPath,
            WhisperFolder = Folder,
            WhisperExecutable = Executable,
            WhisperModel = WhisperServer.TinyModel,
            WhisperPort = FreePort(),
            WhisperTimeoutMs = 20000, // other test runs may share the CPU
        };

        static VoiceInput Listen(VoiceSession session, VoiceRecognizerSettings settings)
        {
            var input = new VoiceInput(() => VoiceRecognizers.Create(settings));
            input.SetGrammar(session.GrammarPhrases());
            Assert.True(input.WaitIdle(TimeSpan.FromSeconds(60)));
            Assert.True(input.Ready, input.Error);
            return input;
        }

        [SkippableTheory]
        [InlineData("rotate-this-object-ninety-degrees", "rotate this object ninety degrees")]
        [InlineData("move-the-shaft-ten-millimeters-along-x", "move the shaft ten millimeters along x")]
        [InlineData("select-the-base-plate", "select the base plate")]
        [InlineData("scale-it-by-one-point-five", "scale it by one point five")]
        [InlineData("undo", "undo")]
        public void WhisperAloneHearsTheCommands(string fixture, string expected)
        {
            SkipWithoutWhisper();
            VoiceSession session = VoskTests.ExampleScene();
            using (VoiceInput input = Listen(session, Settings(RecognizerKind.Whisper)))
            {
                VoskTests.Speak(input, VoskTests.Fixture(fixture));
                RecognitionResult heard = VoskTests.Heard(input);
                Assert.Equal(VoskTests.Outcome(new RecognitionResult(expected, 1f)), VoskTests.Outcome(heard));
            }
        }

        [SkippableFact]
        public void TheFastPathHearsCommandsAndIgnoresChatter()
        {
            SkipWithoutWhisper();
            Skip.IfNot(Directory.Exists(VoskTests.ModelPath), "No Vosk model at " + VoskTests.ModelPath + "; run voice/fetch-model.sh");
            VoiceSession session = VoskTests.ExampleScene();
            using (VoiceInput input = Listen(session, Settings(RecognizerKind.FastPath)))
            {
                foreach ((string fixture, string expected) in new[]
                {
                    ("rotate-this-object-ninety-degrees", "rotate this object ninety degrees"),
                    ("scale-it-by-one-point-five", "scale it by one point five"),
                    ("undo", "undo"),
                })
                {
                    VoskTests.Speak(input, VoskTests.Fixture(fixture));
                    Assert.Equal(VoskTests.Outcome(new RecognitionResult(expected, 1f)), VoskTests.Outcome(VoskTests.Heard(input)));
                }

                session.SetSelection(new[] { VoskTests.Shaft });
                VoskTests.Speak(input, VoskTests.Fixture("chatter"));
                Assert.Null(session.Hear(VoskTests.Heard(input)).Command);
            }
        }

        [SkippableFact]
        public void DisposingVoiceInputStopsTheServer()
        {
            SkipWithoutWhisper();
            VoiceRecognizerSettings settings = Settings(RecognizerKind.Whisper);
            VoiceInput input = Listen(VoskTests.ExampleScene(), settings);
            Assert.True(WhisperServer.Answers(settings.WhisperPort, 1000));
            input.Dispose();
            Assert.False(WhisperServer.Answers(settings.WhisperPort, 500));
        }
    }
}
