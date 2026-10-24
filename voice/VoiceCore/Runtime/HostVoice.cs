using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// A <c>voice.resolve</c> request (contracts/README.md, Voice): words VoiceCore can't turn into a command by itself,
    /// for the host's resolver. Send a message of type <see cref="Type"/> with <see cref="Payload"/>, then pass its
    /// message ID to <see cref="VoiceSession.ResolveSent"/>; the answer is a <c>voice.candidates</c> whose <c>re</c> is
    /// that ID.
    /// </summary>
    public sealed class VoiceResolve
    {
        public const string Type = "voice.resolve";

        /// <summary>The contract's longest <c>text</c>; longer text (only typed) stays on VoiceCore's own path.</summary>
        public const int MaxText = 500;

        internal VoiceResolve(string text, float confidence, SceneObject target, bool lowConfidence)
        {
            Text = text;
            Confidence = confidence;
            TargetId = target?.Id;
            LowConfidence = lowConfidence;
        }

        /// <summary>The transcript as heard.</summary>
        public string Text { get; }

        /// <summary>The recognizer's confidence, 0 to 1. Below <see cref="VoiceSessionOptions.MinConfidence"/> the host may
        /// only ask, never run (and the session treats a run as a question).</summary>
        public float Confidence { get; }

        /// <summary>The object the words refer to (named, selected, pointed at, or the only one), or null.</summary>
        public string TargetId { get; }

        /// <summary>The confidence is below <see cref="VoiceSessionOptions.MinConfidence"/>.</summary>
        public bool LowConfidence { get; }

        /// <summary>The message payload as plain data, like <see cref="HostCommand.Args"/>: <c>JObject.FromObject</c> turns
        /// it into JSON. Pass the target's current <c>generation</c>; without one the target is left out.</summary>
        public IReadOnlyDictionary<string, object> Payload(long? targetGeneration)
        {
            var payload = new Dictionary<string, object>
            {
                { "text", Text },
                { "confidence", Math.Round(Math.Min(1.0, Math.Max(0.0, Confidence)), 3) },
            };
            if (TargetId != null && targetGeneration.HasValue)
                payload["target"] = new Dictionary<string, object> { { "id", TargetId }, { "generation", targetGeneration.Value } };
            return payload;
        }
    }

    /// <summary>The host's <c>decision</c> in <c>voice.candidates</c>.</summary>
    public enum VoiceDecision
    {
        /// <summary>Sure: run the first candidate now.</summary>
        Run,
        /// <summary>Not sure: ask "which one?" with up to three candidates.</summary>
        Ask,
        /// <summary>Nothing fits: VoiceCore handles the words as it did before (usually "Sorry, I can't do that").</summary>
        Reject,
    }

    /// <summary>One of the host's candidates. The operator is for display only: running it means sending
    /// <c>voice.run</c> with its <see cref="Choice"/>, and the host runs its own copy.</summary>
    public sealed class VoiceCandidate
    {
        public VoiceCandidate(int choice, string say, string op = null, bool needsTarget = false)
        {
            Choice = choice;
            Say = say ?? "";
            Operator = op;
            NeedsTarget = needsTarget;
        }

        /// <summary>1 to 3: what the user says to pick it.</summary>
        public int Choice { get; }

        /// <summary>Its name, to show next to its number ("Subdivision Surface").</summary>
        public string Say { get; }

        /// <summary>The Blender operator, for display only (<c>object.modifier_add</c>).</summary>
        public string Operator { get; }

        /// <summary>It acts on the request's target, which <c>voice.run</c> then names.</summary>
        public bool NeedsTarget { get; }

        public override string ToString() => Choice + ". " + Say;
    }

    /// <summary>A <c>voice.candidates</c> answer: read it with <see cref="FromJson"/>, then pass it to
    /// <see cref="VoiceSession.HostAnswered"/> with the message's <c>re</c>.</summary>
    public sealed class VoiceCandidates
    {
        public const string Type = "voice.candidates";

        public VoiceCandidates(string resolution, VoiceDecision decision, string reason, double expiresIn,
            IReadOnlyList<VoiceCandidate> candidates)
        {
            Resolution = resolution ?? throw new ArgumentNullException(nameof(resolution));
            Decision = decision;
            Reason = reason;
            ExpiresIn = expiresIn;
            Candidates = candidates ?? new VoiceCandidate[0];
        }

        /// <summary>The ID that <c>voice.run</c> names.</summary>
        public string Resolution { get; }

        public VoiceDecision Decision { get; }

        /// <summary>Why the host asked or rejected, for display, or null.</summary>
        public string Reason { get; }

        /// <summary>Seconds the host keeps the candidates; <c>voice.run</c> after that fails.</summary>
        public double ExpiresIn { get; }

        /// <summary>Best first, at most three.</summary>
        public IReadOnlyList<VoiceCandidate> Candidates { get; }

        /// <summary>Reads a <c>voice.candidates</c> payload (the message's <c>payload</c> object as JSON text).</summary>
        /// <exception cref="FormatException">It isn't one.</exception>
        public static VoiceCandidates FromJson(string payloadJson)
        {
            var payload = MiniJson.Parse(payloadJson) as Dictionary<string, object>
                ?? throw new FormatException("voice.candidates payload is not an object");
            string decision = MiniJson.Get<string>(payload, "decision");
            VoiceDecision parsed = decision == "run" ? VoiceDecision.Run : decision == "ask" ? VoiceDecision.Ask
                : decision == "reject" ? VoiceDecision.Reject : throw new FormatException("Unknown decision " + decision);
            var candidates = new List<VoiceCandidate>();
            if (payload.TryGetValue("candidates", out object list) && list is List<object> items)
                foreach (object item in items)
                {
                    var c = item as Dictionary<string, object> ?? throw new FormatException("candidate is not an object");
                    candidates.Add(new VoiceCandidate((int)MiniJson.Get<double>(c, "choice"), MiniJson.Get<string>(c, "say"),
                        MiniJson.Optional<string>(c, "operator"), MiniJson.Optional<bool>(c, "needs_target")));
                }
            return new VoiceCandidates(MiniJson.Get<string>(payload, "resolution"), parsed, MiniJson.Optional<string>(payload, "reason"),
                payload.ContainsKey("expires_in") ? MiniJson.Get<double>(payload, "expires_in") : 30, candidates);
        }
    }

    /// <summary>The host's <c>voice.grammar</c>: the phrases its resolver knows, for <see cref="VoiceSession.SetHostGrammar"/>.
    /// Ask for it after <c>welcome</c> with a <see cref="QueryType"/> message (payload <c>{}</c>); the answer's <c>re</c> is
    /// the query's ID. A host without voice answers <c>error</c> <c>unknown_type</c>: then call
    /// <see cref="VoiceSession.HostHasNoVoice"/>.</summary>
    public static class VoiceGrammar
    {
        public const string Type = "voice.grammar";

        /// <summary>The request for the host's <c>voice.grammar</c>.</summary>
        public const string QueryType = "voice.grammar_query";

        /// <summary>Reads the <c>phrases</c> of a <c>voice.grammar</c> payload (the <c>payload</c> object as JSON text).</summary>
        /// <exception cref="FormatException">It isn't one.</exception>
        public static IReadOnlyList<string> FromJson(string payloadJson)
        {
            var payload = MiniJson.Parse(payloadJson) as Dictionary<string, object>
                ?? throw new FormatException("voice.grammar payload is not an object");
            var phrases = new List<string>();
            foreach (object phrase in MiniJson.Get<List<object>>(payload, "phrases"))
                phrases.Add(phrase as string ?? throw new FormatException("phrase is not a string"));
            return phrases;
        }
    }

    /// <summary>The host's question waiting for "one", "two" or "three", for the UI to show with its options and a
    /// Cancel button. <see cref="VoiceSession.Choose"/> answers it from a button.</summary>
    public sealed class PendingChoice
    {
        internal PendingChoice(VoiceCandidates candidates, SceneObject target, DateTime expiresAt)
        {
            Resolution = candidates.Resolution;
            Candidates = candidates.Candidates;
            Reason = candidates.Reason;
            Target = target;
            ExpiresAt = expiresAt;
        }

        public string Resolution { get; }

        /// <summary>Show each as "1. Subdivision Surface".</summary>
        public IReadOnlyList<VoiceCandidate> Candidates { get; }

        /// <summary>The host's reason for asking, or null.</summary>
        public string Reason { get; }

        /// <summary>The object the request named, or null.</summary>
        public SceneObject Target { get; }

        /// <summary>In the session clock's time (UTC by default).</summary>
        public DateTime ExpiresAt { get; }
    }

    /// <summary>
    /// The answers to "which one?": only these phrases, said exactly, count. The recognizer grammar while asking is these
    /// phrases plus "[unk]", so that other speech comes out as "[unk]" (and is ignored) instead of being forced onto a
    /// number. Measured on TTS: 20/20 answers, and 0 of 220 chatter clips answered; without the "[unk]" check 7 of 20
    /// chatter clips became answers. Ordinals are their own phrases, so "the second one" can't be read as "one".
    /// </summary>
    internal static class ChoiceWords
    {
        static readonly string[][] Spoken =
        {
            new[] { "one", "first", "option one", "number one", "the first one" },
            new[] { "two", "second", "option two", "number two", "the second one" },
            new[] { "three", "third", "option three", "number three", "the third one" },
        };

        static readonly string[] CancelPhrases = { "cancel", "never mind" };

        /// <summary>Also accepted from text input (Windows dictation, the app's text box), but not in the grammar.</summary>
        static readonly Dictionary<string, int> Typed = new Dictionary<string, int>
        {
            { "the first", 1 }, { "the second", 2 }, { "the third", 3 },
            { "first one", 1 }, { "second one", 2 }, { "third one", 3 }, { "nevermind", 0 }, { "cancel that", 0 },
        };

        /// <summary>The grammar while asking: the phrases for the offered choices, cancel, and "[unk]".</summary>
        public static List<string> Grammar(IReadOnlyList<VoiceCandidate> offered)
        {
            var phrases = new List<string>();
            for (int n = 1; n <= Spoken.Length; n++)
                if (Offers(offered, n))
                    phrases.AddRange(Spoken[n - 1]);
            phrases.AddRange(CancelPhrases);
            phrases.Add(Vocabulary.Unknown);
            return phrases;
        }

        /// <summary>The offered choice the words say, 0 for cancel, or null when they aren't exactly an answer to this
        /// question.</summary>
        public static int? Read(string text, IReadOnlyList<VoiceCandidate> offered)
        {
            List<string> words = Vocabulary.Words(text);
            if (words.Count == 0 || words.Contains(Vocabulary.Unknown))
                return null;
            string said = string.Join(" ", words);
            if (Array.IndexOf(CancelPhrases, said) >= 0)
                return 0;
            int? choice = Typed.TryGetValue(said, out int typed) ? typed : (int?)null;
            for (int n = 0; n < Spoken.Length && choice == null; n++)
                if (Array.IndexOf(Spoken[n], said) >= 0)
                    choice = n + 1;
            return choice == 0 || (choice.HasValue && Offers(offered, choice.Value)) ? choice : null;
        }

        /// <summary>Not a command but a garbled answer: every word is an answer word, "[unk]" or a filler ("[unk] two",
        /// "two please", "to"). Anything else said while asking is a new command.</summary>
        public static bool LooksLikeAnAnswer(string text)
        {
            foreach (string word in Vocabulary.Words(text))
                if (word != Vocabulary.Unknown && !AnswerWords.Contains(word) && !Fillers.Contains(word))
                    return false;
            return true;
        }

        static readonly HashSet<string> Fillers = new HashSet<string>(StringComparer.Ordinal)
        {
            "please", "to", "too", "uh", "um", "er", "oh", "ok", "okay", "yes", "yeah", "that", "this", "it", "is", "a", "an", "and",
        };

        static readonly HashSet<string> AnswerWords = Collect();

        static HashSet<string> Collect()
        {
            var words = new HashSet<string>(StringComparer.Ordinal);
            foreach (string[] phrases in Spoken)
                foreach (string phrase in phrases)
                    words.UnionWith(phrase.Split(' '));
            foreach (string phrase in CancelPhrases)
                words.UnionWith(phrase.Split(' '));
            foreach (string phrase in Typed.Keys)
                words.UnionWith(phrase.Split(' '));
            return words;
        }

        static bool Offers(IReadOnlyList<VoiceCandidate> offered, int number)
        {
            foreach (VoiceCandidate candidate in offered)
                if (candidate.Choice == number)
                    return true;
            return false;
        }
    }

    /// <summary>
    /// Just enough JSON for the host's voice messages, so VoiceCore needs no JSON library: objects become
    /// <c>Dictionary&lt;string, object&gt;</c>, arrays <c>List&lt;object&gt;</c>, numbers double, and true, false and null
    /// themselves.
    /// </summary>
    internal static class MiniJson
    {
        public static object Parse(string json)
        {
            if (json == null)
                throw new FormatException("No JSON");
            int at = 0;
            object value = Value(json, ref at);
            SkipSpace(json, ref at);
            if (at != json.Length)
                throw new FormatException("Unexpected text after the JSON value at " + at);
            return value;
        }

        public static T Get<T>(Dictionary<string, object> obj, string key) =>
            obj.TryGetValue(key, out object value) && value is T typed ? typed
                : throw new FormatException("\"" + key + "\" is missing or not a " + typeof(T).Name);

        public static T Optional<T>(Dictionary<string, object> obj, string key) =>
            obj.TryGetValue(key, out object value) && value is T typed ? typed : default;

        static object Value(string s, ref int at)
        {
            SkipSpace(s, ref at);
            if (at >= s.Length)
                throw new FormatException("Unexpected end of JSON");
            char c = s[at];
            if (c == '{')
            {
                var obj = new Dictionary<string, object>();
                at++;
                SkipSpace(s, ref at);
                if (Take(s, ref at, '}'))
                    return obj;
                do
                {
                    SkipSpace(s, ref at);
                    string key = String(s, ref at);
                    SkipSpace(s, ref at);
                    Expect(s, ref at, ':');
                    obj[key] = Value(s, ref at);
                    SkipSpace(s, ref at);
                } while (Take(s, ref at, ','));
                Expect(s, ref at, '}');
                return obj;
            }
            if (c == '[')
            {
                var list = new List<object>();
                at++;
                SkipSpace(s, ref at);
                if (Take(s, ref at, ']'))
                    return list;
                do
                {
                    list.Add(Value(s, ref at));
                    SkipSpace(s, ref at);
                } while (Take(s, ref at, ','));
                Expect(s, ref at, ']');
                return list;
            }
            if (c == '"')
                return String(s, ref at);
            if (Word(s, ref at, "true"))
                return true;
            if (Word(s, ref at, "false"))
                return false;
            if (Word(s, ref at, "null"))
                return null;
            int start = at;
            while (at < s.Length && "+-0123456789.eE".IndexOf(s[at]) >= 0)
                at++;
            if (start < at && double.TryParse(s.Substring(start, at - start), NumberStyles.Float, CultureInfo.InvariantCulture, out double number))
                return number;
            throw new FormatException("Unexpected character '" + c + "' at " + start);
        }

        static string String(string s, ref int at)
        {
            Expect(s, ref at, '"');
            var text = new StringBuilder();
            while (true)
            {
                if (at >= s.Length)
                    throw new FormatException("Unterminated string");
                char c = s[at++];
                if (c == '"')
                    return text.ToString();
                if (c != '\\')
                {
                    text.Append(c);
                    continue;
                }
                if (at >= s.Length)
                    throw new FormatException("Unterminated string");
                char e = s[at++];
                switch (e)
                {
                    case 'n': text.Append('\n'); break;
                    case 't': text.Append('\t'); break;
                    case 'r': text.Append('\r'); break;
                    case 'b': text.Append('\b'); break;
                    case 'f': text.Append('\f'); break;
                    case 'u':
                        if (at + 4 > s.Length || !int.TryParse(s.Substring(at, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out int code))
                            throw new FormatException("Bad \\u escape at " + at);
                        text.Append((char)code);
                        at += 4;
                        break;
                    default: text.Append(e); break; // \" \\ \/
                }
            }
        }

        static void SkipSpace(string s, ref int at)
        {
            while (at < s.Length && char.IsWhiteSpace(s[at]))
                at++;
        }

        static bool Take(string s, ref int at, char c)
        {
            if (at < s.Length && s[at] == c)
            {
                at++;
                return true;
            }
            return false;
        }

        static void Expect(string s, ref int at, char c)
        {
            if (!Take(s, ref at, c))
                throw new FormatException("Expected '" + c + "' at " + at);
        }

        static bool Word(string s, ref int at, string word)
        {
            if (string.CompareOrdinal(s, at, word, 0, word.Length) != 0)
                return false;
            at += word.Length;
            return true;
        }
    }
}
