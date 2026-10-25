using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Text;

namespace SpatialModeling.VoiceCore.Whisper
{
    /// <summary>
    /// A recognizer that can tell "I heard nothing usable" (chatter, silence) from "I couldn't listen" (server down,
    /// timeout), so <see cref="FastPathRecognizer"/> falls back to Vosk only in the second case.
    /// </summary>
    public interface IFallibleRecognizer : ISpeechRecognizer
    {
        /// <summary>The last <see cref="ISpeechRecognizer.Stop"/> failed; <see cref="LastError"/> says why.</summary>
        bool LastStopFailed { get; }

        string LastError { get; }
    }

    /// <summary>
    /// <see cref="ISpeechRecognizer"/> on a local whisper.cpp <c>whisper-server</c> (see <see cref="WhisperServer"/>):
    /// buffers the push-to-talk audio, POSTs it as a WAV to <c>/inference</c> on <see cref="Stop"/> (VoiceInput's
    /// worker thread waits for the answer), snaps the transcript to the grammar with <see cref="PhraseSnapper"/> and
    /// raises the snapped phrases with their similarity as confidence (capped below 0.5 when the snap had to replace
    /// words, see <see cref="DefaultGuessConfidence"/>). Three answers, so the app can tell them apart:
    /// <list type="bullet">
    /// <item>a phrase (<see cref="Recognized"/>): the snap was accepted;</item>
    /// <item><see cref="NoResult"/> with <see cref="NoResultReason.NotUnderstood"/>: speech was heard but none of it
    /// is in the grammar (chatter, or a command Whisper misheard beyond the snap), so the session says "didn't catch
    /// that" (<see cref="VoiceInput.TryGetNoResult"/>, then <see cref="VoiceSession.NothingRecognized"/>);</item>
    /// <item><see cref="NoResult"/> with <see cref="NoResultReason.Silence"/>: no speech. The utterance was silent
    /// (<see cref="MinSpeechRms"/>, checked before Whisper is asked) or Whisper wrote one of its silence
    /// hallucinations ("you", "thank you", "[BLANK_AUDIO]", see <see cref="IsSilenceHallucination"/>), so an
    /// accidental press says nothing.</item>
    /// </list>
    /// Whisper is trained on real speech, so it hears
    /// real voices far better than Vosk's small model; the snap keeps its output inside what VoiceCore understands.
    /// It talks HTTP over a plain socket because Unity refuses <c>http://</c> in UnityWebRequest
    /// (<c>insecureHttpOption</c> 0), and it has no native code in Unity: if the server is down or slow the
    /// utterance fails (<see cref="LastStopFailed"/>) and nothing is raised, not even <see cref="NoResult"/> (it may
    /// have been noise, so VoiceInput counts it as silence).
    /// </summary>
    public sealed class WhisperServerRecognizer : IFallibleRecognizer, IReportsNoResult
    {
        /// <summary>
        /// The vocabulary prompt from the voice-asr-alternatives study: with it whisper tiny.en got 165 instead of 108
        /// of 250 TTS commands right before snapping, because Whisper otherwise writes "devil" for bevel and
        /// "a torus" as "at Taurus".
        /// </summary>
        public const string BlenderPrompt =
            "Blender modeling commands: mesh, modifier, mirror, solidify, bevel, array, boolean, decimate, remesh, " +
            "subdivision surface, triangulate, wireframe, weld, screw, torus, monkey, cube, cylinder, cone, sphere, plane, " +
            "camera, light, extrude, inset faces, normals, vertices, merge by distance, origin to geometry, shade smooth, " +
            "undo, redo.";

        /// <summary>Whisper keeps at most 224 prompt tokens; this many characters of grammar words stay well under.</summary>
        public const int MaxPromptChars = 600;

        /// <summary>
        /// The most confidence a snap that replaced words gets: just under VoiceSession's MinConfidence 0.5, so the host
        /// may only ask about it ("one, two or three?"), never run it. Measured through the resolver on the 290-clip
        /// TTS corpus and the 5 x 116 degraded clips of the realvoice kit: wrong runs fell from 3 to 1 and from
        /// 4-6 to 1-4 per 108 commands, with as many commands run or asked right.
        /// </summary>
        public const float DefaultGuessConfidence = 0.49f;

