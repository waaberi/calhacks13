using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using SpatialModeling.VoiceCore;
using Vosk;

namespace SpatialModeling.VoskSpike
{
    /// <summary>
    /// Recognizes WAV samples with and without the VoiceCore grammar and runs the results through a VoiceSession.
    /// Usage: dotnet run --project voice/VoskSpike -- MODEL_DIR SAMPLES_DIR
    /// Each sample is NAME.wav (16-bit mono PCM) with NAME.txt holding the expected words, or "-" for speech
    /// that must not produce a command.
    /// </summary>
    static class Program
    {
        static readonly SceneObject[] Objects =
        {
            new SceneObject("id-cube", "Cube"), new SceneObject("id-sphere", "Sphere"), new SceneObject("id-cylinder", "Cylinder"),
        };

        static int Main(string[] args)
        {
            if (args.Length != 2)
            {
                Console.Error.WriteLine("usage: VoskSpike MODEL_DIR SAMPLES_DIR");
                return 2;
            }
            Vosk.Vosk.SetLogLevel(-1);
            var clock = Stopwatch.StartNew();
            using var model = new Model(args[0]);
            Console.WriteLine($"Model loaded in {clock.ElapsedMilliseconds} ms");

            var session = new VoiceSession();
            session.SetObjects(Objects);
            IReadOnlyList<string> grammar = session.GrammarPhrases();
            string[] missing = grammar.Where(w => w != "[unk]" && model.FindWord(w) < 0).ToArray();
            Console.WriteLine($"Grammar: {grammar.Count} words; missing from the model: {(missing.Length == 0 ? "none" : string.Join(", ", missing))}");

            using var restricted = new VoskSpeechRecognizer(model);
            restricted.SetGrammar(grammar);
            using var free = new VoskSpeechRecognizer(model);

            int total = 0, exact = 0, freeExact = 0;
            double audioSeconds = 0, decodeSeconds = 0;
            var heard = new Dictionary<string, RecognitionResult>();
            var samples = new List<(string expected, RecognitionResult result)>();
            float threshold = new VoiceSessionOptions().MinConfidence;
            foreach (string wav in Directory.GetFiles(args[1], "*.wav").OrderBy(p => p, StringComparer.Ordinal))
            {
                string expected = File.ReadAllText(Path.ChangeExtension(wav, ".txt")).Trim();
                (short[] pcm, int rate) = ReadWav(wav);
                audioSeconds += pcm.Length / (double)rate;
                clock.Restart();
                RecognitionResult result = Recognize(restricted, pcm, rate);
                decodeSeconds += clock.Elapsed.TotalSeconds;
                RecognitionResult freeResult = Recognize(free, pcm, rate);
                heard[Path.GetFileNameWithoutExtension(wav)] = result;
                samples.Add((expected, result));

                VoiceTurn turn = Outcome(result, threshold);
                string verdict = expected == "-" ? (turn.Command == null ? "ok  " : "FAIL") : result.Text == expected ? "ok  " : "MISS";
                Console.WriteLine($"{verdict} {Path.GetFileName(wav),-34} heard '{result.Text}' ({result.Confidence:0.00})" +
                    (expected == "-" ? "" : $" free '{freeResult.Text}'") + $" -> {turn}");
                if (expected == "-")
                    continue;
                total++;
                exact += result.Text == expected ? 1 : 0;
                freeExact += freeResult.Text == expected ? 1 : 0;
            }

            Console.WriteLine();
            Console.WriteLine($"Grammar transcripts exact: {exact}/{total}; free dictation exact: {freeExact}/{total}");
            Console.WriteLine($"Grammar decoding: {decodeSeconds:0.00} s for {audioSeconds:0.0} s of audio (real-time factor {decodeSeconds / audioSeconds:0.000})");
            Console.WriteLine("Each utterance alone with the cube selected, by MinConfidence (lowest word confidence):");
            foreach (float t in new[] { 0f, 0.3f, 0.4f, 0.5f, 0.6f, 0.7f, 0.8f })
            {
                int right = 0, wrong = 0, none = 0;
                foreach ((string expected, RecognitionResult result) in samples)
                {
                    VoiceTurn turn = Outcome(result, t);
                    if (turn.Command == null)
                        none++;
                    else if (expected != "-" && turn.ToString() == Outcome(new RecognitionResult(expected, 1f), 0f).ToString())
                        right++;
                    else
                        wrong++;
                }
                Console.WriteLine($"  {t:0.0}: intended command {right}, WRONG command {wrong}, no command {none} (of {samples.Count})");
            }

            RunExampleDialogue(heard);
            return 0;
        }

