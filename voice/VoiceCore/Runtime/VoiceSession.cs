using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    public sealed class VoiceSessionOptions
    {
        /// <summary>Results below this confidence are rejected and never produce a command. Confidence is the lowest
        /// word confidence, and Vosk gives "two" about 0.5 because "to" sounds the same, so a higher threshold rejects
        /// nearly every command with "two" in it. Checked with real voices in #93 (laptop and earphone microphones);
        /// recheck with the Quest microphone. See voice/README.md, "Confidence threshold".</summary>
        public float MinConfidence { get; set; } = 0.5f;

        /// <summary>A pending command is dropped this long after its last question.</summary>
        public TimeSpan PendingTimeout { get; set; } = TimeSpan.FromSeconds(30);

        /// <summary>The pointer must rest this long on an object before it answers "which object?".</summary>
        public TimeSpan PointerDwell { get; set; } = TimeSpan.FromSeconds(0.5);

        /// <summary>Send words VoiceCore can't turn into a command by itself to the host's resolver
        /// (<see cref="VoiceTurn.Resolve"/>). Off by default: without it the session works exactly as before.</summary>
        public bool AskHost { get; set; }

        /// <summary>How long to wait for the host's <c>voice.candidates</c> before handling the words as if there were no
        /// host. At least 3 s: a reply can wait 1.1 to 2.4 s behind a large scene message on the app's read thread.</summary>
        public TimeSpan HostTimeout { get; set; } = TimeSpan.FromSeconds(3);

        /// <summary>Answers to "which one?" below this confidence are asked again. On real speech (Speech Commands, 71
        /// answers and 488 other words, exact phrases only): 0.9 kept 68 answers with none wrong and let 13 other words
        /// through, against 69, 1 wrong and 24 at 0.6. The choice grammar has no "to", so "two" scores high.</summary>
        public float ChoiceMinConfidence { get; set; } = 0.9f;
    }

    [Flags]
    public enum MissingFields { None = 0, Shape = 1, Target = 2, Axis = 4, Amount = 8, Unit = 16 }

    /// <summary>The command waiting for missing information, for the UI to show with a Cancel button.</summary>
    public sealed class PendingCommand
    {
        internal PendingCommand(VoiceCommand command, MissingFields missing, DateTime expiresAt)
        {
            Command = command;
            Missing = missing;
            ExpiresAt = expiresAt;
        }

        /// <summary>What is known so far; missing fields are null.</summary>
        public VoiceCommand Command { get; }

        public MissingFields Missing { get; }

        /// <summary>In the session clock's time (UTC by default).</summary>
        public DateTime ExpiresAt { get; }
    }

    /// <summary>The result of one input: at most one command to execute, and prompts to play and show in order.</summary>
    public sealed class VoiceTurn
    {
        internal VoiceTurn(VoiceCommand command, IReadOnlyList<Prompt> prompts, VoiceResolve resolve = null, bool grammarChanged = false,
            string hostReason = null, NoResultReason? noResult = null, bool choiceDismissed = false, bool asked = false)
        {
            Command = command;
            Prompts = prompts;
            Resolve = resolve;
            GrammarChanged = grammarChanged;
            HostReason = hostReason;
            NoResult = noResult;
            ChoiceDismissed = choiceDismissed;
            CancelsDelete = asked || (command != null && command.Kind != CommandKind.Cancel);
        }

        /// <summary>The press gave nothing to act on (<see cref="VoiceSession.NothingRecognized"/>, or empty words): show a
        /// short "Didn't catch that". Only <see cref="NoResultReason.NotUnderstood"/> also has a spoken prompt; a silent
        /// press has none, so it never speaks.</summary>
        public NoResultReason? NoResult { get; }

        /// <summary>The host's "which one?" (<see cref="VoiceSession.Choice"/>) was dropped because the words weren't an
        /// answer: hide its panel. Words with a command are handled as that new command in the same turn.</summary>
        public bool ChoiceDismissed { get; }

        /// <summary>
        /// The newest request wins over a Delete waiting for its controller confirmation: this turn has a new command
        /// (anything but Cancel, which cancels the delete itself) or asks a new question (a missing field, or the host's
        /// "which one?"). The app must then drop the waiting delete and say <see cref="Prompt.ReplacedPending"/>, so the
        /// trigger can never confirm a delete the panel no longer shows. Words still waiting for the host don't cancel
        /// it; the host's answer does if it runs or asks.
        /// </summary>
        public bool CancelsDelete { get; }

        /// <summary>The host's reason for rejecting or asking ("Join isn't available by voice."), to show next to the
        /// prompts, or null.</summary>
        public string HostReason { get; }

        /// <summary>A complete command to send through the normal command path, or null. A <see cref="CommandKind.Run"/>
        /// goes out like the others, as <c>voice.run</c> (<see cref="HostCommand.From"/>).</summary>
        public VoiceCommand Command { get; }

        public IReadOnlyList<Prompt> Prompts { get; }

        /// <summary>Words for the host's resolver, or null: send them as <c>voice.resolve</c> and report the message ID with
        /// <see cref="VoiceSession.ResolveSent"/>. Only with <see cref="VoiceSessionOptions.AskHost"/>.</summary>
        public VoiceResolve Resolve { get; }

        /// <summary>A question about the host's candidates began or ended: pass <see cref="VoiceSession.GrammarPhrases"/>
        /// to the recognizer again.</summary>
        public bool GrammarChanged { get; }

        public override string ToString() =>
            (Command == null ? "no command" : Command.ToString()) + (Prompts.Count == 0 ? "" : " [" + string.Join(", ", Prompts) + "]") +
            (Resolve == null ? "" : " ask host: " + Resolve.Text) + (NoResult == null ? "" : " no result: " + NoResult) +
            (ChoiceDismissed ? " question dismissed" : "");
    }

    /// <summary>
    /// Voice conversation memory: turns recognized utterances plus selection and pointer events into complete
    /// commands, asking only for what is missing. It keeps at most one pending command.
    /// With <see cref="VoiceSessionOptions.AskHost"/>, words it can't handle by itself go to the host's resolver
    /// (<see cref="VoiceTurn.Resolve"/>), which runs a Blender operation or asks "which one?" (<see cref="Choice"/>).
    /// Whenever the host can't help (it rejects the words, doesn't know <c>voice.resolve</c>, or doesn't answer within
    /// <see cref="VoiceSessionOptions.HostTimeout"/>), the words are handled exactly as without a host.
    /// Not thread-safe: call it from the Unity main thread, and call <see cref="Tick"/> every frame.
    /// </summary>
    public sealed partial class VoiceSession
    {
        readonly VoiceSessionOptions options;
        readonly Func<DateTime> clock;

        List<SceneObject> objects = new List<SceneObject>();
        readonly List<string> selection = new List<string>();
        string pointerId;
        DateTime pointerSince;
        bool promptPlaying;

        Draft pending;
        DateTime pendingSince;
        DateTime expiresAt;

        List<string> hostGrammar = new List<string>();
        bool hostResolves = true; // false once this connection's host answered unknown_type
        Resolving resolving;      // words sent to the host and not answered yet
        PendingChoice choice;     // the host's "which one?"

        public VoiceSession() : this(new VoiceSessionOptions(), () => DateTime.UtcNow) { }

        public VoiceSession(VoiceSessionOptions options, Func<DateTime> clock)
        {
            this.options = options ?? throw new ArgumentNullException(nameof(options));
            this.clock = clock ?? throw new ArgumentNullException(nameof(clock));
        }

        /// <summary>The command waiting for information, or null.</summary>
        public PendingCommand Pending =>
            pending == null ? null : new PendingCommand(pending.ToCommand(), pending.Missing, expiresAt);

        public IReadOnlyList<SceneObject> Objects => objects;

        /// <summary>The host's question waiting for "one", "two" or "three", or null. Show its candidates numbered, with
        /// a Cancel button; <see cref="Choose"/> answers it from a button.</summary>
        public PendingChoice Choice => choice;

        /// <summary>Words were sent to the host and its answer hasn't come yet (show that it is thinking).</summary>
        public bool WaitingForHost => resolving != null;

        /// <summary>
        /// The recognizer grammar: VoiceCore's words, the current objects' names and the host's phrases
        /// (<see cref="SetHostGrammar"/>). While <see cref="Choice"/> is pending it is only the answers ("one", "the
        /// second one", "cancel", ...) and "[unk]", so other speech can't become an answer. Pass it to
        /// <see cref="ISpeechRecognizer.SetGrammar"/> at startup, after every <see cref="SetObjects"/> and
        /// <see cref="SetHostGrammar"/>, and after every turn with <see cref="VoiceTurn.GrammarChanged"/>.
        /// </summary>
        public IReadOnlyList<string> GrammarPhrases()
        {
            if (choice != null)
                return ChoiceWords.Grammar(choice.Candidates);
            var names = new List<string>();
            foreach (SceneObject obj in objects)
                names.Add(obj.Name);
            List<string> phrases = Vocabulary.GrammarPhrases(names);
            if (hostGrammar.Count == 0)
                return phrases;
            var merged = new SortedSet<string>(phrases, StringComparer.Ordinal);
            merged.Remove(Vocabulary.Unknown);
            // "to" only fills ("scale this to fifty percent"), and Vosk splits "two"'s confidence with it. With the host's
            // phrases (which leave it out too), dropping it took today's 17 commands from 201 to 205 of 255 right and
            // "two" from a median confidence of 0.78 to 1.0 (TTS, voice/README.md). Typed "to" still parses.
            merged.Remove("to");
            merged.UnionWith(hostGrammar);
            return new List<string>(merged) { Vocabulary.Unknown };
        }

        /// <summary>The phrases of the host's <c>voice.grammar</c> (<see cref="VoiceGrammar.FromJson"/>), merged into
        /// <see cref="GrammarPhrases"/>. Pass the grammar to the recognizer again afterwards.</summary>
        public void SetHostGrammar(IEnumerable<string> phrases)
        {
            var normalized = new SortedSet<string>(StringComparer.Ordinal);
            foreach (string phrase in phrases ?? new string[0])
            {
                List<string> words = Vocabulary.Words(phrase);
                if (words.Count > 0 && !words.Contains(Vocabulary.Unknown))
                    normalized.Add(string.Join(" ", words));
            }
            hostGrammar = new List<string>(normalized);
        }

        /// <summary>The objects the user can refer to: the ones the app shows (see <see cref="SceneObject"/>). Cancels
        /// a pending command whose target is no longer among them.</summary>
        public VoiceTurn SetObjects(IEnumerable<SceneObject> visibleObjects)
        {
            var turn = Begin();
            objects = new List<SceneObject>(visibleObjects);
            if (pointerId != null && Find(pointerId) == null)
                pointerId = null;
            if (pending?.Target != null)
            {
                pending.Target = Find(pending.Target.Id);
                if (pending.Target == null)
                {
                    pending = null;
                    turn.Prompts.Add(Prompt.TargetDeleted);
                }
            }
            if (choice?.Target != null && Find(choice.Target.Id) == null)
            {
                EndChoice(turn);
                turn.Prompts.Add(Prompt.TargetDeleted);
            }
            return turn.Build();
        }

        /// <summary>The user's current selection. A single selected object answers "which object?".</summary>
        public VoiceTurn SetSelection(IEnumerable<string> selectedIds)
        {
            var turn = Begin();
            selection.Clear();
            selection.AddRange(selectedIds);
            ResumeCompositionTarget(turn);
            if (pending != null && (pending.Missing & MissingFields.Target) != 0)
            {
                SceneObject selected = SingleSelected();
                if (selected != null)
                {
                    pending.Target = selected;
                    Advance(turn);
                }
            }
            return turn.Build();
        }

        /// <summary>The object under the pointer ray, or null. Call it whenever that changes.</summary>
        public VoiceTurn SetPointerTarget(string objectId)
        {
            var turn = Begin();
            if (objectId != pointerId)
            {
                pointerId = objectId;
                pointerSince = clock();
            }
            FillFromPointer(turn);
            return turn.Build();
        }

        /// <summary>A different document was opened or the session changed (the app's Wrong document state):
        /// forgets everything.</summary>
        public VoiceTurn DocumentChanged()
        {
            var turn = Begin();
            CancelComposition(turn, Prompt.DocumentChanged);
            if (pending != null || choice != null || resolving != null)
            {
                pending = null;
                resolving = null;
                EndChoice(turn);
                turn.Prompts.Add(Prompt.DocumentChanged);
            }
            objects = new List<SceneObject>();
            selection.Clear();
            pointerId = null;
            return turn.Build();
        }

        /// <summary>The host connection closed (the app's Disconnected state): drops the pending command, the host's
        /// question and its grammar. The objects stay until the fresh snapshot's <see cref="SetObjects"/>, or
        /// <see cref="DocumentChanged"/>. The next host is asked again, even if this one didn't know <c>voice.resolve</c>.</summary>
        public VoiceTurn ConnectionLost()
        {
            var turn = Begin();
            CancelComposition(turn, Prompt.ConnectionLost);
            if (pending != null || choice != null || resolving != null)
            {
                pending = null;
                resolving = null;
                EndChoice(turn);
                turn.Prompts.Add(Prompt.ConnectionLost);
            }
            if (hostGrammar.Count > 0)
            {
                hostGrammar = new List<string>();
                turn.GrammarChanged = true;
            }
            hostResolves = true;
            compositionEnabled = false;
            return turn.Build();
        }

        /// <summary>The UI's Cancel button for the pending command or the host's question.</summary>
        public VoiceTurn Cancel()
        {
            var turn = Begin();
            CancelComposition(turn, Prompt.Cancelled);
            if (pending != null || choice != null || resolving != null)
            {
                pending = null;
                resolving = null;
                EndChoice(turn);
                turn.Prompts.Add(Prompt.Cancelled);
            }
            return turn.Build();
        }

        /// <summary>Answers the host's question from a button: the candidate's <see cref="VoiceCandidate.Choice"/>.</summary>
        public VoiceTurn Choose(int number)
        {
            var turn = Begin();
            if (choice != null)
                Pick(number, turn);
            return turn.Build();
        }

        /// <summary>
        /// The <see cref="VoiceTurn.Resolve"/> request went out with this message ID, or couldn't be sent (null): then
        /// its words are handled as without a host.
        /// </summary>
        public VoiceTurn ResolveSent(VoiceResolve request, string messageId)
        {
            var turn = Begin();
            if (resolving == null || resolving.Request != request)
                return turn.Build(); // replaced by newer words meanwhile
            if (messageId == null)
                HearWithoutHost(turn);
            else
                resolving.MessageId = messageId;
            return turn.Build();
        }

        /// <summary>
        /// The host's <c>voice.candidates</c> (<see cref="VoiceCandidates.FromJson"/>), with the message's <c>re</c>.
        /// <list type="bullet">
        /// <item>run: the turn's <see cref="VoiceTurn.Command"/> runs the first candidate (<c>voice.run</c>, choice 1);</item>
        /// <item>ask: the turn says <see cref="Prompt.AskChoice"/>; show <see cref="Choice"/> and switch the grammar;</item>
        /// <item>reject: the words are handled as without a host.</item>
        /// </list>
        /// A run of words heard below <see cref="VoiceSessionOptions.MinConfidence"/> becomes a question, and so does a run of
        /// words with one of VoiceCore's shapes but no command verb ("selected cylinder" for "select the cylinder"). A
        /// pending command is dropped for a run or a question. Answers to older words, or after <see cref="VoiceSessionOptions.HostTimeout"/>,
        /// are ignored.
        /// </summary>
        public VoiceTurn HostAnswered(string re, VoiceCandidates answer)
        {
            var turn = Begin();
            if (answer == null || !Answers(re) || TimedOutWaiting(turn))
                return turn.Build();
            Resolving asked = resolving;
            turn.HostReason = answer.Reason;
            if (AnswerComposition(answer, turn)) return turn.Build();
            var candidates = new List<VoiceCandidate>();
            foreach (VoiceCandidate candidate in answer.Candidates)
                if (candidate != null && candidate.Choice >= 1 && candidate.Choice <= 3 && candidates.Count < 3)
                    candidates.Add(candidate);
            if (answer.Decision == VoiceDecision.Reject || candidates.Count == 0)
            {
                HearWithoutHost(turn);
                return turn.Build();
            }
            resolving = null;
            if (pending != null)
            {
                pending = null; // the host understood a new command
                turn.Prompts.Add(Prompt.ReplacedPending);
            }
            if (answer.Decision == VoiceDecision.Run && !asked.Request.LowConfidence && !asked.ShapeWithoutVerb)
            {
                RunCandidate(answer.Resolution, candidates[0], asked.Target, turn);
                return turn.Build();
            }
            double seconds = Math.Min(answer.ExpiresIn > 0 ? answer.ExpiresIn : double.MaxValue, options.PendingTimeout.TotalSeconds);
            choice = new PendingChoice(new VoiceCandidates(answer.Resolution, VoiceDecision.Ask, answer.Reason, seconds, candidates),
                asked.Target, clock() + TimeSpan.FromSeconds(seconds));
            turn.GrammarChanged = true;
            turn.Asked = true;
            turn.Prompts.Add(Prompt.AskChoice);
            return turn.Build();
        }

        /// <summary>This connection's host doesn't know voice (it answered <c>voice.grammar_query</c> with
        /// <c>unknown_type</c>): nothing is sent to it, and the grammar stays VoiceCore's own, until
        /// <see cref="ConnectionLost"/>.</summary>
        public void HostHasNoVoice() => hostResolves = false;

        /// <summary>An <c>error</c> whose <c>re</c> is a <c>voice.resolve</c>: the words are handled as without a host. After
        /// <c>unknown_type</c> (a host without voice) nothing more is sent to this connection's host.</summary>
        public VoiceTurn HostError(string re, string code)
        {
            var turn = Begin();
            if (!Answers(re) || TimedOutWaiting(turn))
                return turn.Build();
            if (code == "unknown_type")
                hostResolves = false;
            HearWithoutHost(turn);
            return turn.Build();
        }

        /// <summary>
        /// While a prompt plays, results are ignored so the app can't hear itself. Use it for a recognizer that listens by
        /// itself (Windows speech). With <see cref="VoiceInput"/>, pause that instead (<see cref="VoiceInput.Paused"/>):
        /// its results never contain a prompt, and speech that ended just before one is still heard.
        /// </summary>
        public void SetPromptPlaying(bool playing) => promptPlaying = playing;

        /// <summary>Expires the pending command and the host's question, gives up waiting for the host after
        /// <see cref="VoiceSessionOptions.HostTimeout"/>, and lets a resting pointer answer "which object?".</summary>
        public VoiceTurn Tick()
        {
            var turn = Begin();
            TimedOutWaiting(turn);
            FillFromPointer(turn);
            return turn.Build();
        }

        /// <summary>
        /// Handles one final recognized utterance. Words still waiting for the host's answer are dropped. While the host's
        /// question is open (<see cref="Choice"/>), an answer answers it; words with something else in them dismiss it
        /// (<see cref="VoiceTurn.ChoiceDismissed"/>) and are handled as a new command, routed to the host as usual.
        /// Empty words are a silent press (<see cref="VoiceTurn.NoResult"/>, nothing spoken).
        /// </summary>
        public VoiceTurn Hear(RecognitionResult result)
        {
            var turn = Begin();
            if (promptPlaying)
                return turn.Build();
            if (string.IsNullOrWhiteSpace(result.Text))
            {
                turn.NoResult = NoResultReason.Silence;
                return turn.Build();
            }
            if (HearComposition(result, turn)) return turn.Build();
            if (choice != null && HearChoice(result, turn))
                return turn.Build();
            resolving = null;
            if (ForHost(result))
                AskHost(result, turn);
            else
                HearHere(result, turn);
            return turn.Build();
        }

        /// <summary>
        /// A push-to-talk press that gave no result (<see cref="VoiceInput.TryGetNoResult"/>). The turn's
        /// <see cref="VoiceTurn.NoResult"/> lets the UI show "Didn't catch that". Silence says nothing and changes nothing.
        /// Speech that matched no phrase says <see cref="Prompt.LowConfidence"/>; while the host's question is open it also
        /// dismisses it: with the answers-only grammar that is a new command the recognizer couldn't hold, so the next try
        /// gets the full grammar back.
        /// </summary>
        public VoiceTurn NothingRecognized(NoResultReason reason)
        {
            var turn = Begin();
            if (promptPlaying)
                return turn.Build();
            turn.NoResult = reason;
            if (reason == NoResultReason.Silence)
                return turn.Build();
            if (choice != null)
            {
                EndChoice(turn);
                turn.ChoiceDismissed = true;
            }
            turn.Prompts.Add(Prompt.LowConfidence);
            return turn.Build();
        }

        /// <summary>
        /// Whether the words go to the host's resolver first (re-checked against the parser with #142's verb check):
        /// <list type="bullet">
        /// <item>no command verb ("shade smooth", "a monkey" with "add" lost);</item>
        /// <item>words VoiceCore doesn't know after the verb ("add a monkey", "select all");</item>
        /// <item>"apply" with more words ("apply the scale").</item>
        /// </list>
        /// Everything else stays on VoiceCore's own path: complete and partial core commands, undo, redo and cancel, two
        /// different verbs (a mishearing, checked first), and only "[unk]". While a command waits for a field, answers
        /// keep priority: only words without a verb that can't fill it go to the host, and none while it waits for its
        /// object, where unknown words are an object's name as before.
        /// </summary>
        bool ForHost(RecognitionResult result)
        {
            if (!options.AskHost || !hostResolves || result.Text.Length > VoiceResolve.MaxText)
                return false;
            ParsedUtterance parsed = CommandParser.Parse(result.Text, objects, pending?.Kind);
            if (!parsed.HasWords || parsed.ConflictingVerbs)
                return false;
            bool needsTarget = pending != null && (pending.Missing & MissingFields.Target) != 0;
            switch (parsed.Verb)
            {
                case null:
                    return pending == null || (parsed.HasUnknownWords && !needsTarget);
                case CommandKind.Undo:
                case CommandKind.Redo:
                case CommandKind.Cancel:
                    return false;
                case CommandKind.Apply:
                    return parsed.MoreAfterVerb;
                case CommandKind.Select when needsTarget:
                    return false; // "select the banana" answers "which object?" as before
                default:
                    return parsed.HasUnknownWords;
            }
        }

        /// <summary>Sends the words to the host, with the object they name or the context's (selection, pointer, only
        /// object). Below <see cref="VoiceSessionOptions.MinConfidence"/> they still go, so that the host can ask:
        /// Vosk gives "two" about 0.5 because "to" sounds the same.</summary>
        void AskHost(RecognitionResult result, Turn turn)
        {
            bool composing = compositionToken != null || (compositionEnabled && IsCompositionRequest(result.Text));
            // A compound transcript contains many parameter words and potentially several names.
            // The host resolves each clause; this field carries only the current controller context.
            SceneObject target = composing ? FromContext(CommandKind.Move)
                : CommandParser.NamedObject(result.Text, objects) ?? FromContext(CommandKind.Move);
            if (compositionToken != null && compositionMissing == "target" && result.Text.TrimStart().StartsWith("select ", StringComparison.OrdinalIgnoreCase))
                target = CommandParser.NamedObject(result.Text, objects) ?? target;
            var request = new VoiceResolve(result.Text, result.Confidence, target, result.Confidence < options.MinConfidence, compositionToken, composing);
            // One of VoiceCore's own shapes without its verb is a core command that lost its verb ("selected cylinder",
            // "on cube"): it could be select, add or delete, so the host may only ask. On TTS with today's grammar the
            // host otherwise ran "add a cylinder" for "select the cylinder" 3 times out of 15.
            ParsedUtterance parsed = CommandParser.Parse(result.Text, objects); // without the pending kind, so shapes count
            bool shapeWithoutVerb = parsed.Verb == null && parsed.Shape.HasValue;
            resolving = new Resolving(request, result, target, clock()) { ShapeWithoutVerb = shapeWithoutVerb };
            turn.Resolve = request;
        }

        bool Answers(string re) => resolving?.MessageId != null && re == resolving.MessageId;

        // An external interpreter proposes a complete typed recipe. Force host
        // resolution even when its words also contain a valid core prefix.
        public VoiceTurn ResolveRecipe(string transcript)
        {
            var turn = Begin();
            EndChoice(turn); ClearComposition(); pending = null;
            var result = new RecognitionResult(transcript, 1);
            var target = FromContext(CommandKind.Move);
            var request = new VoiceResolve(transcript, 1, target, false, null, true);
            resolving = new Resolving(request, result, target, clock());
            turn.Resolve = request;
            return turn.Build();
        }

        /// <summary>After the host timeout, handles the waiting words as without a host. True if it did.</summary>
        bool TimedOutWaiting(Turn turn)
        {
            if (resolving == null || clock() - resolving.SentAt < options.HostTimeout)
                return false;
            HearWithoutHost(turn);
            return true;
        }

        void HearWithoutHost(Turn turn)
        {
            RecognitionResult result = resolving.Result;
            bool wholePlan = resolving.Request.Composition;
            resolving = null;
            if (wholePlan || compositionToken != null || IsCompositionRequest(result.Text))
            {
                ClearComposition();
                turn.Prompts.Add(Prompt.Failed);
                return;
            }
            HearHere(result, turn);
        }

        /// <summary>The answer to the host's question: only an exact answer phrase without "[unk]" counts, at
        /// <see cref="VoiceSessionOptions.ChoiceMinConfidence"/> (ordinals first: "the second one" is two). Words made only
        /// of answer words, "[unk]" and fillers ("[unk] two", "two please", "to") are a garbled answer and ask again.
        /// Anything else dismisses the question and returns false: the caller handles the words as a new command.</summary>
        bool HearChoice(RecognitionResult result, Turn turn)
        {
            int? said = ChoiceWords.Read(result.Text, choice.Candidates);
            if (!said.HasValue && !ChoiceWords.LooksLikeAnAnswer(result.Text))
            {
                EndChoice(turn);
                turn.ChoiceDismissed = true;
                return false;
            }
            if (result.Confidence < options.ChoiceMinConfidence)
                turn.Prompts.Add(Prompt.LowConfidence);
            else if (said == 0)
            {
                EndChoice(turn);
                turn.Prompts.Add(Prompt.Cancelled);
            }
            else if (said.HasValue)
                Pick(said.Value, turn);
            else
                turn.Prompts.Add(Prompt.AskChoice);
            return true;
        }

        void Pick(int number, Turn turn)
        {
            VoiceCandidate picked = null;
            foreach (VoiceCandidate candidate in choice.Candidates)
                if (candidate.Choice == number)
                    picked = candidate;
            if (picked == null)
            {
                turn.Prompts.Add(Prompt.AskChoice);
                return;
            }
            PendingChoice asked = choice;
            EndChoice(turn);
            RunCandidate(asked.Resolution, picked, asked.Target, turn);
        }

        /// <summary>The <c>voice.run</c> command for one of the host's candidates.</summary>
        void RunCandidate(string resolution, VoiceCandidate candidate, SceneObject target, Turn turn)
        {
            if (candidate.NeedsTarget && target != null && Find(target.Id) == null)
            {
                turn.Prompts.Add(Prompt.TargetDeleted);
                return;
            }
            // Without a target the host answers with its own reason, which the app shows.
            SceneObject actual = candidate.TargetId == null ? target : Find(candidate.TargetId);
            if (candidate.TargetId != null && actual == null) { turn.Prompts.Add(Prompt.TargetDeleted); return; }
            turn.Command = new VoiceCommand(resolution, candidate, candidate.NeedsTarget ? actual : null);
        }

        void EndChoice(Turn turn)
        {
            if (choice == null)
                return;
            choice = null;
            turn.GrammarChanged = true;
        }

        /// <summary>VoiceCore's own handling of an utterance, as without a host.</summary>
        void HearHere(RecognitionResult result, Turn turn)
        {
            if (result.Confidence < options.MinConfidence)
            {
                turn.Prompts.Add(Prompt.LowConfidence);
                return;
            }

            ParsedUtterance parsed = CommandParser.Parse(result.Text, objects, pending?.Kind);
            if (parsed.ConflictingVerbs)
            {
                // Two commands in one transcript is a mishearing (or two requests at once): treated as low confidence.
                turn.Prompts.Add(Prompt.LowConfidence);
                return;
            }
            if (parsed.Verb == CommandKind.Cancel)
            {
                if (pending == null)
                    turn.Command = new VoiceCommand(CommandKind.Cancel, null, null, null, null, null);
                else
                {
                    pending = null;
                    turn.Prompts.Add(Prompt.Cancelled);
                }
                return;
            }

            if (pending != null)
            {
                bool answersTarget = parsed.Verb == CommandKind.Select && (pending.Missing & MissingFields.Target) != 0;
                if (parsed.Verb == null || answersTarget || parsed.Verb == CommandKind.Apply)
                {
                    Fill(parsed, turn);
                    return;
                }
                // A new command never completes the old one.
                pending = null;
                turn.Prompts.Add(Prompt.ReplacedPending);
            }

            if (parsed.Verb == null)
                turn.Prompts.Add(Prompt.Unsupported);
            else
                Start(parsed, turn);
        }

        void Start(ParsedUtterance parsed, Turn turn)
        {
            CommandKind kind = parsed.Verb.Value;
            if (kind == CommandKind.Undo || kind == CommandKind.Redo || kind == CommandKind.Apply)
            {
                turn.Command = new VoiceCommand(kind, null, null, null, null, null);
                return;
            }

            var draft = new Draft(kind) { Shape = parsed.Shape, Axis = parsed.Axis, NegativeAxis = parsed.NegativeAxis };
            if (parsed.Number.HasValue)
                draft.SetAmount(parsed.Number.Value, parsed.NegativeAmount, parsed.Unit, turn);
            else if (parsed.Unit.HasValue)
                draft.SetUnit(parsed.Unit.Value, turn);

            if (Vocabulary.IsTargetable(kind))
            {
                if (parsed.Target == TargetRef.Named)
                    draft.Target = parsed.Named;
                else if (parsed.Target == TargetRef.Ambiguous)
                    turn.Prompts.Add(Prompt.AmbiguousName);
                else if (parsed.Target == TargetRef.Unknown)
                    turn.Prompts.Add(Prompt.UnknownObject);
                else
                    draft.Target = FromContext(kind);
            }

            pending = draft;
            pendingSince = clock();
            Advance(turn);
        }

        /// <summary>Applies an utterance without a verb ("z", "ten centimeters", "the cube") to the pending command.
        /// Only missing fields are filled; anything already known is kept.</summary>
        void Fill(ParsedUtterance parsed, Turn turn)
        {
            Draft draft = pending;
            MissingFields missing = draft.Missing;
            bool needsTarget = (missing & MissingFields.Target) != 0;

            if (needsTarget && parsed.Target == TargetRef.Named)
                draft.Target = parsed.Named;
            else if (parsed.HasUnknownWords)
            {
                if (needsTarget)
                    turn.Prompts.Add(Prompt.UnknownObject);
                Advance(turn);
                return;
            }
            else if (needsTarget && parsed.Target == TargetRef.Ambiguous)
                turn.Prompts.Add(Prompt.AmbiguousName);
            else if (needsTarget && parsed.Target == TargetRef.Context)
                draft.Target = FromContext(draft.Kind);

            if ((missing & MissingFields.Shape) != 0 && parsed.Shape.HasValue)
                draft.Shape = parsed.Shape;
            if ((missing & MissingFields.Axis) != 0 && parsed.Axis.HasValue)
            {
                draft.Axis = parsed.Axis;
                draft.NegativeAxis = parsed.NegativeAxis; // "negative z"
            }
            else if (parsed.Axis.HasValue && parsed.Axis == draft.Axis && parsed.NegativeAxis)
                draft.NegativeAxis = true; // the known axis restated as "negative x"
            if ((missing & MissingFields.Amount) != 0 && parsed.Number.HasValue)
                draft.SetAmount(parsed.Number.Value, parsed.NegativeAmount, parsed.Unit, turn); // "minus ten centimeters"
            else
            {
                if (parsed.Number.HasValue && parsed.Number == draft.Magnitude && parsed.NegativeAmount)
                    draft.NegativeAmount = true; // the known amount restated as "minus ten"
                if ((missing & MissingFields.Unit) != 0 && parsed.Unit.HasValue)
                    draft.SetUnit(parsed.Unit.Value, turn);
            }

            Advance(turn);
        }

        /// <summary>Emits the command if complete, otherwise asks for the first missing field.</summary>
        void Advance(Turn turn)
        {
            Draft draft = pending;
            if (!draft.InRange())
            {
                draft.ClearAmount(); // the corrected amount comes with its own unit and sign
                turn.Prompts.Add(Prompt.OutOfRange);
            }
            MissingFields missing = draft.Missing;
            if (missing == MissingFields.None)
            {
                turn.Command = draft.ToCommand();
                pending = null;
                return;
            }
            expiresAt = clock() + options.PendingTimeout;
            turn.Asked = true;
            turn.Prompts.Add(Question(draft, missing));
        }

        static Prompt Question(Draft draft, MissingFields missing)
        {
            if ((missing & MissingFields.Shape) != 0) return Prompt.AskShape;
            if ((missing & MissingFields.Target) != 0) return Prompt.AskTarget;
            if ((missing & MissingFields.Axis) != 0) return Prompt.AskAxis;
            if ((missing & MissingFields.Amount) != 0)
                return draft.Kind == CommandKind.Move ? Prompt.AskDistance : draft.Kind == CommandKind.Rotate ? Prompt.AskAngle : Prompt.AskFactor;
            return Prompt.AskUnit;
        }

        /// <summary>Explicit selection first, then the pointer target, then the only eligible object. A selection is
        /// never overridden: several objects, or one that isn't eligible, is a question.</summary>
        SceneObject FromContext(CommandKind kind)
        {
            if (kind != CommandKind.Select && selection.Count > 0)
                return SingleSelected();
            SceneObject pointed = pointerId == null ? null : Find(pointerId);
            if (pointed != null)
                return pointed;
            return objects.Count == 1 ? objects[0] : null;
        }

        /// <summary>A pointer that came to rest on an object after the question answers it.</summary>
        void FillFromPointer(Turn turn)
        {
            ResumeCompositionTarget(turn, true);
            if (pending == null || (pending.Missing & MissingFields.Target) == 0 || pointerId == null)
                return;
            SceneObject pointed = Find(pointerId);
            DateTime now = clock();
            if (pointed != null && pointerSince >= pendingSince && now - pointerSince >= options.PointerDwell)
            {
                pending.Target = pointed;
                Advance(turn);
            }
        }

        /// <summary>The selected object if exactly one is selected and it is eligible, otherwise null.</summary>
        SceneObject SingleSelected()
        {
            SceneObject found = null;
            foreach (string id in selection)
            {
                SceneObject obj = Find(id);
                if (obj == null || (found != null && found.Id != obj.Id))
                    return null;
                found = obj;
            }
            return found;
        }

        SceneObject Find(string id)
        {
            foreach (SceneObject obj in objects)
                if (obj.Id == id)
                    return obj;
            return null;
        }

        /// <summary>Starts handling an input; an expired pending command or host question is dropped first.</summary>
        Turn Begin()
        {
            var turn = new Turn();
            if (compositionToken != null && clock() >= compositionExpires) CancelComposition(turn, Prompt.TimedOut);
            if (pending != null && clock() >= expiresAt)
            {
                pending = null;
                turn.Prompts.Add(Prompt.TimedOut);
            }
            if (choice != null && clock() >= choice.ExpiresAt)
            {
                EndChoice(turn);
                turn.Prompts.Add(Prompt.TimedOut);
            }
            return turn;
        }

        sealed class Turn
        {
            public VoiceCommand Command;
            public readonly List<Prompt> Prompts = new List<Prompt>();
            public VoiceResolve Resolve;
            public bool GrammarChanged;
            public string HostReason;
            public NoResultReason? NoResult;
            public bool ChoiceDismissed;
            public bool Asked; // a new question: cancels a delete waiting for its confirmation
            public VoiceTurn Build() => new VoiceTurn(Command, Prompts, Resolve, GrammarChanged, HostReason, NoResult, ChoiceDismissed, Asked);
        }

        /// <summary>Words sent to the host, kept to be handled as without a host if it can't help.</summary>
        sealed class Resolving
        {
            public Resolving(VoiceResolve request, RecognitionResult result, SceneObject target, DateTime sentAt)
            {
                Request = request;
                Result = result;
                Target = target;
                SentAt = sentAt;
            }

            public readonly VoiceResolve Request;
            public readonly RecognitionResult Result;
            public readonly SceneObject Target;
            public readonly DateTime SentAt;
            public string MessageId;
            public bool ShapeWithoutVerb; // a run of these words only asks
        }

        /// <summary>A command being assembled, with the number and unit as spoken.</summary>
        sealed class Draft
        {
            public Draft(CommandKind kind) => Kind = kind;

            public readonly CommandKind Kind;
            public SceneObject Target;
            public Shape? Shape;
            public Axis? Axis;
            public double? Magnitude;
            public SpokenUnit? Unit;
            public bool NegativeAmount, NegativeAxis;

            bool HasAmount => Kind == CommandKind.Move || Kind == CommandKind.Rotate || Kind == CommandKind.Scale;

            public MissingFields Missing
            {
                get
                {
                    var missing = MissingFields.None;
                    if (Kind == CommandKind.AddShape && !Shape.HasValue)
                        missing |= MissingFields.Shape;
                    if (Vocabulary.IsTargetable(Kind) && Target == null)
                        missing |= MissingFields.Target;
                    if ((Kind == CommandKind.Move || Kind == CommandKind.Rotate) && !Axis.HasValue)
                        missing |= MissingFields.Axis;
                    if (HasAmount && !Magnitude.HasValue)
                        missing |= MissingFields.Amount;
                    if (Kind == CommandKind.Move && !Unit.HasValue)
                        missing |= MissingFields.Unit;
                    return missing;
                }
            }

            /// <summary>Sets the number, its sign and its unit, or explains a wrong unit.</summary>
            public void SetAmount(double magnitude, bool negative, SpokenUnit? unit, Turn turn)
            {
                if (!HasAmount || (unit.HasValue && !SetUnit(unit.Value, turn)))
                    return;
                if (Kind == CommandKind.Rotate)
                    Unit = SpokenUnit.Degrees;
                else if (Kind == CommandKind.Scale && !Unit.HasValue)
                    Unit = SpokenUnit.Times;
                Magnitude = magnitude;
                NegativeAmount = negative;
            }

            public void ClearAmount()
            {
                Magnitude = null;
                Unit = null;
                NegativeAmount = false;
            }

            public bool SetUnit(SpokenUnit unit, Turn turn)
            {
                bool ok = Kind == CommandKind.Move ? VoiceCommand.IsDistance(unit)
                    : Kind == CommandKind.Rotate ? unit == SpokenUnit.Degrees
                    : Kind == CommandKind.Scale && (unit == SpokenUnit.Percent || unit == SpokenUnit.Times);
                if (ok)
                    Unit = unit;
                else if (HasAmount)
                    turn.Prompts.Add(Kind == CommandKind.Move ? Prompt.WrongUnitDistance
                        : Kind == CommandKind.Rotate ? Prompt.WrongUnitAngle : Prompt.WrongUnitFactor);
                return ok;
            }

            /// <summary>The voice limits (<see cref="VoiceLimits"/>), inside the contract's bounds.</summary>
            public bool InRange()
            {
                VoiceCommand command = ToCommand();
                if (command.Meters.HasValue)
                    return command.Meters != 0 && Math.Abs(command.Meters.Value) <= VoiceLimits.MaxMoveMeters;
                if (command.Radians.HasValue)
                    return command.Amount != 0 && Math.Abs(command.Amount.Value) <= VoiceLimits.MaxTurnDegrees;
                if (command.Factor.HasValue)
                    return command.Factor >= VoiceLimits.MinScaleFactor && command.Factor <= VoiceLimits.MaxScaleFactor;
                return true;
            }

            public VoiceCommand ToCommand() =>
                new VoiceCommand(Kind, Target, Shape, Axis, Magnitude.HasValue ? (NegativeAmount != NegativeAxis ? -Magnitude : Magnitude) : null, Unit);
        }
    }
}