        /// <summary>
        /// The speech gate: an utterance is speech only if at least <see cref="MinSpeechFrames"/> of its 30 ms frames
        /// reach this RMS (16-bit samples; 100 is -50 dBFS). Measured: the quietest of 1,100 real Speech Commands
        /// clips had its third-loudest frame at 293, the 320 SLURP clips at 778, the 290 TTS clips at 3,458; the
        /// silent press of the Unity run was 0. Below it Whisper isn't asked at all (it writes "you" for silence).
        /// </summary>
        public const float DefaultMinSpeechRms = 100f;

        /// <summary>Frames that must reach <see cref="MinSpeechRms"/>: 90 ms of sound, more than a click.</summary>
        public const int MinSpeechFrames = 3;

        /// <summary>
        /// What Whisper writes for silence or noise (normalized), from the Unity run (a silent press gave "you" at
        /// 1.0) and whisper.cpp's known hallucinations. Single filler sounds count too.
        /// </summary>
        static readonly HashSet<string> SilenceHallucinations = new HashSet<string>(StringComparer.Ordinal)
        {
            "you", "thank you", "thank you very much", "thanks", "thanks for watching", "thank you for watching",
            "thanks for listening", "thank you for listening", "bye", "bye bye", "goodbye", "blank audio",
            "silence", "music", "applause", "laughter", "um", "uh", "uhm", "umm", "hmm", "hm", "mm", "mhm", "ah", "oh",
            "eh", "er", "huh",
        };

        readonly string host;
        readonly int port;
        readonly string basePrompt;
        readonly bool promptWithGrammar;
        readonly int timeoutMs;
        readonly float threshold;
        readonly float guessConfidence;
        readonly List<short> pcm = new List<short>();
        int rate = 16000;
        PhraseSnapper snapper;
        string prompt;
        string restartFailed;

        /// <param name="port">The port <see cref="WhisperServer"/> listens on.</param>
        /// <param name="prompt">Initial prompt: words Whisper should expect. Null for <see cref="BlenderPrompt"/>.</param>
        /// <param name="promptWithGrammar">Append the grammar's words to the prompt (object names, choice words).</param>
        /// <param name="timeoutMs">Longest wait for a transcript before the utterance counts as failed.</param>
        /// <param name="threshold">Snap similarity needed; see <see cref="PhraseSnapper.DefaultThreshold"/>.</param>
        /// <param name="guessConfidence">Cap on the confidence of a snap that replaced words; 1 for none.</param>
        public WhisperServerRecognizer(int port = WhisperServer.DefaultPort, string prompt = null, bool promptWithGrammar = true,
            int timeoutMs = 4000, float threshold = PhraseSnapper.DefaultThreshold, float guessConfidence = DefaultGuessConfidence,
            string host = "127.0.0.1", float minSpeechRms = DefaultMinSpeechRms)
        {
            this.guessConfidence = guessConfidence;
            MinSpeechRms = minSpeechRms;
            this.host = host;
            this.port = port;
            basePrompt = prompt ?? BlenderPrompt;
            this.promptWithGrammar = promptWithGrammar;
            this.timeoutMs = timeoutMs;
            this.threshold = threshold;
            this.prompt = basePrompt;
        }

        public event Action<RecognitionResult> Recognized;

        /// <summary>
        /// Raised from <see cref="Stop"/> instead of <see cref="Recognized"/>: <see cref="NoResultReason.Silence"/> for no
        /// speech (<see cref="LastWasSilence"/>), <see cref="NoResultReason.NotUnderstood"/> for speech that snapped onto
        /// no phrase. Not raised for a failed decode (<see cref="LastStopFailed"/>).
        /// </summary>
        public event Action<NoResultReason> NoResult;

        /// <summary>What Whisper wrote for the last utterance, before snapping (for logs and measurements).</summary>
        public string LastTranscript { get; private set; } = "";

        /// <summary>The snap of the last utterance, accepted or not.</summary>
        public SnapResult LastSnap { get; private set; }

        /// <summary>Release to transcript, in milliseconds, for the last utterance (0 if none was sent).</summary>
        public double LastMilliseconds { get; private set; }

        public bool LastStopFailed { get; private set; }

        /// <summary>The last utterance was no speech: too quiet to send, or a silence hallucination that was dropped.</summary>
        public bool LastWasSilence { get; private set; }

        /// <summary>The last transcript was a silence hallucination ("you"), dropped or not.</summary>
        public bool LastWasHallucination { get; private set; }

        /// <summary>See <see cref="DefaultMinSpeechRms"/>; 0 sends every utterance to Whisper.</summary>
        public float MinSpeechRms { get; }

