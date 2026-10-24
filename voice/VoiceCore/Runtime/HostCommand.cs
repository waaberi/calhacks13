using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// A complete voice command as the contract's <c>command</c> fields <c>op</c>, <c>target</c> and <c>args</c>
    /// (contracts/README.md, Commands), in meters and radians on Blender's axes. The sender adds the request fields
    /// from <c>welcome</c>, <c>base_revision</c>, <c>source</c> <see cref="Source"/> and the target's current
    /// <c>generation</c>. Plain data: <see cref="Args"/> holds strings, doubles, double arrays and nested
    /// dictionaries, so <c>JObject.FromObject(Args)</c> turns it into JSON.
    /// </summary>
    public sealed class HostCommand
    {
        /// <summary>The command's <c>source</c>.</summary>
        public const string Source = "voice";

        /// <summary>Box size of a voice "add", in meters, when the app doesn't pass one.</summary>
        public const double DefaultAddSize = 0.05;

        // The contract's bounds (contracts/schemas/envelope.schema.json and command.schema.json).
        internal const double MaxCoordinate = 1000, MinLength = 0.000001, MaxLength = 1000;
        internal const double MinFactor = 0.001, MaxFactor = 1000, MaxAngle = 6.283186;

        HostCommand(string op, string targetId, Dictionary<string, object> args)
        {
            Op = op;
            TargetId = targetId;
            Args = args;
        }

        /// <summary>For example <c>object.rotate</c>.</summary>
        public string Op { get; }

        /// <summary>The target object's ID, or null for an op without a target (object.add, history.undo, history.redo).</summary>
        public string TargetId { get; }

        /// <summary>The op's <c>args</c>; empty for object.delete, history.undo and history.redo.</summary>
        public IReadOnlyDictionary<string, object> Args { get; }

        /// <summary>
        /// The host command for a complete <see cref="VoiceTurn.Command"/>, or null for Select, Apply and Cancel, which the
        /// app handles itself. Ask for the deliberate confirmation of a Delete (<see cref="VoiceCommand.RequiresConfirmation"/>)
        /// before sending it.
        /// </summary>
        /// <param name="addLocation">AddShape: where the new object's center goes, in Blender world meters, for example
        /// where the pointer meets the table. Defaults to the world origin.</param>
        /// <param name="addDimensions">AddShape: its bounding box in meters. Defaults to <see cref="DefaultAddSize"/> each way.</param>
        public static HostCommand From(VoiceCommand command, double[] addLocation = null, double[] addDimensions = null)
        {
            if (command == null)
                throw new ArgumentNullException(nameof(command));
            var args = new Dictionary<string, object>();
            switch (command.Kind)
            {
                case CommandKind.Select:
                case CommandKind.Apply:
                case CommandKind.Cancel:
                    return null;
                case CommandKind.Undo:
                    return new HostCommand("history.undo", null, args);
                case CommandKind.Redo:
                    return new HostCommand("history.redo", null, args);
                case CommandKind.AddShape:
                    args["primitive"] = Require(command.Shape, command).ToString().ToLowerInvariant();
                    args["location"] = Vector(addLocation ?? new double[3], -MaxCoordinate, MaxCoordinate, nameof(addLocation));
                    args["dimensions"] = Vector(addDimensions ?? new[] { DefaultAddSize, DefaultAddSize, DefaultAddSize },
                        MinLength, MaxLength, nameof(addDimensions));
                    return new HostCommand("object.add", null, args);
            }

            string target = command.TargetId ?? throw Incomplete(command);
            switch (command.Kind)
            {
                case CommandKind.Move:
                    var by = new double[3];
                    by[(int)Require(command.Axis, command)] = Require(command.Meters, command);
                    args["by"] = Vector(by, -MaxCoordinate, MaxCoordinate, nameof(command));
                    return new HostCommand("object.move", target, args);
                case CommandKind.Rotate:
                    args["by"] = new Dictionary<string, object>
                    {
                        { "axis", Require(command.Axis, command).ToString() },
                        { "angle", Number(Require(command.Radians, command), -MaxAngle, MaxAngle, nameof(command)) },
                    };
                    return new HostCommand("object.rotate", target, args);
                case CommandKind.Scale:
                    double f = Require(command.Factor, command);
                    args["by"] = Vector(new[] { f, f, f }, MinFactor, MaxFactor, nameof(command));
                    return new HostCommand("object.scale", target, args);
                case CommandKind.Delete:
                    return new HostCommand("object.delete", target, args);
                default:
                    throw new ArgumentException("No host op for " + command.Kind, nameof(command));
            }
        }

        /// <summary>
        /// What to say about the host's answer to a voice command: a <c>result</c>'s <c>outcome</c> and <c>error.code</c>,
        /// or (outcome null) the <c>code</c> of an <c>error</c> reply whose <c>re</c> is the command. Show the receipt's
        /// <c>summary</c> or the host's error <c>message</c> next to it.
        /// </summary>
        public static Prompt PromptFor(string op, string outcome, string errorCode)
        {
            if (outcome == "applied")
                return Prompt.Done;
            if (outcome == "unknown")
                return Prompt.OutcomeUnknown;
            switch (errorCode)
            {
                case "lease_conflict": return Prompt.Locked;
                case "stale_revision": return Prompt.Changed;
                case "not_found": return Prompt.TargetDeleted;
                case "invalid_message": return Prompt.OutOfRange; // the schema bounds are the host's range check
                case "permission_denied": return Prompt.ReadOnly;
                case "wrong_session":
                case "wrong_document": return Prompt.DocumentChanged;
                case "busy": return Prompt.Busy;
                case "internal_error": return Prompt.OutcomeUnknown; // the contract treats it as an unknown outcome
                case "failed":
                    return op == "history.undo" ? Prompt.NothingToUndo : op == "history.redo" ? Prompt.NothingToRedo : Prompt.Failed;
                default: return Prompt.Failed;
            }
        }

        static T Require<T>(T? value, VoiceCommand command) where T : struct => value ?? throw Incomplete(command);

        static ArgumentException Incomplete(VoiceCommand command) =>
            new ArgumentException("Incomplete voice command: " + command, nameof(command));

        /// <summary>A copy of three numbers within the contract's bounds.</summary>
        static double[] Vector(double[] values, double min, double max, string name)
        {
            if (values.Length != 3)
                throw new ArgumentException("Expected [x, y, z]", name);
            foreach (double v in values)
                Number(v, min, max, name);
            return (double[])values.Clone();
        }

        static double Number(double value, double min, double max, string name) =>
            value >= min && value <= max ? value
                : throw new ArgumentOutOfRangeException(name, value, "Outside the contract's bounds " + min + " to " + max);
    }
}
