using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// Something VoiceCore wants the user to hear and read. <see cref="Id"/> is stable and names its prerecorded clip
    /// (<see cref="ClipResource"/>); <see cref="Text"/> is the matching English line. The spoken text is static: show
    /// details such as an owner's name or the host's message next to it on screen.
    /// </summary>
    public sealed class Prompt
    {
        Prompt(string id, string text)
        {
            Id = id;
            Text = text;
        }

        public string Id { get; }
        public string Text { get; }

        /// <summary>The clip's path for <c>Resources.Load&lt;AudioClip&gt;</c>, from the package's
        /// <c>Prompts/Resources/</c> folder (made by <c>voice/make-prompts.py</c>).</summary>
        public string ClipResource => "VoiceCorePrompts/" + Id;

        public override string ToString() => Id;

        // Questions about the single missing field of the pending command.
        public static readonly Prompt AskShape = new Prompt("ask_shape", "Which shape: cube, sphere or cylinder?");
        public static readonly Prompt AskTarget = new Prompt("ask_target", "Please select or point at the object you are referring to.");
        public static readonly Prompt AskAxis = new Prompt("ask_axis", "Which axis: X, Y or Z?");
        public static readonly Prompt AskDistance = new Prompt("ask_distance", "How far? For example, ten centimeters.");
        public static readonly Prompt AskAngle = new Prompt("ask_angle", "How many degrees?");
        public static readonly Prompt AskFactor = new Prompt("ask_factor", "By how much? For example, two times or fifty percent.");
        public static readonly Prompt AskUnit = new Prompt("ask_unit", "In millimeters, centimeters or meters?");

        // Notices. When a field is still missing, its question follows in the same turn.
        public static readonly Prompt LowConfidence = new Prompt("low_confidence", "Sorry, I didn't catch that. Please say it again.");
        public static readonly Prompt Unsupported = new Prompt("unsupported", "Sorry, I can't do that. Try: rotate this object ninety degrees around Z.");
        public static readonly Prompt Cancelled = new Prompt("cancelled", "Cancelled.");
        public static readonly Prompt TimedOut = new Prompt("timed_out", "The unfinished command timed out.");
        public static readonly Prompt ReplacedPending = new Prompt("replaced_pending", "I dropped the unfinished command.");
        public static readonly Prompt DocumentChanged = new Prompt("document_changed", "The document changed, so I cancelled the command.");
        public static readonly Prompt ConnectionLost = new Prompt("connection_lost", "I lost the connection to Blender, so I cancelled the command.");
        public static readonly Prompt TargetDeleted = new Prompt("target_deleted", "That object is gone, so I cancelled the command.");
        public static readonly Prompt UnknownObject = new Prompt("unknown_object", "I couldn't find an object with that name.");
        public static readonly Prompt AmbiguousName = new Prompt("ambiguous_name", "More than one object has that name.");
        public static readonly Prompt WrongUnitDistance = new Prompt("wrong_unit_distance", "Move needs a distance in millimeters, centimeters or meters.");
        public static readonly Prompt WrongUnitAngle = new Prompt("wrong_unit_angle", "Rotate needs an angle in degrees.");
        public static readonly Prompt WrongUnitFactor = new Prompt("wrong_unit_factor", "Scale needs a factor, like two times or fifty percent.");
        public static readonly Prompt OutOfRange = new Prompt("out_of_range", "That amount is out of range.");

        // Sending a complete command and the host's answer (HostCommand.PromptFor).
        public static readonly Prompt ConfirmDelete = new Prompt("confirm_delete", "Please confirm the delete on your controller.");
        public static readonly Prompt NotConnected = new Prompt("not_connected", "Blender isn't connected, so nothing changed.");
        public static readonly Prompt Done = new Prompt("done", "Done.");
        public static readonly Prompt Locked = new Prompt("locked", "Someone else is editing that right now.");
        public static readonly Prompt Changed = new Prompt("changed", "That changed in the meantime. Please check it and try again.");
        public static readonly Prompt ReadOnly = new Prompt("read_only", "You can't edit right now.");
        public static readonly Prompt Busy = new Prompt("busy", "Blender is busy. Please try again.");
        public static readonly Prompt NothingToUndo = new Prompt("nothing_to_undo", "There is nothing to undo.");
        public static readonly Prompt NothingToRedo = new Prompt("nothing_to_redo", "There is nothing to redo.");
        public static readonly Prompt Failed = new Prompt("failed", "Blender couldn't do that.");
        public static readonly Prompt OutcomeUnknown = new Prompt("outcome_unknown", "I'm not sure that worked. Please check the model.");

        /// <summary>Every prompt, for generating or checking audio clips.</summary>
        public static IReadOnlyList<Prompt> All { get; } = new[]
        {
            AskShape, AskTarget, AskAxis, AskDistance, AskAngle, AskFactor, AskUnit,
            LowConfidence, Unsupported, Cancelled, TimedOut, ReplacedPending, DocumentChanged, ConnectionLost, TargetDeleted,
            UnknownObject, AmbiguousName, WrongUnitDistance, WrongUnitAngle, WrongUnitFactor, OutOfRange,
            ConfirmDelete, NotConnected, Done, Locked, Changed, ReadOnly, Busy, NothingToUndo, NothingToRedo, Failed, OutcomeUnknown,
        };
    }
}
