using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using SpatialModeling.VoiceCore;
using SpatialModeling.VoiceCore.Vosk;

namespace SpatialModeling.VoskSpike
{
    /// <summary>
    /// Recognizes audio files the way the Unity app will: float samples at the file's rate (48 kHz from make-samples.sh,
    /// like a Windows microphone) through VoiceInput, PcmConverter and the package's Vosk recognizer, with and without
    /// the VoiceCore grammar, then runs the results through a VoiceSession.
    ///
    ///   dotnet run --project voice/VoskSpike -- MODEL_DIR SAMPLES_DIR
    ///   dotnet run --project voice/VoskSpike -- MODEL_DIR --transcribe FILE...   # free dictation, e.g. prompt clips
    ///
    /// Each sample is NAME.wav (16-bit PCM) or NAME.ogg, with NAME.txt holding the expected words, or "-" for speech
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
            if (args.Length < 2)
            {
                Console.Error.WriteLine("usage: VoskSpike MODEL_DIR SAMPLES_DIR | MODEL_DIR --transcribe FILE...");
                return 2;
            }
            var clock = Stopwatch.StartNew();
            var free = Listen(args[0], null);
            Console.WriteLine($"Model loaded in {clock.ElapsedMilliseconds} ms");
            if (args[1] == "--transcribe")
            {
                foreach (string file in args.Skip(2))
                    Console.WriteLine($"{Path.GetFileName(file),-28} '{Recognize(free, file).Text}'");
                free.Dispose();
                return 0;
            }

            var session = new VoiceSession();
            session.SetObjects(Objects);
            IReadOnlyList<string> grammar = session.GrammarPhrases();
            using (VoskSpeechRecognizer vosk = VoskSpeechRecognizer.Load(args[0]))
            {
                string[] missing = grammar.Where(w => w != "[unk]" && !vosk.HasWord(w)).ToArray();
                Console.WriteLine($"Grammar: {grammar.Count} words; missing from the model: {(missing.Length == 0 ? "none" : string.Join(", ", missing))}");
            }
            var restricted = Listen(args[0], grammar);

            int total = 0, exact = 0, freeExact = 0;
            double audioSeconds = 0, decodeSeconds = 0;
            var heard = new Dictionary<string, RecognitionResult>();
            var samples = new List<(string expected, RecognitionResult result)>();
            float threshold = new VoiceSessionOptions().MinConfidence;
            var files = Directory.GetFiles(args[1]).Where(p => p.EndsWith(".wav") || p.EndsWith(".ogg"));
            foreach (string file in files.OrderBy(p => p, StringComparer.Ordinal))
            {
                string expected = File.ReadAllText(Path.ChangeExtension(file, ".txt")).Trim();
                (float[] audio, int rate) = Read(file);
                audioSeconds += audio.Length / (double)rate;
                clock.Restart();
                RecognitionResult result = Recognize(restricted, audio, rate);
                decodeSeconds += clock.Elapsed.TotalSeconds;
                RecognitionResult freeResult = Recognize(free, audio, rate);
                heard[Path.GetFileNameWithoutExtension(file)] = result;
                samples.Add((expected, result));

                VoiceTurn turn = Outcome(result, threshold);
                string verdict = expected == "-" ? (turn.Command == null ? "ok  " : "FAIL") : result.Text == expected ? "ok  " : "MISS";
                Console.WriteLine($"{verdict} {Path.GetFileName(file),-52} {rate / 1000.0:0.#} kHz heard '{result.Text}' ({result.Confidence:0.00})" +
                    (expected == "-" ? "" : $" free '{freeResult.Text}'") + $" -> {turn}");
                if (expected == "-")
                    continue;
                total++;
                exact += result.Text == expected ? 1 : 0;
                freeExact += freeResult.Text == expected ? 1 : 0;
            }

            Console.WriteLine();
            Console.WriteLine($"Grammar transcripts exact: {exact}/{total}; free dictation exact: {freeExact}/{total}");
            Console.WriteLine($"Grammar decoding incl. resampling: {decodeSeconds:0.00} s for {audioSeconds:0.0} s of audio (real-time factor {decodeSeconds / audioSeconds:0.000})");
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
            restricted.Dispose();
            free.Dispose();
            return 0;
        }

        static VoiceInput Listen(string model, IReadOnlyList<string> grammar)
        {
            var input = new VoiceInput(() => VoskSpeechRecognizer.Load(model));
            if (grammar != null)
                input.SetGrammar(grammar);
            input.WaitIdle(TimeSpan.FromMinutes(1));
            if (!input.Ready)
                throw new InvalidOperationException(input.Error);
            return input;
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
                VoiceTurn done = session.Hear(axis);
                HostCommand command = done.Command == null ? null : HostCommand.From(done.Command);
                Console.WriteLine($"  user: '{axis.Text}' -> {done}" + (command == null ? "" : $" -> {command.Op} {command.TargetId}"));
            }
        }

        static RecognitionResult Recognize(VoiceInput input, string file)
        {
            (float[] audio, int rate) = Read(file);
            return Recognize(input, audio, rate);
        }

        /// <summary>Push-to-talk around the audio, in 20 ms microphone frames.</summary>
        static RecognitionResult Recognize(VoiceInput input, float[] samples, int rate)
        {
            input.StartUtterance();
            int frame = rate / 50;
            var buffer = new float[frame];
            for (int at = 0; at < samples.Length; at += frame)
            {
                int n = Math.Min(frame, samples.Length - at);
                Array.Copy(samples, at, buffer, 0, n);
                input.Write(buffer, n, rate);
            }
            input.StopUtterance();
            input.WaitIdle(TimeSpan.FromMinutes(1));
            var results = new List<RecognitionResult>();
            while (input.TryGetResult(out RecognitionResult r))
                results.Add(r);
            if (results.Count == 0)
                return new RecognitionResult("", 0f);
            return new RecognitionResult(string.Join(" ", results.Select(r => r.Text)), results.Min(r => r.Confidence));
        }

        /// <summary>Mono float samples and their rate, like Unity's AudioClip.GetData.</summary>
        static (float[] samples, int rate) Read(string path)
        {
            if (path.EndsWith(".ogg"))
            {
                using (var vorbis = new NVorbis.VorbisReader(path))
                {
                    var samples = new float[vorbis.TotalSamples * vorbis.Channels];
                    int read = vorbis.ReadSamples(samples, 0, samples.Length);
                    return (samples.Take(read).Where((_, i) => i % vorbis.Channels == 0).ToArray(), vorbis.SampleRate);
                }
            }
            using (var reader = new BinaryReader(File.OpenRead(path)))
            {
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
                        var samples = new float[size / 2];
                        for (int i = 0; i < samples.Length; i++)
                            samples[i] = reader.ReadInt16() / 32768f;
                        return (samples, rate);
                    }
                    else
                        reader.ReadBytes(size + (size & 1));
                }
            }
        }
    }
}
