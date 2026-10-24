using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    public sealed class VoiceSessionOptions
    {
        /// <summary>Results below this confidence are rejected and never produce a command. Provisional: chosen
        /// from TTS samples in the Vosk spike; recalibrate with the Quest microphone.</summary>
        public float MinConfidence { get; set; } = 0.5f;

        /// <summary>A pending command is dropped this long after its last question.</summary>
        public TimeSpan PendingTimeout { get; set; } = TimeSpan.FromSeconds(30);

        /// <summary>The pointer must rest this long on an object before it answers "which object?".</summary>
        public TimeSpan PointerDwell { get; set; } = TimeSpan.FromSeconds(0.5);
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
        internal VoiceTurn(VoiceCommand command, IReadOnlyList<Prompt> prompts)
        {
            Command = command;
            Prompts = prompts;
        }

        /// <summary>A complete command to send through the normal command path, or null.</summary>
        public VoiceCommand Command { get; }

        public IReadOnlyList<Prompt> Prompts { get; }

        public override string ToString() =>
            (Command == null ? "no command" : Command.ToString()) + (Prompts.Count == 0 ? "" : " [" + string.Join(", ", Prompts) + "]");
    }

    /// <summary>
    /// Voice conversation memory: turns recognized utterances plus selection and pointer events into complete
    /// commands, asking only for what is missing. It keeps at most one pending command.
    /// Not thread-safe: call it from the Unity main thread, and call <see cref="Tick"/> every frame.
    /// </summary>
    public sealed class VoiceSession
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

        /// <summary>
        /// The recognizer grammar for the current objects. Pass it to <see cref="ISpeechRecognizer.SetGrammar"/>
        /// at startup and after every <see cref="SetObjects"/>.
        /// </summary>
        public IReadOnlyList<string> GrammarPhrases()
        {
            var names = new List<string>();
            foreach (SceneObject obj in objects)
                names.Add(obj.Name);
            return Vocabulary.GrammarPhrases(names);
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
            return turn.Build();
        }

        /// <summary>The user's current selection. A single selected object answers "which object?".</summary>
        public VoiceTurn SetSelection(IEnumerable<string> selectedIds)
        {
            var turn = Begin();
            selection.Clear();
            selection.AddRange(selectedIds);
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
            if (pending != null)
            {
                pending = null;
                turn.Prompts.Add(Prompt.DocumentChanged);
            }
            objects = new List<SceneObject>();
            selection.Clear();
            pointerId = null;
            return turn.Build();
        }

        /// <summary>The host connection closed (the app's Disconnected state): drops the pending command. The objects
        /// stay until the fresh snapshot's <see cref="SetObjects"/>, or <see cref="DocumentChanged"/>.</summary>
        public VoiceTurn ConnectionLost()
        {
            var turn = Begin();
            if (pending != null)
            {
                pending = null;
                turn.Prompts.Add(Prompt.ConnectionLost);
            }
            return turn.Build();
        }

        /// <summary>The UI's Cancel button for the pending command.</summary>
        public VoiceTurn Cancel()
        {
            var turn = Begin();
            if (pending != null)
            {
                pending = null;
                turn.Prompts.Add(Prompt.Cancelled);
            }
            return turn.Build();
        }

        /// <summary>While a prompt plays, results are ignored so the app can't hear itself. Pause
        /// <see cref="VoiceInput"/> at the same time, so no utterance spans the prompt.</summary>
        public void SetPromptPlaying(bool playing) => promptPlaying = playing;

        /// <summary>Expires the pending command and lets a resting pointer answer "which object?".</summary>
        public VoiceTurn Tick()
        {
            var turn = Begin();
            FillFromPointer(turn);
            return turn.Build();
        }

        /// <summary>Handles one final recognized utterance.</summary>
        public VoiceTurn Hear(RecognitionResult result)
        {
            var turn = Begin();
            if (promptPlaying || string.IsNullOrWhiteSpace(result.Text))
                return turn.Build();
            if (result.Confidence < options.MinConfidence)
            {
                turn.Prompts.Add(Prompt.LowConfidence);
                return turn.Build();
            }

            ParsedUtterance parsed = CommandParser.Parse(result.Text, objects, pending?.Kind);
            if (parsed.Verb == CommandKind.Cancel)
            {
                if (pending == null)
                    turn.Command = new VoiceCommand(CommandKind.Cancel, null, null, null, null, null);
                else
                {
                    pending = null;
                    turn.Prompts.Add(Prompt.Cancelled);
                }
                return turn.Build();
            }

            if (pending != null)
            {
                bool answersTarget = parsed.Verb == CommandKind.Select && (pending.Missing & MissingFields.Target) != 0;
                if (parsed.Verb == null || answersTarget || parsed.Verb == CommandKind.Apply)
                {
                    Fill(parsed, turn);
                    return turn.Build();
                }
                // A new command never completes the old one.
                pending = null;
                turn.Prompts.Add(Prompt.ReplacedPending);
            }

            if (parsed.Verb == null)
                turn.Prompts.Add(Prompt.Unsupported);
            else
                Start(parsed, turn);
            return turn.Build();
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
            if ((missing & MissingFields.Amount) != 0 && parsed.Number.HasValue)
                draft.SetAmount(parsed.Number.Value, parsed.NegativeAmount, parsed.Unit, turn); // "minus ten centimeters"
            else if ((missing & MissingFields.Unit) != 0 && parsed.Unit.HasValue)
                draft.SetUnit(parsed.Unit.Value, turn);

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

        /// <summary>Starts handling an input; an expired pending command is dropped first.</summary>
        Turn Begin()
        {
            var turn = new Turn();
            if (pending != null && clock() >= expiresAt)
            {
                pending = null;
                turn.Prompts.Add(Prompt.TimedOut);
            }
            return turn;
        }

        sealed class Turn
        {
            public VoiceCommand Command;
            public readonly List<Prompt> Prompts = new List<Prompt>();
            public VoiceTurn Build() => new VoiceTurn(Command, Prompts);
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
