using System;
using System.Globalization;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // Local numeric draft only. The shared native session still owns every
    // permission, generation, receipt, history entry and actual transmission.
    public sealed class NativeNumericTools : IDisposable
    {
        readonly NativeEditSession session;
        readonly NativeObjectTools objects;
        readonly string[] text = { "0", "0", "0" };
        string identity = "", target = "";
        long revision, generation;
        bool loaded, invalid, replace = true;
        public string Mode { get; private set; } = "move";
        public int Axis { get; private set; }
        public string Notice { get; private set; } = "Choose a numeric operation";
        public string Unit => Mode == "rotation" ? "degrees, native Euler XYZ" : Mode.StartsWith("scale", StringComparison.Ordinal) ? "scale factors" : "millimeters, native world XYZ";
        public string Value(int axis) => text[axis];
        public bool IsCurrent { get { Observe(); return loaded && !invalid; } }
        public NativeNumericTools(NativeEditSession session, NativeObjectTools objects)
        { this.session = session; this.objects = objects; session.Changed += Observe; }
        public void Dispose() => session.Changed -= Observe;
        string Identity() => session.RequestIdentity?.ToString(Newtonsoft.Json.Formatting.None) ?? "";
        bool Creation => Mode.StartsWith("add.", StringComparison.Ordinal);
        public void Invalidate(string reason = null) { if (loaded) { invalid = true; Notice = reason ?? "Native context changed; reload before applying"; } }
        void Observe()
        {
            if (!loaded || invalid) return;
            if (!session.Ready || !session.SceneCurrent || identity != Identity() || revision != session.Revision
                || (!Creation && (target != objects.TargetId || !objects.TargetAvailable
                    || !session.Objects.TryGetValue(target, out var record) || (long?)record["generation"] != generation))) Invalidate();
        }
        public bool Load(string mode)
        {
            if (mode != "move" && mode != "position" && mode != "rotation" && mode != "scale.by" && mode != "scale.to"
                && mode != "add.cube" && mode != "add.sphere" && mode != "add.cylinder") return false;
            if (!session.Ready || !session.SceneCurrent || !session.CanEdit || session.Busy || session.OutcomeUnknown) return false;
            bool create = mode.StartsWith("add.", StringComparison.Ordinal);
            if (!create && !objects.TargetAvailable) { Notice = "Choose a current object target first"; return false; }
            double[] current = null;
            if ((mode == "position" || mode == "scale.to") && !TryVector(session.Objects[objects.TargetId]["transform"]?[mode == "position" ? "location" : "scale"], out current))
            { Notice = "Current native transform is unavailable; wait for a fresh scene record"; return false; }
            if (mode == "rotation" && (!TryVector(session.Objects[objects.TargetId]["transform"]?["rotation"], out var q, 4) || !ToEuler(q, out current)))
            { Notice = "Current native rotation is unavailable; wait for a fresh scene record"; return false; }
            Mode = mode; loaded = true; invalid = false; Axis = 0; replace = true;
            identity = Identity(); revision = session.Revision; target = create ? "" : objects.TargetId;
            generation = create ? 0 : (long)session.Objects[target]["generation"];
            for (int i = 0; i < 3; i++)
            {
                double value = create ? 50 : mode.StartsWith("scale", StringComparison.Ordinal) ? 1 : 0;
                if (mode == "position") value = current[i] * 1000;
                if (mode == "scale.to") value = current[i];
                if (mode == "rotation") value = current[i];
                text[i] = value.ToString("0.############", CultureInfo.InvariantCulture);
            }
            Notice = "Local draft · " + Unit + " · Apply changes Blender";
            return true;
        }
        public void SelectAxis(int axis) { if (axis >= 0 && axis < 3) { Axis = axis; replace = true; } }
        public void Enter(string key)
        {
            if (string.IsNullOrEmpty(key) || !IsCurrent || session.Busy) return;
            string value = text[Axis];
            if (key == "clear") value = "";
            else if (key == "back") value = value.Length == 0 ? "" : value.Substring(0, value.Length - 1);
            else if (key == "sign") value = value.StartsWith("-", StringComparison.Ordinal) ? value.Substring(1) : "-" + value;
            else if (key.Length == 1 && "0123456789.".IndexOf(key[0]) >= 0)
            {
                if (replace) value = "";
                if (key == "." && value.Contains(".")) return;
                if (value.Length >= 24) return;
                value += key == "." && (value.Length == 0 || value == "-") ? "0." : key;
            }
            else return;
            text[Axis] = value; replace = false;
        }
        public static bool Parse(string value, out double number) => double.TryParse(value,
            NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out number)
            && !double.IsNaN(number) && !double.IsInfinity(number);
        static bool TryVector(JToken value, out double[] numbers, int count = 3)
        {
            numbers = null;
            if (!(value is JArray array) || array.Count != count) return false;
            var result = new double[count];
            for (int i = 0; i < count; i++)
            {
                if (array[i].Type != JTokenType.Float && array[i].Type != JTokenType.Integer) return false;
                try { result[i] = (double)array[i]; } catch (Exception) { return false; }
                if (double.IsNaN(result[i]) || double.IsInfinity(result[i])) return false;
            }
            numbers = result; return true;
        }
        static bool ToEuler(double[] q, out double[] degrees)
        {
            degrees = null;
            double norm = Math.Sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
            if (norm < 1e-12 || double.IsInfinity(norm)) return false;
            double w = q[0] / norm, x = q[1] / norm, y = q[2] / norm, z = q[3] / norm;
            double pitch = Math.Asin(Math.Max(-1, Math.Min(1, 2 * (w * y - x * z))));
            double roll, yaw;
            if (Math.Abs(Math.Cos(pitch)) > 1e-7)
            { roll = Math.Atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)); yaw = Math.Atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)); }
            else { roll = Math.Atan2(2 * (w * x - y * z), 1 - 2 * (x * x + z * z)); yaw = 0; }
            degrees = new[] { roll * 180 / Math.PI, pitch * 180 / Math.PI, yaw * 180 / Math.PI };
            return true;
        }
        public static JArray EulerQuaternion(double x, double y, double z)
        {
            x *= Math.PI / 360; y *= Math.PI / 360; z *= Math.PI / 360;
            double cx = Math.Cos(x), sx = Math.Sin(x), cy = Math.Cos(y), sy = Math.Sin(y), cz = Math.Cos(z), sz = Math.Sin(z);
            return new JArray(cz * cy * cx + sz * sy * sx, cz * cy * sx - sz * sy * cx,
                cz * sy * cx + sz * cy * sx, sz * cy * cx - cz * sy * sx);
        }
        public bool Stage()
        {
            if (!IsCurrent || session.Busy) { Notice = "Reload the current target and values before applying"; return false; }
            var values = new double[3];
            for (int i = 0; i < 3; i++)
            {
                if (!Parse(text[i], out values[i])) { Notice = "Enter a valid decimal for every axis"; return false; }
                double low = Mode.StartsWith("scale", StringComparison.Ordinal) ? .001 : Creation ? .001 : Mode == "rotation" ? -360000 : -1000000;
                double high = Mode.StartsWith("scale", StringComparison.Ordinal) ? 1000 : Mode == "rotation" ? 360000 : 1000000;
                if (values[i] < low || values[i] > high) { Notice = "Value is outside the supported " + Unit + " range"; return false; }
                if (Mode != "rotation" && !Mode.StartsWith("scale", StringComparison.Ordinal)) values[i] /= 1000;
            }
            if (Creation)
            {
                if (!objects.Stage(Mode)) return false;
                session.Draft["args"]["dimensions"] = new JArray(values);
                return true;
            }
            session.Select(target);
            string op = Mode == "move" || Mode == "position" ? "object.move" : Mode == "rotation" ? "object.rotate" : "object.scale";
            var args = Mode == "rotation" ? new JObject { ["to"] = EulerQuaternion(values[0], values[1], values[2]) }
                : new JObject { [Mode == "move" || Mode == "scale.by" ? "by" : "to"] = new JArray(values) };
            return session.BeginDraft(op, args, true);
        }
    }
}