        /// <summary>
        /// Drop a transcript that is a silence hallucination (see <see cref="IsSilenceHallucination"/>). True by
        /// default; <see cref="FastPathRecognizer"/> turns it off and drops them itself unless Vosk heard speech too.
        /// </summary>
        public bool DropSilenceHallucinations { get; set; } = true;

        public string LastError { get; private set; }

        /// <summary>The prompt sent with each utterance.</summary>
        public string Prompt => prompt;

        /// <summary>
        /// The server this recognizer owns, if any: started again at the next utterance if it died or went away
        /// (once; if that fails, every later utterance fails at once and Vosk answers alone), and disposed (killed)
        /// with the recognizer.
        /// </summary>
        public WhisperServer Server { get; set; }

        /// <summary>Snap the transcript onto the grammar's phrases. False sends Whisper's own words (normalized) at
        /// confidence 1, for the host resolver to read.</summary>
        public bool SnapToGrammar { get; set; } = true;
        bool compositionGrammar;

        public void SetGrammar(IReadOnlyList<string> phrases)
        {
            compositionGrammar = phrases != null && new List<string>(phrases).Contains("then");
            snapper = phrases == null || !SnapToGrammar ? null : new PhraseSnapper(phrases, threshold);
            prompt = promptWithGrammar ? PromptFor(basePrompt, phrases) : basePrompt;
        }

        public void Start(int sampleRate)
        {
            rate = sampleRate;
            pcm.Clear();
        }

        public void AcceptAudio(short[] samples, int count)
        {
            for (int i = 0; i < count; i++)
                pcm.Add(samples[i]);
        }

        public void Stop()
        {
            LastTranscript = "";
            LastSnap = default;
            LastMilliseconds = 0;
            LastStopFailed = false;
            LastError = null;
            LastWasSilence = false;
            LastWasHallucination = false;
            if (pcm.Count < rate / 10)
            {
                pcm.Clear();
                Silent(); // under 0.1 s: a click, not speech (whisper.cpp ignores it too)
                return;
            }
            if (!HasSpeech(pcm, rate, MinSpeechRms))
            {
                pcm.Clear();
                Silent(); // Whisper would write "you": don't ask it
                return;
            }

            if (restartFailed != null)
            {
                // One restart was tried and failed: don't make every utterance wait for another (up to the start
                // timeout each); Vosk answers alone from now on.
                LastStopFailed = true;
                LastError = restartFailed;
                pcm.Clear();
                return;
            }

            var clock = Stopwatch.StartNew();
            string text;
            try
            {
                if (Server != null && Server.NeedsStart)
                    Restart(); // it crashed or went away: start it again (about a second, on the worker thread)
                text = Transcribe(Wav(pcm, rate));
            }
            catch (Exception e) when (e is IOException || e is SocketException || e is FormatException ||
                                      e is AggregateException || e is ObjectDisposedException ||
                                      e is InvalidOperationException || e is System.ComponentModel.Win32Exception)
            {
                LastStopFailed = true;
                LastError = e.GetType().Name + ": " + e.Message;
                return;
            }
            finally
            {
                LastMilliseconds = clock.Elapsed.TotalMilliseconds;
                pcm.Clear();
            }

            LastTranscript = text.Trim();
            if (PhraseSnapper.Normalize(LastTranscript).Length == 0 && !IsSilenceHallucination(LastTranscript))
            {
                Silent(); // Whisper heard no words
                return;
            }
            LastWasHallucination = IsSilenceHallucination(LastTranscript);
            if (LastWasHallucination && DropSilenceHallucinations)
            {
                Silent();
                return;
            }
            if (snapper == null)
            {
                string words = PhraseSnapper.Normalize(LastTranscript);
                if (words.Length == 0)
                    NoResult?.Invoke(NoResultReason.NotUnderstood);
                else
                    Recognized?.Invoke(new RecognitionResult(words, 1f));
                return;
            }
            // Never drop unknown words or the second half of a compound request while snapping.
            // The capability-advertised host planner validates every clause before anything runs.
            if (compositionGrammar && VoiceSession.IsCompositionRequest(LastTranscript))
            {
                Recognized?.Invoke(new RecognitionResult(LastTranscript, 1f));
                return;
            }
            LastSnap = snapper.Snap(LastTranscript);
            if (!LastSnap.Accepted)
            {
                NoResult?.Invoke(NoResultReason.NotUnderstood); // speech, but no command: "didn't catch that"
                return;
            }
            Recognized?.Invoke(new RecognitionResult(LastSnap.Text,
                LastSnap.WordForWord ? LastSnap.Similarity : Math.Min(LastSnap.Similarity, guessConfidence)));
        }

