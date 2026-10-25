using System;
using System.Globalization;

namespace SpatialModeling.VoiceCore
{
    /// <summary>What a voice command does. <see cref="Run"/> is a Blender operation the host resolved from the words
    /// (<c>voice.resolve</c>): the command runs the host's own candidate, and never names an operator itself.</summary>
    public enum CommandKind { AddShape, Select, Move, Rotate, Scale, Delete, Undo, Redo, Apply, Cancel, Run }

    public enum Shape { Cube, Sphere, Cylinder }

    /// <summary>Blender world axes: right-handed, Z up.</summary>
    public enum Axis { X, Y, Z }

    /// <summary>The unit as spoken. Use <see cref="VoiceCommand.Meters"/>, <see cref="VoiceCommand.Radians"/>
    /// and <see cref="VoiceCommand.Factor"/> for wire values.</summary>
    public enum SpokenUnit { Millimeters, Centimeters, Meters, Degrees, Percent, Times }

    /// <summary>
    /// The amounts voice accepts. Tighter than the contract's bounds (<see cref="HostCommand"/>), so a misheard
    /// "nine hundred" can't send a huge edit; anything outside them is <see cref="Prompt.OutOfRange"/>.
    /// </summary>
    public static class VoiceLimits
    {
        /// <summary>Moves are nonzero and up to this distance.</summary>
        public const double MaxMoveMeters = 10;

        /// <summary>Turns are nonzero and up to one full turn.</summary>
        public const double MaxTurnDegrees = 360;

        public const double MinScaleFactor = 0.01;
        public const double MaxScaleFactor = 100;
    }

    /// <summary>
    /// An object the user can refer to: one the VR app shows (in the scene with <c>visible</c> true and a
    /// <c>mesh</c>). <see cref="Id"/> is the contract's object <c>id</c>.
    /// </summary>
    public sealed class SceneObject
    {
        public SceneObject(string id, string name)
        {
            Id = id ?? throw new ArgumentNullException(nameof(id));
            Name = name ?? "";
        }

        /// <summary>Stable object ID (the UUID custom property in Blender).</summary>
        public string Id { get; }

        /// <summary>Visible name, used for "select the cube".</summary>
        public string Name { get; }
    }

    /// <summary>
    /// A voice command. Complete commands come out of <see cref="VoiceSession"/> in <see cref="VoiceTurn.Command"/>;
    /// a pending command uses the same type with the missing fields left null.
    /// </summary>
    public sealed class VoiceCommand
    {
        internal VoiceCommand(CommandKind kind, SceneObject target, Shape? shape, Axis? axis, double? amount, SpokenUnit? unit)
        {
            Kind = kind;
            TargetId = target?.Id;
            TargetName = target?.Name;
            Shape = shape;
            Axis = axis;
            Amount = amount;
            Unit = unit;
        }

        /// <summary>A <see cref="CommandKind.Run"/> of the host's candidate.</summary>
        internal VoiceCommand(string resolution, VoiceCandidate candidate, SceneObject target)
            : this(CommandKind.Run, target, null, null, null, null)
        {
            Resolution = resolution;
            Choice = candidate.Choice;
            Say = candidate.Say;
        }

        public CommandKind Kind { get; }

        /// <summary>Run only: the host's <c>resolution</c> ID from <c>voice.candidates</c>.</summary>
        public string Resolution { get; }

        /// <summary>Run only: the chosen candidate's <c>choice</c>, 1 to 3.</summary>
        public int Choice { get; }

        /// <summary>Run only: what the operation is called, for display ("Subdivision Surface").</summary>
        public string Say { get; }

        /// <summary>Stable object ID. Set for Select, Move, Rotate, Scale and Delete; null otherwise.</summary>
        public string TargetId { get; }

        /// <summary>The target's visible name, for display.</summary>
        public string TargetName { get; }

        /// <summary>AddShape only.</summary>
        public Shape? Shape { get; }

        /// <summary>Move and Rotate only.</summary>
        public Axis? Axis { get; }

        /// <summary>The signed number as spoken, in <see cref="Unit"/>. For display; send the normalized values.</summary>
        public double? Amount { get; }

        public SpokenUnit? Unit { get; }

        /// <summary>Move: signed distance along <see cref="Axis"/> in meters.</summary>
        public double? Meters => Kind == CommandKind.Move && Amount.HasValue && Unit.HasValue && IsDistance(Unit.Value)
            ? Amount.Value * MetersPer(Unit.Value)
            : (double?)null;

        /// <summary>Rotate: signed angle around <see cref="Axis"/> in radians (right-hand rule).</summary>
        public double? Radians => Kind == CommandKind.Rotate && Amount.HasValue && Unit == SpokenUnit.Degrees
            ? Amount.Value * Math.PI / 180.0
            : (double?)null;

        /// <summary>Scale: uniform factor relative to the current scale (50 percent is 0.5).</summary>
        public double? Factor => Kind == CommandKind.Scale && Amount.HasValue && Unit.HasValue
            ? (Unit == SpokenUnit.Percent ? Amount.Value / 100.0 : Unit == SpokenUnit.Times ? Amount.Value : (double?)null)
            : null;

        /// <summary>Destructive: the UI asks for a deliberate controller confirmation before sending.
        /// A spoken "yes" must not confirm it.</summary>
        public bool RequiresConfirmation => Kind == CommandKind.Delete;

        public override string ToString()
        {
            string target = TargetName ?? "?";
            string amount = Amount.HasValue ? Amount.Value.ToString("0.###", CultureInfo.InvariantCulture) : "?";
            string unit = Unit.HasValue ? " " + UnitText(Unit.Value) : Amount.HasValue ? " ?" : "";
            string axis = Axis.HasValue ? Axis.Value.ToString() : "?";
            switch (Kind)
            {
                case CommandKind.AddShape: return "Add " + (Shape.HasValue ? Shape.Value.ToString().ToLowerInvariant() : "?");
                case CommandKind.Move: return "Move " + target + " " + amount + unit + " along " + axis;
                case CommandKind.Rotate: return "Rotate " + target + " " + amount + unit + " around " + axis;
                case CommandKind.Scale: return "Scale " + target + " by " + amount + unit;
                case CommandKind.Select:
                case CommandKind.Delete: return Kind + " " + target;
                case CommandKind.Run: return Say + (TargetName == null ? "" : " on " + TargetName);
                default: return Kind.ToString();
            }
        }

        internal static bool IsDistance(SpokenUnit unit) =>
            unit == SpokenUnit.Millimeters || unit == SpokenUnit.Centimeters || unit == SpokenUnit.Meters;

        internal static double MetersPer(SpokenUnit unit) =>
            unit == SpokenUnit.Millimeters ? 0.001 : unit == SpokenUnit.Centimeters ? 0.01 : 1.0;

        static string UnitText(SpokenUnit unit)
        {
            switch (unit)
            {
                case SpokenUnit.Millimeters: return "mm";
                case SpokenUnit.Centimeters: return "cm";
                case SpokenUnit.Meters: return "m";
                case SpokenUnit.Degrees: return "degrees";
                case SpokenUnit.Percent: return "percent";
                default: return "times";
            }
        }
    }
}