        static VoiceTurn Outcome(RecognitionResult result, float minConfidence)
        {
            var session = new VoiceSession(new VoiceSessionOptions { MinConfidence = minConfidence }, () => DateTime.UtcNow);
            session.SetObjects(Objects);
            session.SetSelection(new[] { "id-cube" });
            return session.Hear(result);
        }

        /// <summary>The plan's example: "rotate this object ninety degrees", select, "z".</summary>
        static void RunExampleDialogue(Dictionary<string, RecognitionResult> heard)
        {
            const string rotate = "-rotate-this-object-ninety-degrees";
            foreach (string first in heard.Keys.Where(k => k.EndsWith(rotate)))
            {
                string voice = first.Substring(0, first.Length - rotate.Length);
                if (!heard.TryGetValue(voice + "-z", out RecognitionResult axis))
                    continue;
                var session = new VoiceSession();
                session.SetObjects(Objects);
                Console.WriteLine();
                Console.WriteLine($"Example dialogue from audio ({voice}):");
                Console.WriteLine($"  user: '{heard[first].Text}' -> {session.Hear(heard[first])}");
                Console.WriteLine($"  user selects Sphere -> {session.SetSelection(new[] { "id-sphere" })}");
                Console.WriteLine($"  user: '{axis.Text}' -> {session.Hear(axis)}");
            }
        }

        static RecognitionResult Recognize(ISpeechRecognizer recognizer, short[] samples, int rate)
        {
            var results = new List<RecognitionResult>();
            void OnResult(RecognitionResult r) => results.Add(r);
            recognizer.Recognized += OnResult;
            recognizer.Start(rate);
            const int chunk = 1600; // 100 ms at 16 kHz, like a microphone callback
            var buffer = new short[chunk];
            for (int at = 0; at < samples.Length; at += chunk)
            {
                int n = Math.Min(chunk, samples.Length - at);
                Array.Copy(samples, at, buffer, 0, n);
                recognizer.AcceptAudio(buffer, n);
            }
            recognizer.Stop();
            recognizer.Recognized -= OnResult;
            if (results.Count == 0)
                return new RecognitionResult("", 0f);
            return new RecognitionResult(string.Join(" ", results.Select(r => r.Text)), results.Min(r => r.Confidence));
        }

        static (short[] samples, int rate) ReadWav(string path)
        {
            using var reader = new BinaryReader(File.OpenRead(path));
            if (new string(reader.ReadChars(4)) != "RIFF")
                throw new InvalidDataException(path + " is not a WAV file");
            reader.ReadInt32();
            reader.ReadChars(4); // WAVE
            int rate = 0;
            while (true)
            {
                string id = new string(reader.ReadChars(4));
                int size = reader.ReadInt32();
                if (id == "fmt ")
                {
                    short format = reader.ReadInt16(), channels = reader.ReadInt16();
                    rate = reader.ReadInt32();
                    reader.ReadInt32();
                    reader.ReadInt16();
                    short bits = reader.ReadInt16();
                    if (format != 1 || channels != 1 || bits != 16)
                        throw new InvalidDataException(path + " must be 16-bit mono PCM");
                    reader.ReadBytes(size - 16);
                }
                else if (id == "data")
                {
                    var samples = new short[size / 2];
                    for (int i = 0; i < samples.Length; i++)
                        samples[i] = reader.ReadInt16();
                    return (samples, rate);
                }
                else
                    reader.ReadBytes(size + (size & 1));
            }
        }
    }
}