        /// <summary>No speech: sets <see cref="LastWasSilence"/> and raises <see cref="NoResult"/> with
        /// <see cref="NoResultReason.Silence"/>.</summary>
        void Silent()
        {
            LastWasSilence = true;
            NoResult?.Invoke(NoResultReason.Silence);
        }

        /// <summary>
        /// Whisper's words for silence or noise: "you", "Thank you.", "[BLANK_AUDIO]", "(music)", a single "um".
        /// A whole transcript in brackets or parentheses is a sound description, never speech.
        /// </summary>
        public static bool IsSilenceHallucination(string transcript)
        {
            string trimmed = (transcript ?? "").Trim().TrimEnd('.', '!', '?', ',').Trim();
            if (trimmed.Length == 0)
                return false;
            if ((trimmed[0] == '[' && trimmed[trimmed.Length - 1] == ']') || (trimmed[0] == '(' && trimmed[trimmed.Length - 1] == ')') ||
                (trimmed[0] == '*' && trimmed[trimmed.Length - 1] == '*'))
                return true;
            var words = new StringBuilder();
            foreach (char c in trimmed.ToLowerInvariant())
                words.Append(char.IsLetter(c) ? c : ' ');
            string normalized = string.Join(" ", words.ToString().Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries));
            return SilenceHallucinations.Contains(normalized);
        }

        /// <summary>
        /// At least <see cref="MinSpeechFrames"/> 30 ms frames reach <paramref name="minRms"/> (see
        /// <see cref="DefaultMinSpeechRms"/>). A threshold of 0 or less lets everything through.
        /// </summary>
        public static bool HasSpeech(IReadOnlyList<short> samples, int sampleRate, float minRms)
        {
            if (minRms <= 0f)
                return true;
            int frame = Math.Max(1, sampleRate * 30 / 1000);
            double needed = (double)minRms * minRms * frame;
            int loud = 0;
            for (int start = 0; start + frame <= samples.Count; start += frame)
            {
                double energy = 0;
                for (int i = start; i < start + frame; i++)
                    energy += (double)samples[i] * samples[i];
                if (energy >= needed && ++loud >= MinSpeechFrames)
                    return true;
            }
            return false;
        }

        public void Dispose()
        {
            pcm.Clear();
            Server?.Dispose();
            Server = null;
        }

        void Restart()
        {
            try
            {
                Server.EnsureRunning();
            }
            catch (Exception e)
            {
                restartFailed = "whisper-server could not be restarted (" + e.GetType().Name + ": " + e.Message + ")";
                throw;
            }
        }

        /// <summary>
        /// <paramref name="basePrompt"/> plus the grammar's words that it doesn't already name (object names, choice
        /// words), up to <see cref="MaxPromptChars"/>. One- and two-letter words are left out: they don't help Whisper.
        /// </summary>
        public static string PromptFor(string basePrompt, IReadOnlyList<string> phrases)
        {
            if (phrases == null || phrases.Count == 0)
                return basePrompt;
            var known = new HashSet<string>(PhraseSnapper.Normalize(basePrompt).Split(' '), StringComparer.Ordinal);
            var extra = new StringBuilder();
            foreach (string phrase in phrases)
                foreach (string word in PhraseSnapper.Normalize(phrase).Split(' '))
                {
                    if (word.Length < 3 || !known.Add(word))
                        continue;
                    if (basePrompt.Length + extra.Length + word.Length + 2 > MaxPromptChars)
                        return Join(basePrompt, extra);
                    extra.Append(extra.Length == 0 ? "" : ", ").Append(word);
                }
            return Join(basePrompt, extra);
        }

        static string Join(string basePrompt, StringBuilder extra) =>
            extra.Length == 0 ? basePrompt : (basePrompt + " " + extra + ".").Trim();

        string Transcribe(byte[] wav)
        {
            string boundary = "----voicecore" + Guid.NewGuid().ToString("N");
            var body = new MemoryStream();
            void Field(string name, string value) =>
                Write(body, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + name + "\"\r\n\r\n" + value + "\r\n");
            Field("response_format", "json");
            Field("temperature", "0");
            Field("temperature_inc", "0"); // no fallback decodes: one greedy pass, as measured
            Field("no_timestamps", "true");
            Field("suppress_nst", "true");
            Field("language", "en");
            if (prompt.Length > 0)
                Field("prompt", prompt);
            Write(body, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"utterance.wav\"\r\n" +
                        "Content-Type: audio/wav\r\n\r\n");
            body.Write(wav, 0, wav.Length);
            Write(body, "\r\n--" + boundary + "--\r\n");

            string head = "POST /inference HTTP/1.1\r\nHost: " + host + ":" + port + "\r\nContent-Type: multipart/form-data; boundary=" +
                          boundary + "\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n";
            (int status, string reply) = Http.Send(host, port, head, body.ToArray(), timeoutMs);
            if (status != 200)
                throw new IOException("whisper-server answered " + status + ": " + Http.FirstLine(reply));
            return JsonText(reply);
        }

