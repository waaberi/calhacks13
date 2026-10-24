using System;
using System.IO;
using System.Threading.Tasks;
using SpatialModeling.VoiceCore.Vosk;

namespace SpatialModeling.VoiceCore.Whisper
{
    /// <summary>Which recognizer <see cref="VoiceRecognizers.Create"/> builds.</summary>
    public enum RecognizerKind
    {
        /// <summary>Vosk's small model in grammar mode alone: VoiceCore's behaviour before Whisper.</summary>
        Vosk,

        /// <summary>Whisper alone (every utterance waits for whisper-server). For measurements.</summary>
        Whisper,

        /// <summary>Vosk first, Whisper when Vosk isn't sure (<see cref="FastPathRecognizer"/>). Falls back to Vosk
        /// alone if whisper-server can't start.</summary>
        FastPath,
    }

    /// <summary>Settings for <see cref="VoiceRecognizers.Create"/>. <see cref="ForStreamingAssets"/> fills the paths.</summary>
    public sealed class VoiceRecognizerSettings
    {
        public RecognizerKind Kind = RecognizerKind.FastPath;

        /// <summary>The Vosk model directory, for example StreamingAssets/vosk-model-small-en-us-0.15.</summary>
        public string VoskModelPath;

        /// <summary>The folder with whisper-server(.exe), its DLLs and the models, for example StreamingAssets/whisper.</summary>
        public string WhisperFolder;

        /// <summary>
        /// The model file in <see cref="WhisperFolder"/> (or a full path). If it is missing, the other model that
        /// <c>voice/fetch-whisper.sh</c> downloads is used. tiny.en: see <see cref="WhisperServer.TinyModel"/>.
        /// </summary>
        public string WhisperModel = WhisperServer.TinyModel;

        /// <summary>A whisper-server executable elsewhere, for example a Linux build; null for the one in the folder.</summary>
        public string WhisperExecutable;

        public int WhisperPort = WhisperServer.DefaultPort;

        /// <summary>CPU threads per decode (measured: 4).</summary>
        public int WhisperThreads = 4;

        /// <summary>Longest wait for a transcript; after it the utterance falls back to Vosk's result.</summary>
        public int WhisperTimeoutMs = 4000;

        /// <summary>Longest wait for whisper-server to load and warm up.</summary>
        public int WhisperStartTimeoutMs = 30000;

        /// <summary>Whisper's initial prompt; null for <see cref="WhisperServerRecognizer.BlenderPrompt"/>.</summary>
        public string WhisperPrompt;

        /// <summary>Append the grammar's words (object names, choice words) to the prompt. Measured with whisper tiny.en
        /// alone on the TTS corpus: 235 instead of 226 of 270 right through the resolver.</summary>
        public bool PromptWithGrammar = true;

        /// <summary>See <see cref="PhraseSnapper.DefaultThreshold"/>.</summary>
        public float SnapThreshold = PhraseSnapper.DefaultThreshold;

        /// <summary>See <see cref="WhisperServerRecognizer.DefaultGuessConfidence"/>; 1 to let guesses run.</summary>
        public float WhisperGuessConfidence = WhisperServerRecognizer.DefaultGuessConfidence;

        /// <summary>See <see cref="FastPathRecognizer.DefaultMinFastConfidence"/>.</summary>
        public float MinFastConfidence = FastPathRecognizer.DefaultMinFastConfidence;

        /// <summary>Which recognizer runs and why Whisper isn't used, for example Unity's Debug.Log. Any thread.</summary>
        public Action<string> Log;

        /// <summary>The app's layout: the Vosk model and the whisper folder in StreamingAssets.</summary>
        public static VoiceRecognizerSettings ForStreamingAssets(string streamingAssetsPath, Action<string> log = null) =>
            new VoiceRecognizerSettings
            {
                VoskModelPath = Path.Combine(streamingAssetsPath, VoskSpeechRecognizer.ModelName),
                WhisperFolder = Path.Combine(streamingAssetsPath, WhisperServer.FolderName),
                Log = log,
            };

