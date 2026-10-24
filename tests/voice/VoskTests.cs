using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using SpatialModeling.VoiceCore.Vosk;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>
    /// Real Vosk through VoiceInput and PcmConverter, with speech from voice/make-prompts.py --say (tests/voice/audio)
    /// and the prompt clips. Needs the model from voice/fetch-model.sh (or VOSK_MODEL); without it these are skipped.
    /// </summary>
    public class VoskTests
    {
        internal const string Shaft = "fd7bd4ddae444528a4fedbc562fe018b";
        static readonly TimeSpan Timeout = TimeSpan.FromSeconds(30);

        internal static string ModelPath =>
            Environment.GetEnvironmentVariable("VOSK_MODEL") ?? Path.Combine(Contract.Root, "voice", "models", VoskSpeechRecognizer.ModelName);

        static void SkipWithoutModel() =>
            Skip.IfNot(Directory.Exists(ModelPath), "No Vosk model at " + ModelPath + "; run voice/fetch-model.sh");

        /// <summary>Decoded like Unity's AudioClip.GetData: floats at the file's rate.</summary>
        internal static (float[] samples, int rate) Audio(string path)
        {
            using (var vorbis = new NVorbis.VorbisReader(path))
            {
                Assert.Equal(1, vorbis.Channels);
                var samples = new float[vorbis.TotalSamples];
                int read = vorbis.ReadSamples(samples, 0, samples.Length);
                Array.Resize(ref samples, read);
                return (samples, vorbis.SampleRate);
            }
        }

        internal static string Fixture(string name) => Path.Combine(Contract.Root, "tests", "voice", "audio", name + ".ogg");

        static string Clip(Prompt prompt) =>
            Path.Combine(Contract.Root, "voice", "VoiceCore", "Prompts", "Resources", prompt.ClipResource + ".ogg");

        /// <summary>Push-to-talk around the audio, in 20 ms microphone frames, with a little silence after it.</summary>
        internal static void Speak(VoiceInput input, string path, bool pausedForPrompt = false)
        {
            (float[] samples, int rate) = Audio(path);
            samples = samples.Concat(new float[rate / 2]).ToArray();
            int frame = rate / 50;
            input.StartUtterance();
            if (pausedForPrompt)
                input.Paused = true;
            var buffer = new float[frame];
            for (int at = 0; at < samples.Length; at += frame)
            {
                int n = Math.Min(frame, samples.Length - at);
                Array.Copy(samples, at, buffer, 0, n);
                input.Write(buffer, n, rate);
            }
            input.Paused = false;
            input.StopUtterance();
        }

        /// <summary>Everything recognized since the last call, as one result with the lowest confidence.</summary>
        internal static RecognitionResult Heard(VoiceInput input)
        {
            Assert.True(input.WaitIdle(Timeout));
            Assert.Null(input.Error);
            var results = new List<RecognitionResult>();
            while (input.TryGetResult(out RecognitionResult r))
                results.Add(r);
            return results.Count == 0 ? new RecognitionResult("", 0f)
                : new RecognitionResult(string.Join(" ", results.Select(r => r.Text)), results.Min(r => r.Confidence));
        }

        static VoiceInput Listen(VoiceSession session)
        {
            var input = new VoiceInput(() => VoskSpeechRecognizer.Load(ModelPath));
            input.SetGrammar(session.GrammarPhrases());
            Assert.True(input.WaitIdle(Timeout));
            Assert.True(input.Ready, input.Error);
            return input;
        }

        internal static VoiceSession ExampleScene()
        {
            var session = new VoiceSession();
            session.SetObjects(Contract.SnapshotObjects());
            return session;
        }

        [Fact]
        public void ModelNameMatchesTheFetchScript()
        {
            string script = File.ReadAllText(Path.Combine(Contract.Root, "voice", "fetch-model.sh"));
            Assert.Equal(VoskSpeechRecognizer.ModelName, Regex.Match(script, @"^NAME=(\S+)", RegexOptions.Multiline).Groups[1].Value);
        }

        [Fact]
        public void LibvoskLoadsAndRefusesABrokenModel()
        {
            Assert.Throws<DirectoryNotFoundException>(() => VoskSpeechRecognizer.Load(Path.Combine(Path.GetTempPath(), "no-such-model")));
            string fake = Directory.CreateTempSubdirectory("voicecore-model").FullName;
            try
            {
                Directory.CreateDirectory(Path.Combine(fake, "am"));
                File.WriteAllText(Path.Combine(fake, "am", "final.mdl"), "");
                Assert.Throws<IOException>(() => VoskSpeechRecognizer.Load(fake)); // Vosk itself refused it
            }
            finally
            {
                Directory.Delete(fake, true);
            }
        }

        [SkippableFact]
        public void EveryGrammarWordIsInTheModel()
        {
            SkipWithoutModel();
            using (VoskSpeechRecognizer vosk = VoskSpeechRecognizer.Load(ModelPath))
                Assert.Equal(new string[0], ExampleScene().GrammarPhrases().Where(w => w != "[unk]" && !vosk.HasWord(w)));
        }

        /// <summary>What a session does with the result, with the shaft selected.</summary>
        internal static string Outcome(RecognitionResult result)
        {
            VoiceSession session = ExampleScene();
            session.SetSelection(new[] { Shaft });
            return session.Hear(result).ToString();
        }

        [SkippableTheory]
        [InlineData("rotate-this-object-ninety-degrees", "rotate this object ninety degrees")]
        [InlineData("move-the-shaft-ten-millimeters-along-x", "move the shaft ten millimeters along x")]
        [InlineData("select-the-base-plate", "select the base plate")]
        [InlineData("scale-it-by-one-point-five", "scale it by one point five")]
        [InlineData("undo", "undo")]
        [InlineData("the-z-axis", "the z axis")]
        public void RecognizesCommands(string fixture, string expected)
        {
            SkipWithoutModel();
            VoiceSession session = ExampleScene();
            using (VoiceInput input = Listen(session))
            {
                Speak(input, Fixture(fixture));
                RecognitionResult heard = Heard(input);
                // Vosk may drop a filler word ("scale by one point five"); the command must be the same.
                Assert.Equal(Outcome(new RecognitionResult(expected, 1f)), Outcome(heard));
                Assert.DoesNotContain("low_confidence", Outcome(heard));
            }
        }

        [SkippableFact]
        public void ChatterNeverBecomesACommand()
        {
            SkipWithoutModel();
            VoiceSession session = ExampleScene();
            session.SetSelection(new[] { Shaft });
            using (VoiceInput input = Listen(session))
            {
                Speak(input, Fixture("chatter"));
                VoiceTurn turn = session.Hear(Heard(input));
                Assert.Null(turn.Command);
            }
        }

        [SkippableFact]
        public void PlanDialogueFromSpeechSendsTheRotateExample()
        {
            SkipWithoutModel();
            VoiceSession session = ExampleScene();
            using (VoiceInput input = Listen(session))
            {
                Speak(input, Fixture("rotate-this-object-ninety-degrees"));
                Assert.Equal(new[] { Prompt.AskTarget }, session.Hear(Heard(input)).Prompts);
                Assert.Equal(new[] { Prompt.AskAxis }, session.SetSelection(new[] { Shaft }).Prompts);
                Speak(input, Fixture("the-z-axis"));
                VoiceTurn done = session.Hear(Heard(input));

                HostCommand command = HostCommand.From(done.Command);
                Assert.Equal("object.rotate", command.Op);
                Assert.Equal(Shaft, command.TargetId);
                Assert.True(Contract.Validate(Contract.Envelope(command, 42)).IsValid);
            }
        }

        [SkippableFact]
        public void AGrammarChangeDuringAnUtteranceKeepsIt()
        {
            SkipWithoutModel();
            VoiceSession session = ExampleScene();
            using (VoiceInput input = Listen(session))
            {
                (float[] samples, int rate) = Audio(Fixture("undo"));
                input.StartUtterance();
                input.Write(samples, samples.Length / 2, rate);
                session.SetObjects(Contract.SnapshotObjects().Take(1)); // a scene update while the button is down
                input.SetGrammar(session.GrammarPhrases());
                float[] rest = samples.Skip(samples.Length / 2).Concat(new float[rate / 2]).ToArray();
                input.Write(rest, rest.Length, rate);
                input.StopUtterance();
                Assert.Equal("undo", Heard(input).Text);

                Speak(input, Fixture("move-the-shaft-ten-millimeters-along-x")); // the shaft is no longer in the grammar
                Assert.DoesNotContain("shaft", Heard(input).Text);
            }
        }

        [SkippableFact]
        public void AnOpenMicrophoneTakesANewGrammarAtTheNextUtterance()
        {
            SkipWithoutModel();
            VoiceSession session = ExampleScene();
            using (VoiceInput input = Listen(session))
            {
                input.StartUtterance(); // once: Vosk ends utterances at pauses by itself
                session.SetObjects(Contract.SnapshotObjects().Take(1)); // the shaft leaves the scene
                input.SetGrammar(session.GrammarPhrases());
                foreach (string fixture in new[] { "undo", "move-the-shaft-ten-millimeters-along-x" })
                {
                    (float[] samples, int rate) = Audio(Fixture(fixture));
                    float[] withPause = samples.Concat(new float[rate]).ToArray();
                    input.Write(withPause, withPause.Length, rate);
                }
                Assert.True(input.WaitIdle(Timeout));
                var heard = new List<string>();
                while (input.TryGetResult(out RecognitionResult r))
                    heard.Add(r.Text);
                Assert.Equal("undo", heard[0]);
                Assert.Equal(2, heard.Count);
                Assert.DoesNotContain("shaft", heard[1]);
                input.StopUtterance();
            }
        }

        [SkippableFact]
        public void APromptHeardWhilePausedIsNeverRecognized()
        {
            SkipWithoutModel();
            VoiceSession session = ExampleScene();
            using (VoiceInput input = Listen(session))
            {
                // Unpaused, the microphone would pick the axis question up as words...
                Speak(input, Clip(Prompt.AskAxis));
                Assert.NotEqual("", Heard(input).Text);
                // ...paused, as while the prompt plays, nothing comes out.
                Speak(input, Clip(Prompt.AskAxis), pausedForPrompt: true);
                Assert.Equal("", Heard(input).Text);
            }
        }
    }
}
