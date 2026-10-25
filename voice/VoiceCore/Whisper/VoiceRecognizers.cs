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
        /// <summary>Whisper for every utterance (the default: the setup Waaberi approved, small.en on the GPU with the
        /// Blender prompt, its own words sent to the host). FastPath and Vosk stay available.</summary>
        public RecognizerKind Kind = RecognizerKind.Whisper;

        /// <summary>Snap Whisper's transcript onto the grammar's phrases. Off by default: the host resolver reads
        /// Whisper's own words, as in the approved test.</summary>
        public bool SnapWhisperToGrammar;

        /// <summary>The Vosk model directory, for example StreamingAssets/vosk-model-small-en-us-0.15.</summary>
        public string VoskModelPath;

        /// <summary>The folder with whisper-server(.exe), its DLLs and the models, for example StreamingAssets/whisper.</summary>
        public string WhisperFolder;

        /// <summary>
        /// The model file in <see cref="WhisperFolder"/> (or a full path). Null (the default) picks by where it decodes
        /// (<see cref="UsesGpu"/>): small.en on the GPU (<see cref="WhisperServer.SmallModel"/>), tiny.en on the CPU
        /// (<see cref="WhisperServer.TinyModel"/>). Set it to override, for example tiny.en on the GPU. If the file is
        /// missing, another model that <c>voice/fetch-whisper.sh</c> downloads is used: small.en falls back to tiny.en,
        /// then base.en; tiny.en to base.en; anything else to tiny.en.
        /// </summary>
        public string WhisperModel;

        /// <summary>A whisper-server executable elsewhere, for example a Linux build; null for the one in the folder.</summary>
        public string WhisperExecutable;

        public int WhisperPort = WhisperServer.DefaultPort;

        /// <summary>CPU threads per decode (measured: 4).</summary>
        public int WhisperThreads = 4;

        /// <summary>
        /// Decode on the GPU: null (the default) does when <see cref="WhisperFolder"/> holds the CUDA build
        /// (<c>voice/fetch-whisper.sh --cuda</c>, see <see cref="WhisperServer.HasGpuBuild"/>); true or false forces it.
        /// The CPU build always decodes on the CPU. It also picks the default <see cref="WhisperModel"/>: false gives
        /// tiny.en, the way back to the CPU if the GPU build drops frames.
        /// </summary>
        public bool? WhisperUseGpu;

        /// <summary>Longest wait for a transcript; after it the utterance falls back to Vosk's result.</summary>
        public int WhisperTimeoutMs = 4000;

        /// <summary>Longest wait for whisper-server to load and warm up; voice input isn't ready until then.</summary>
        public int WhisperStartTimeoutMs = WhisperServer.DefaultStartTimeoutMs;

        /// <summary>Whisper's initial prompt; null for <see cref="WhisperServerRecognizer.BlenderPrompt"/>.</summary>
        public string WhisperPrompt;

        /// <summary>Append the grammar's words (object names, choice words) to the prompt. Measured with whisper tiny.en
        /// alone on the TTS corpus: 235 instead of 226 of 270 right through the resolver.</summary>
        public bool PromptWithGrammar;

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

        /// <summary>
        /// Whisper decodes on the GPU: <see cref="WhisperUseGpu"/>, or when that is null, whether the executable's folder
        /// holds the CUDA build (<see cref="WhisperServer.HasGpuBuild"/>). Decides <c>-ng</c> and the default model.
        /// </summary>
        public bool UsesGpu() => WhisperUseGpu ?? WhisperServer.HasGpuBuild(ExecutablePath());

        /// <summary>The model file whisper-server gets: <see cref="WhisperModel"/>, or the default for
        /// <see cref="UsesGpu"/>, or the first fallback that exists.</summary>
        public string ModelPath()
        {
            string folder = WhisperFolder ?? "";
            string chosen = Path.Combine(folder, WhisperModel ?? (UsesGpu() ? WhisperServer.SmallModel : WhisperServer.TinyModel));
            if (File.Exists(chosen))
                return chosen;
            string name = Path.GetFileName(chosen);
            string[] fallbacks =
                name == WhisperServer.SmallModel ? new[] { WhisperServer.TinyModel, WhisperServer.BaseModel } :
                name == WhisperServer.TinyModel ? new[] { WhisperServer.BaseModel } :
                new[] { WhisperServer.TinyModel };
            foreach (string fallback in fallbacks)
                if (File.Exists(Path.Combine(folder, fallback)))
                    return Path.Combine(folder, fallback);
            return chosen;
        }

        internal string ExecutablePath() => WhisperExecutable ?? Path.Combine(WhisperFolder ?? "", WhisperServer.ExecutableName);
    }

    /// <summary>
    /// Builds the app's recognizer, so the Unity adapter changes one line:
    /// <c>new VoiceInput(() =&gt; VoiceRecognizers.Create(settings))</c>. Runs on VoiceInput's worker thread: loading
    /// Vosk and starting whisper-server happen side by side there, never on a frame.
    /// <para><b>GPU or CPU.</b> Which whisper-server runs is decided by what <c>voice/fetch-whisper.sh</c> put in
    /// StreamingAssets/whisper, not here. On a Windows PC with an NVIDIA GPU (the demo PC), prefer the CUDA 12.4 build
    /// (<c>voice/fetch-whisper.sh --cuda app/Assets/StreamingAssets</c>: a 685 MB zip and the 488 MB small.en model,
    /// needs an NVIDIA driver for CUDA 12.4 or later). With it <see cref="VoiceRecognizerSettings.UsesGpu"/> is true,
    /// so whisper-server decodes on the GPU with small.en (a GPU build took about 0.2 s per utterance for small.en and
    /// 18-22 ms for tiny.en on an idle RTX 5070 Ti; small.en takes 2.6-4 s on 4 CPU threads). The Windows CUDA build and
    /// a GPU busy rendering VR are unmeasured: set WhisperUseGpu = false if frames drop or it fails to start (then
    /// tiny.en on the CPU), or WhisperModel = tiny.en to stay on the GPU with a lighter model. Everywhere else use the
    /// CPU build (the default download), which gets tiny.en (<see cref="VoiceRecognizerSettings.WhisperModel"/>). If
    /// whisper-server can't start at all (no driver, no VC++ runtime), FastPath falls back to Vosk alone and logs why.</para>
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
                    catch (Exception why)
                    {
                        server.Dispose();
                        log("Voice: Whisper is unavailable (" + why.GetType().Name + ": " + why.Message + "); using Vosk");
                        return VoskSpeechRecognizer.Load(settings.VoskModelPath);
                    }
                    log("Voice: Whisper only (" + Describe(settings) + ")");
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
            log("Voice: Vosk with Whisper (" + Describe(settings) + ") when Vosk isn't sure");
            return new FastPathRecognizer(vosk, Recognizer(settings, server), settings.MinFastConfidence);
        }

        /// <summary>"ggml-small.en.bin on the GPU", for the log.</summary>
        static string Describe(VoiceRecognizerSettings settings) =>
            Path.GetFileName(settings.ModelPath()) + (settings.UsesGpu() ? " on the GPU" : " on the CPU");

        static WhisperServer Server(VoiceRecognizerSettings settings, Action<string> log) =>
            new WhisperServer(settings.ExecutablePath(), settings.ModelPath(), settings.WhisperPort, settings.WhisperThreads,
                settings.WhisperStartTimeoutMs, log, settings.UsesGpu());

        static WhisperServerRecognizer Recognizer(VoiceRecognizerSettings settings, WhisperServer server) =>
            new WhisperServerRecognizer(settings.WhisperPort, settings.WhisperPrompt, settings.PromptWithGrammar,
                settings.WhisperTimeoutMs, settings.SnapThreshold, settings.WhisperGuessConfidence)
            { Server = server, SnapToGrammar = settings.SnapWhisperToGrammar };

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
