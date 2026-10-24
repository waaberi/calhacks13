using System;
using System.Collections.Generic;
using SpatialModeling.VoiceCore;
using Vosk;

namespace SpatialModeling.VoskSpike
{
    /// <summary>
    /// <see cref="ISpeechRecognizer"/> on Vosk 0.3.38. Plain C# that also compiles in Unity once Vosk.dll and
    /// the native libraries are in the project. Call Start, AcceptAudio and Stop from one thread
    /// (a worker thread in Unity); <see cref="Recognized"/> is raised on that thread.
    /// </summary>
    public sealed class VoskSpeechRecognizer : ISpeechRecognizer
    {
        readonly Model model;
        string grammar;
        VoskRecognizer recognizer;
        int recognizerRate;

        public VoskSpeechRecognizer(Model model) => this.model = model ?? throw new ArgumentNullException(nameof(model));

        public event Action<RecognitionResult> Recognized;

        public void SetGrammar(IReadOnlyList<string> phrases)
        {
            // Vosk 0.3.38 takes the grammar only in the constructor, so the next Start creates a new recognizer.
            grammar = phrases == null ? null : VoskJson.Grammar(phrases);
            DisposeRecognizer();
        }

        public void Start(int sampleRate)
        {
            if (recognizer != null && recognizerRate == sampleRate)
            {
                recognizer.Reset();
                return;
            }
            DisposeRecognizer();
            recognizer = grammar == null ? new VoskRecognizer(model, sampleRate) : new VoskRecognizer(model, sampleRate, grammar);
            recognizer.SetWords(true); // word confidences, see VoskJson.ParseResult
            recognizerRate = sampleRate;
        }

        public void AcceptAudio(short[] samples, int count)
        {
            if (recognizer != null && recognizer.AcceptWaveform(samples, count))
                Raise(recognizer.Result()); // Vosk detected the end of an utterance
        }

        public void Stop()
        {
            if (recognizer != null)
                Raise(recognizer.FinalResult());
        }

        public void Dispose() => DisposeRecognizer();

        void Raise(string json)
        {
            RecognitionResult result = VoskJson.ParseResult(json);
            if (result.Text.Length > 0)
                Recognized?.Invoke(result);
        }

        void DisposeRecognizer()
        {
            recognizer?.Dispose();
            recognizer = null;
        }
    }
}