        internal string ModelPath()
        {
            string chosen = Path.Combine(WhisperFolder ?? "", WhisperModel ?? WhisperServer.TinyModel);
            if (File.Exists(chosen))
                return chosen;
            string other = Path.Combine(WhisperFolder ?? "",
                Path.GetFileName(chosen) == WhisperServer.TinyModel ? WhisperServer.BaseModel : WhisperServer.TinyModel);
            return File.Exists(other) ? other : chosen;
        }

        internal string ExecutablePath() => WhisperExecutable ?? Path.Combine(WhisperFolder ?? "", WhisperServer.ExecutableName);
    }

    /// <summary>
    /// Builds the app's recognizer, so the Unity adapter changes one line:
    /// <c>new VoiceInput(() =&gt; VoiceRecognizers.Create(settings))</c>. Runs on VoiceInput's worker thread: loading
    /// Vosk and starting whisper-server happen side by side there, never on a frame.
    /// </summary>
    public static class VoiceRecognizers
    {
        public static ISpeechRecognizer Create(VoiceRecognizerSettings settings)
        {
            if (settings == null)
                throw new ArgumentNullException(nameof(settings));
            Action<string> log = settings.Log ?? (_ => { });
            switch (settings.Kind)
            {
                case RecognizerKind.Vosk:
                    log("Voice: Vosk only");
                    return VoskSpeechRecognizer.Load(settings.VoskModelPath);
                case RecognizerKind.Whisper:
                {
                    WhisperServer server = Server(settings, log);
                    try
                    {
                        server.EnsureRunning();
                    }
                    catch
                    {
                        server.Dispose();
                        throw;
                    }
                    log("Voice: Whisper only (" + Path.GetFileName(settings.ModelPath()) + ")");
                    return Recognizer(settings, server);
                }
                default:
                    return CreateFastPath(settings, log);
            }
        }

        static ISpeechRecognizer CreateFastPath(VoiceRecognizerSettings settings, Action<string> log)
        {
            WhisperServer server = Server(settings, log);
            Task starting = Task.Run(server.EnsureRunning); // the model loads while Vosk loads
            VoskSpeechRecognizer vosk;
            try
            {
                vosk = VoskSpeechRecognizer.Load(settings.VoskModelPath);
            }
            catch
            {
                Stop(server, starting);
                throw;
            }

            try
            {
                starting.Wait();
            }
            catch (AggregateException e)
            {
                Exception why = e.InnerException ?? e;
                log("Voice: Vosk only; Whisper is unavailable (" + why.GetType().Name + ": " + why.Message + ")");
                server.Dispose();
                return vosk;
            }
            log("Voice: Vosk with Whisper (" + Path.GetFileName(settings.ModelPath()) + ") when Vosk isn't sure");
            return new FastPathRecognizer(vosk, Recognizer(settings, server), settings.MinFastConfidence);
        }

        static WhisperServer Server(VoiceRecognizerSettings settings, Action<string> log) =>
            new WhisperServer(settings.ExecutablePath(), settings.ModelPath(), settings.WhisperPort, settings.WhisperThreads,
                settings.WhisperStartTimeoutMs, log);

        static WhisperServerRecognizer Recognizer(VoiceRecognizerSettings settings, WhisperServer server) =>
            new WhisperServerRecognizer(settings.WhisperPort, settings.WhisperPrompt, settings.PromptWithGrammar,
                settings.WhisperTimeoutMs, settings.SnapThreshold, settings.WhisperGuessConfidence) { Server = server };

        static void Stop(WhisperServer server, Task starting)
        {
            try
            {
                starting.Wait();
            }
            catch (AggregateException)
            {
                // Reported by the caller's exception instead.
            }
            server.Dispose();
        }
    }
}
