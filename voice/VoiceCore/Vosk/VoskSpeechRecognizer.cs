using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace SpatialModeling.VoiceCore.Vosk
{
    /// <summary>
    /// <see cref="ISpeechRecognizer"/> on Vosk, through its C API in the native library libvosk 0.3.38 that
    /// <c>voice/fetch-vosk.sh</c> puts into the package's <c>Plugins/</c> folder. There is no managed Vosk.dll, so this
    /// assembly compiles without the download; without it, <see cref="Load"/> throws <see cref="DllNotFoundException"/>.
    /// Use it from one thread at a time: <see cref="VoiceInput"/> creates, uses and disposes it on its worker.
    /// </summary>
    public sealed class VoskSpeechRecognizer : ISpeechRecognizer
    {
        /// <summary>The model <c>voice/fetch-model.sh</c> downloads, for example into StreamingAssets.</summary>
        public const string ModelName = "vosk-model-small-en-us-0.15";

        IntPtr model;
        IntPtr recognizer;
        string grammar;
        bool grammarChanged;
        int recognizerRate;

        VoskSpeechRecognizer(IntPtr model) => this.model = model;

        /// <summary>Loads a model directory (about a second for the small English model). Keep the path ASCII: on
        /// Windows, Vosk opens the model files through the ANSI code page.</summary>
        public static VoskSpeechRecognizer Load(string modelPath)
        {
            if (!File.Exists(Path.Combine(modelPath, "am", "final.mdl")))
                throw new DirectoryNotFoundException("No Vosk model in " + modelPath + "; run voice/fetch-model.sh");
            Native.vosk_set_log_level(-1);
            IntPtr model = Native.vosk_model_new(modelPath);
            if (model == IntPtr.Zero)
                throw new IOException("Vosk couldn't load the model in " + modelPath);
            return new VoskSpeechRecognizer(model);
        }

        public event Action<RecognitionResult> Recognized;

        /// <summary>Whether the model knows a word; grammar words it doesn't know are never recognized.</summary>
        public bool HasWord(string word) => Native.vosk_model_find_word(Model, word) >= 0;

        public void SetGrammar(IReadOnlyList<string> phrases)
        {
            // Vosk takes the grammar when the recognizer is made, so the next Start makes a new one; an utterance
            // in progress keeps the old grammar.
            grammar = phrases == null ? null : VoskJson.Grammar(phrases);
            grammarChanged = true;
        }

        public void Start(int sampleRate)
        {
            if (recognizer != IntPtr.Zero && recognizerRate == sampleRate && !grammarChanged)
            {
                Native.vosk_recognizer_reset(recognizer);
                return;
            }
            FreeRecognizer();
            recognizer = grammar == null
                ? Native.vosk_recognizer_new(Model, sampleRate)
                : Native.vosk_recognizer_new_grm(Model, sampleRate, grammar);
            if (recognizer == IntPtr.Zero)
                throw new InvalidOperationException("Vosk couldn't make a recognizer");
            Native.vosk_recognizer_set_words(recognizer, 1); // word confidences, see VoskJson.ParseResult
            recognizerRate = sampleRate;
            grammarChanged = false;
        }

        public void AcceptAudio(short[] samples, int count)
        {
            if (recognizer == IntPtr.Zero || count <= 0)
                return;
            if (count > samples.Length)
                throw new ArgumentOutOfRangeException(nameof(count));
            if (Native.vosk_recognizer_accept_waveform_s(recognizer, samples, count) != 0)
                Raise(Native.vosk_recognizer_result(recognizer)); // Vosk found the end of an utterance
        }

        public void Stop()
        {
            if (recognizer != IntPtr.Zero)
                Raise(Native.vosk_recognizer_final_result(recognizer));
        }

        public void Dispose()
        {
            FreeRecognizer();
            if (model != IntPtr.Zero)
            {
                Native.vosk_model_free(model);
                model = IntPtr.Zero;
            }
        }

        IntPtr Model => model != IntPtr.Zero ? model : throw new ObjectDisposedException(nameof(VoskSpeechRecognizer));

        void Raise(IntPtr json)
        {
            RecognitionResult result = VoskJson.ParseResult(Utf8(json));
            if (result.Text.Length > 0)
                Recognized?.Invoke(result);
        }

        void FreeRecognizer()
        {
            if (recognizer != IntPtr.Zero)
                Native.vosk_recognizer_free(recognizer);
            recognizer = IntPtr.Zero;
        }

        /// <summary>A NUL-terminated UTF-8 string owned by Vosk.</summary>
        static string Utf8(IntPtr text)
        {
            if (text == IntPtr.Zero)
                return "";
            int length = 0;
            while (Marshal.ReadByte(text, length) != 0)
                length++;
            var bytes = new byte[length];
            Marshal.Copy(text, bytes, 0, length);
            return Encoding.UTF8.GetString(bytes);
        }

        /// <summary>vosk_api.h. "libvosk" is libvosk.dll, libvosk.dylib or libvosk.so.</summary>
        static class Native
        {
            const string Lib = "libvosk";

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern void vosk_set_log_level(int level);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr vosk_model_new(string path);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern void vosk_model_free(IntPtr model);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern int vosk_model_find_word(IntPtr model, string word);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr vosk_recognizer_new(IntPtr model, float sampleRate);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr vosk_recognizer_new_grm(IntPtr model, float sampleRate, string grammar);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern void vosk_recognizer_set_words(IntPtr recognizer, int words);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern int vosk_recognizer_accept_waveform_s(IntPtr recognizer, short[] data, int length);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr vosk_recognizer_result(IntPtr recognizer);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern IntPtr vosk_recognizer_final_result(IntPtr recognizer);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern void vosk_recognizer_reset(IntPtr recognizer);

            [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
            public static extern void vosk_recognizer_free(IntPtr recognizer);
        }
    }
}
