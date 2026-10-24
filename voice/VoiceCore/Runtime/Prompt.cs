using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// Something VoiceCore wants the user to hear and read. <see cref="Id"/> is stable, so the UI can map it
    /// to a prerecorded clip; <see cref="Text"/> is the matching English line.
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
        public static readonly Prompt DocumentChanged = new Prompt("document_changed", "The document changed, so I cancelled the unfinished command.");
        public static readonly Prompt TargetDeleted = new Prompt("target_deleted", "That object is gone, so I cancelled the command.");
        public static readonly Prompt UnknownObject = new Prompt("unknown_object", "I couldn't find an object with that name.");
        public static readonly Prompt AmbiguousName = new Prompt("ambiguous_name", "More than one object has that name.");
        public static readonly Prompt WrongUnitDistance = new Prompt("wrong_unit_distance", "Move needs a distance in millimeters, centimeters or meters.");
        public static readonly Prompt WrongUnitAngle = new Prompt("wrong_unit_angle", "Rotate needs an angle in degrees.");
        public static readonly Prompt WrongUnitFactor = new Prompt("wrong_unit_factor", "Scale needs a factor, like two times or fifty percent.");
        public static readonly Prompt OutOfRange = new Prompt("out_of_range", "That amount is out of range.");

        /// <summary>Every prompt, for generating or checking audio clips.</summary>
        public static IReadOnlyList<Prompt> All { get; } = new[]
        {
            AskShape, AskTarget, AskAxis, AskDistance, AskAngle, AskFactor, AskUnit,
            LowConfidence, Unsupported, Cancelled, TimedOut, ReplacedPending, DocumentChanged, TargetDeleted,
            UnknownObject, AmbiguousName, WrongUnitDistance, WrongUnitAngle, WrongUnitFactor, OutOfRange,
        };
    }
}
