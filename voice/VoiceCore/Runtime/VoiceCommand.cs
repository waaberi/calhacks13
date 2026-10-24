using System;
using System.Globalization;

namespace SpatialModeling.VoiceCore
{
    public enum CommandKind { AddShape, Select, Move, Rotate, Scale, Delete, Undo, Redo, Apply, Cancel }

    public enum Shape { Cube, Sphere, Cylinder }

    /// <summary>Blender world axes: right-handed, Z up.</summary>
    public enum Axis { X, Y, Z }

    /// <summary>The unit as spoken. Use <see cref="VoiceCommand.Meters"/>, <see cref="VoiceCommand.Radians"/>
    /// and <see cref="VoiceCommand.Factor"/> for wire values.</summary>
    public enum SpokenUnit { Millimeters, Centimeters, Meters, Degrees, Percent, Times }

    /// <summary>An object the user can refer to: visible in VR and eligible for editing.</summary>
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

        public CommandKind Kind { get; }

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