        static void Write(Stream stream, string text)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(text);
            stream.Write(bytes, 0, bytes.Length);
        }

        /// <summary>The "text" string of whisper-server's JSON reply, with JSON escapes decoded.</summary>
        internal static string JsonText(string json)
        {
            int at = json.IndexOf("\"text\"", StringComparison.Ordinal);
            int colon = at < 0 ? -1 : json.IndexOf(':', at + 6);
            int open = colon < 0 ? -1 : json.IndexOf('"', colon + 1);
            if (open < 0)
                throw new FormatException("No text in whisper-server's reply: " + Http.FirstLine(json));
            var text = new StringBuilder();
            for (int i = open + 1; i < json.Length; i++)
            {
                char c = json[i];
                if (c == '"')
                    return text.ToString();
                if (c != '\\' || i + 1 >= json.Length)
                {
                    text.Append(c);
                    continue;
                }
                char escape = json[++i];
                if (escape == 'u' && i + 4 < json.Length)
                {
                    text.Append((char)int.Parse(json.Substring(i + 1, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                    i += 4;
                }
                else
                    text.Append(escape == 'n' ? '\n' : escape == 't' ? '\t' : escape == 'r' ? '\r' : escape == 'b' ? '\b' : escape == 'f' ? '\f' : escape);
            }
            throw new FormatException("Unterminated text in whisper-server's reply");
        }

        /// <summary>16-bit mono PCM as a WAV file.</summary>
        internal static byte[] Wav(IReadOnlyList<short> samples, int sampleRate)
        {
            var memory = new MemoryStream(44 + samples.Count * 2);
            var writer = new BinaryWriter(memory);
            int bytes = samples.Count * 2;
            writer.Write(Encoding.ASCII.GetBytes("RIFF"));
            writer.Write(36 + bytes);
            writer.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
            writer.Write(16);
            writer.Write((short)1); // PCM
            writer.Write((short)1); // mono
            writer.Write(sampleRate);
            writer.Write(sampleRate * 2);
            writer.Write((short)2);
            writer.Write((short)16);
            writer.Write(Encoding.ASCII.GetBytes("data"));
            writer.Write(bytes);
            foreach (short sample in samples)
                writer.Write(sample);
            writer.Flush();
            return memory.ToArray();
        }
    }

    /// <summary>Just enough HTTP/1.1 for whisper-server, over a plain TcpClient (see <see cref="WhisperServerRecognizer"/>).</summary>
    static class Http
    {
        /// <summary>Sends one request with <c>Connection: close</c> and returns the status and the body.</summary>
        public static (int status, string body) Send(string host, int port, string head, byte[] body, int timeoutMs)
        {
            using (var client = new TcpClient())
            {
                client.NoDelay = true;
                client.SendTimeout = timeoutMs;
                client.ReceiveTimeout = timeoutMs;
                if (!client.ConnectAsync(host, port).Wait(timeoutMs))
                    throw new IOException("No answer from whisper-server on " + host + ":" + port + " within " + timeoutMs + " ms");
                NetworkStream stream = client.GetStream();
                byte[] headBytes = Encoding.ASCII.GetBytes(head);
                stream.Write(headBytes, 0, headBytes.Length);
                if (body != null && body.Length > 0)
                    stream.Write(body, 0, body.Length);
                var reply = new MemoryStream();
                stream.CopyTo(reply); // the server closes the connection after the reply
                string all = Encoding.UTF8.GetString(reply.ToArray());
                int split = all.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                string[] statusLine = FirstLine(all).Split(' ');
                if (split < 0 || statusLine.Length < 2 || !statusLine[0].StartsWith("HTTP/", StringComparison.Ordinal) ||
                    !int.TryParse(statusLine[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out int status))
                    throw new IOException("Not an HTTP reply from " + host + ":" + port + ": " + FirstLine(all));
                return (status, all.Substring(split + 4));
            }
        }

        public static string FirstLine(string text)
        {
            int end = text.IndexOf('\n');
            return (end < 0 ? text : text.Substring(0, end)).Trim();
        }
    }
}
