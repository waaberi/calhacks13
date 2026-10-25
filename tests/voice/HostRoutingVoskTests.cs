using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SpatialModeling.VoiceCore.Vosk;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>The "which one?" grammar with real Vosk (skipped without the model, like VoskTests).</summary>
    public class HostRoutingVoskTests
    {
        static readonly TimeSpan Timeout = TimeSpan.FromSeconds(30);

        static string ModelPath =>
            Environment.GetEnvironmentVariable("VOSK_MODEL") ?? Path.Combine(Contract.Root, "voice", "models", VoskSpeechRecognizer.ModelName);

        static void SkipWithoutModel() =>
            Skip.IfNot(Directory.Exists(ModelPath), "No Vosk model at " + ModelPath + "; run voice/fetch-model.sh");

        static string Clip(string name) => Path.Combine(Contract.Root, "tests", "voice", "audio", name + ".ogg");

        /// <summary>A session that asked the host and got three candidates back.</summary>
        static VoiceSession Asking()
        {
            var session = new VoiceSession(new VoiceSessionOptions { AskHost = true }, () => DateTime.UtcNow);
            session.SetObjects(Contract.SnapshotObjects());
            VoiceTurn sent = session.Hear(new RecognitionResult("smooth it", 0.95f));
            session.ResolveSent(sent.Resolve, "m");
            session.HostAnswered("m", new VoiceCandidates("r", VoiceDecision.Ask, null, 30, new[]
            {
                new VoiceCandidate(1, "Subdivision Surface, level 1"), new VoiceCandidate(2, "Shade smooth"), new VoiceCandidate(3, "Smooth vertices"),
            }));
            Assert.NotNull(session.Choice);
            return session;
        }

        /// <summary>Push-to-talk around the clip, in 20 ms frames, with the recommended pre-roll and post-roll.</summary>
        static RecognitionResult Hear(VoiceSession session, string clip)
        {
            using (var input = new VoiceInput(() => VoskSpeechRecognizer.Load(ModelPath), 16000,
                VoiceInput.RecommendedPrerollMs, VoiceInput.RecommendedPostrollMs))
            {
                input.SetGrammar(session.GrammarPhrases());
                Assert.True(input.WaitIdle(Timeout));
                Assert.True(input.Ready, input.Error);
                float[] samples;
                int rate;
                using (var vorbis = new NVorbis.VorbisReader(clip))
                {
                    samples = new float[vorbis.TotalSamples];
                    Array.Resize(ref samples, vorbis.ReadSamples(samples, 0, samples.Length));
                    rate = vorbis.SampleRate;
                }
                int frame = rate / 50;
                var buffer = new float[frame];
                void Feed(float[] audio, int from, int count)
                {
                    for (int at = from; at < from + count; at += frame)
                    {
                        int n = Math.Min(frame, from + count - at);
                        Array.Copy(audio, at, buffer, 0, n);
                        input.Write(buffer, n, rate);
                    }
                }
                var silence = new float[rate / 2];
                Feed(silence, 0, silence.Length); // the room before the press fills the pre-roll
                input.StartUtterance();            // pressed right at the first word
                Feed(samples, 0, samples.Length);
                input.StopUtterance();
                Feed(silence, 0, silence.Length);  // the post-roll
                Assert.True(input.WaitIdle(Timeout));
                Assert.Null(input.Error);
                var results = new List<RecognitionResult>();
                while (input.TryGetResult(out RecognitionResult r))
                    results.Add(r);
                return results.Count == 0 ? new RecognitionResult("", 0f)
                    : new RecognitionResult(string.Join(" ", results.Select(r => r.Text)), results.Min(r => r.Confidence));
            }
        }

        [SkippableFact]
        public void EveryAnswerWordIsInTheModel()
        {
            SkipWithoutModel();
            using (VoskSpeechRecognizer vosk = VoskSpeechRecognizer.Load(ModelPath))
            {
                IEnumerable<string> words = Asking().GrammarPhrases().Where(p => p != "[unk]").SelectMany(p => p.Split(' '));
                Assert.Equal(new string[0], words.Where(w => !vosk.HasWord(w)));
            }
        }

        [SkippableFact]
        public void TheSecondOneIsHeardAsChoiceTwo()
        {
            SkipWithoutModel();
            VoiceSession session = Asking();
            RecognitionResult heard = Hear(session, Clip("the-second-one"));
            Assert.Equal("the second one", heard.Text);
            VoiceTurn turn = session.Hear(heard);
            Assert.Equal(CommandKind.Run, turn.Command.Kind);
            Assert.Equal(2, turn.Command.Choice);
        }

        [SkippableFact]
        public void ChatterWhileAskingIsNeverAnAnswer()
        {
            SkipWithoutModel();
            VoiceSession session = Asking();
            RecognitionResult heard = Hear(session, Clip("chatter"));
            VoiceTurn turn = session.Hear(heard);
            Assert.Null(turn.Command);
            Assert.NotNull(session.Choice);
        }
    }
}
