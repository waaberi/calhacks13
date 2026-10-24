using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;

// Pure managed checks only: no InputField, Unity object, native input or network.
public static class P25NumericChecks
{
    const string A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const string Created = "dddddddddddddddddddddddddddddddd", Document = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
    const string Epoch = "ffffffffffffffffffffffffffffffff";

    static void Check(bool ok, string why)
    { if (!ok) throw new Exception("P2.5 numeric tools: " + why); }

    static void Close(double actual, double expected, string why)
    { Check(Math.Abs(actual - expected) < 1e-11, why + " expected=" + expected.ToString("R", CultureInfo.InvariantCulture)); }

    static JObject Doc(long revision = 1, string id = Document, string epoch = Epoch) =>
        new JObject { ["id"] = id, ["open_epoch"] = epoch, ["revision"] = revision,
            ["units"] = new JObject { ["scale_length"] = .001, ["length_unit"] = "MILLIMETERS" } };

    static JObject Record(string id = A, long generation = 3) => new JObject {
        ["id"] = id, ["name"] = id == A ? "Alpha" : "Beta", ["generation"] = generation,
        ["transform"] = new JObject { ["location"] = new JArray(.012345, -.002, .1),
            ["scale"] = new JArray(1.2, .75, 2.5), ["rotation"] = new JArray(1, 0, 0, 0) }
    };

    sealed class Fixture : IDisposable
    {
        public readonly NativeEditSession Session = new NativeEditSession();
        public readonly List<JObject> Sent = new List<JObject>();
        public readonly NativeObjectTools Objects;
        public readonly NativeNumericTools Numeric;

        public Fixture(bool editable = true)
        {
            Session.Send = msg => Sent.Add((JObject)msg.DeepClone());
            Session.Receive(NativeEditSession.Envelope("welcome", Welcome(editable)));
            Session.Receive(NativeEditSession.Envelope("scene.snapshot", new JObject { ["document"] = Doc(),
                ["objects"] = new JArray(Record(), Record(B)) }));
            Objects = new NativeObjectTools(Session); Objects.SelectRelative(1);
            Numeric = new NativeNumericTools(Session, Objects);
        }
        public static JObject Welcome(bool editable = true) => new JObject {
            ["session_id"] = Guid.NewGuid().ToString("N"), ["host_epoch"] = Guid.NewGuid().ToString("N"),
            ["actor_id"] = Guid.NewGuid().ToString("N"), ["can_edit"] = editable, ["document"] = Doc(),
            ["capabilities"] = new JObject { ["sketch"] = false }
        };
        public void Deliver(string type, JObject payload, string re = null)
        {
            var msg = NativeEditSession.Envelope(type, payload);
            if (re != null) msg["re"] = re;
            Session.Receive(msg); Objects.Observe(msg);
        }
        public void Type(int axis, string value)
        {
            Numeric.SelectAxis(axis); Numeric.Enter("clear");
            foreach (char c in value) Numeric.Enter(c == '-' ? "sign" : c.ToString());
        }
        public void Values(string x, string y, string z)
        { Type(0, x); Type(1, y); Type(2, z); }
        public void Dispose() { Numeric.Dispose(); Objects.Dispose(); }
    }

    static JArray Vector(Fixture f, string field, string op)
    {
        Check((string)f.Session.Draft?["op"] == op, "numeric mode stages its existing shared operation");
        Check((string)f.Session.Draft?["target"]?["id"] == A, "targeted numeric draft preserves explicit UUID");
        Check((long?)f.Session.Draft?["target"]?["generation"] == 3, "targeted numeric draft preserves generation");
        return (JArray)f.Session.Draft["args"][field];
    }

    public static void Run(Action<string> report)
    {
        EntryAndUnits(); AbsoluteMetadata(); EulerOracles(); RotationMetadata(); RangesAndParsing();
        ContextInvalidation(); CreationReceipt(); PermissionAndDisposal();
        report("P25_NUMERIC_CHECK PASS 8 modes/mm+factor bounds/fractional-negative/Euler independent oracles/native rotation preload+refusal/frozen context/own-create receipt/draft-only/disposal; no native GUI or OS input");
    }

    static void EntryAndUnits()
    {
        using (var f = new Fixture())
        {
            Check(f.Numeric.Load("move") && f.Numeric.IsCurrent && f.Numeric.Mode == "move" && f.Numeric.Axis == 0,
                "numeric move opens a current local X-axis draft");
            Check(f.Numeric.Unit.Contains("millimeters"), "distance entry declares native millimeters");
            f.Numeric.SelectAxis(2); f.Numeric.SelectAxis(-1); f.Numeric.SelectAxis(3);
            Check(f.Numeric.Axis == 2, "invalid axis selection cannot alter the current axis");
            f.Numeric.Enter("7"); f.Numeric.Enter("."); f.Numeric.Enter("5");
            f.Numeric.Enter("."); Check(f.Numeric.Value(2) == "7.5", "one decimal point is accepted and duplicate dot is ignored");
            f.Numeric.Enter("sign"); Check(f.Numeric.Value(2) == "-7.5", "sign toggles the existing decimal");
            f.Numeric.Enter("back"); Check(f.Numeric.Value(2) == "-7.", "backspace removes exactly the last character");
            f.Numeric.Enter("clear"); f.Numeric.Enter("."); f.Numeric.Enter("1");
            Check(f.Numeric.Value(2) == "0.1", "a leading decimal point becomes an ordinary decimal");
            string before = f.Numeric.Value(2);
            foreach (string invalid in new[] { "e", ",", "NaN", "Infinity", "1e3", " ", null }) f.Numeric.Enter(invalid);
            Check(f.Numeric.Value(2) == before, "invalid and null keypad tokens are ignored safely");
            f.Values("-12.345", "0.001", "1000000");
            Check(f.Numeric.Stage(), "fractional negative movement and inclusive bounds stage");
            var by = Vector(f, "by", "object.move");
            Close((double)by[0], -.012345, "negative millimeters convert once to native meters");
            Close((double)by[1], .000001, "0.001mm converts to one micrometer");
            Close((double)by[2], 1000, "one million millimeters is the 1000m bound");
            Check(f.Sent.Count == 0, "numeric entry and staging send no permission or mutation");
            f.Numeric.Invalidate("test consumed");
            Check(!f.Numeric.IsCurrent && !f.Numeric.Stage() && f.Numeric.Notice.Length > 0, "explicit consumed-draft invalidation blocks reuse");
        }
    }

    static void AbsoluteMetadata()
    {
        using (var f = new Fixture())
        {
            Check(f.Numeric.Load("position") && f.Numeric.Value(0) == "12.345" && f.Numeric.Value(1) == "-2"
                && f.Numeric.Value(2) == "100", "absolute position loads real native metadata in millimeters");
            Check(f.Numeric.Stage(), "loaded absolute position stages");
            var to = Vector(f, "to", "object.move");
            Close((double)to[0], .012345, "absolute position retains native world units");
            Close((double)to[1], -.002, "absolute position preserves negative location");
            Check(f.Numeric.Load("scale.to") && f.Numeric.Unit == "scale factors", "absolute scale declares factor entry");
            Check(f.Numeric.Value(0) == "1.2" && f.Numeric.Value(1) == "0.75" && f.Numeric.Value(2) == "2.5",
                "absolute scale loads the actual independent native scale factors");
            Check(f.Numeric.Stage(), "loaded absolute scale stages");
            to = Vector(f, "to", "object.scale"); Close((double)to[2], 2.5, "absolute factor is not converted as a distance");
            var previous = CultureInfo.CurrentCulture;
            try
            {
                CultureInfo.CurrentCulture = new CultureInfo("fr-FR");
                Check(f.Numeric.Load("position") && f.Numeric.Value(0) == "12.345", "loaded text stays invariant under comma-decimal culture");
                Check(!NativeNumericTools.Parse("12,5", out _), "culture comma is refused");
            }
            finally { CultureInfo.CurrentCulture = previous; }
            Check(f.Sent.Count == 0, "absolute metadata editing does not send");
        }
        foreach (string mode in new[] { "position", "scale.to" })
        {
            using (var f = new Fixture())
            {
                f.Session.Objects[A].Remove("transform");
                Check(!f.Numeric.Load(mode), "missing current absolute metadata cannot silently invent zero/one: " + mode);
                Check(f.Sent.Count == 0, "unavailable absolute metadata never requests permission");
            }
            foreach (var bad in new[] { new JArray(1, 2), new JArray("1", 2, 3), new JArray(double.NaN, 2, 3),
                new JArray(double.PositiveInfinity, 2, 3) })
            {
                using (var f = new Fixture())
                {
                    f.Session.Objects[A]["transform"][mode == "position" ? "location" : "scale"] = bad.DeepClone();
                    Check(!f.Numeric.Load(mode) && f.Sent.Count == 0, "malformed/nonfinite absolute vector cannot invent an edit: " + mode);
                }
            }
        }
    }

    static void Quaternion(JArray q, double w, double x, double y, double z, string why)
    {
        Check(q.Count == 4, "rotation uses native WXYZ quaternion shape");
        double[] expected = { w, x, y, z };
        for (int i = 0; i < 4; i++) Close((double)q[i], expected[i], why + " component " + i);
    }

    static double[] Rotate(JArray q, double x, double y, double z)
    {
        // Vector rotation via two cross products is independent of the runtime's
        // Euler expansion. Known basis-vector images below fix composition order.
        double w = (double)q[0], a = (double)q[1], b = (double)q[2], c = (double)q[3];
        double tx = 2 * (b * z - c * y), ty = 2 * (c * x - a * z), tz = 2 * (a * y - b * x);
        return new[] { x + w * tx + b * tz - c * ty,
            y + w * ty + c * tx - a * tz, z + w * tz + a * ty - b * tx };
    }

    static void EulerOracles()
    {
        double h = Math.Sqrt(.5);
        Quaternion(NativeNumericTools.EulerQuaternion(0, 0, 0), 1, 0, 0, 0, "identity");
        Quaternion(NativeNumericTools.EulerQuaternion(90, 0, 0), h, h, 0, 0, "X quarter turn");
        Quaternion(NativeNumericTools.EulerQuaternion(0, 0, -90), h, 0, 0, -h, "negative Z quarter turn");
        // Independently known q_y(90)*q_x(90) = (.5,.5,.5,-.5).
        Quaternion(NativeNumericTools.EulerQuaternion(90, 90, 0), .5, .5, .5, -.5, "ordered mixed-axis quarter turns");
        using (var f = new Fixture())
        {
            Check(f.Numeric.Load("rotation") && f.Numeric.Unit.Contains("degrees"), "absolute rotation declares degrees and native Euler XYZ");
            f.Values("90", "90", "0"); Check(f.Numeric.Stage(), "absolute Euler XYZ stages");
            var q = Vector(f, "to", "object.rotate");
            var ex = Rotate(q, 1, 0, 0); var ey = Rotate(q, 0, 1, 0); var ez = Rotate(q, 0, 0, 1);
            Close(ex[0], 0, "mixed rotation X basis x"); Close(ex[1], 0, "mixed rotation X basis y"); Close(ex[2], -1, "X basis becomes negative Z");
            Close(ey[0], 1, "Y basis becomes positive X"); Close(ey[1], 0, "mixed rotation Y basis y"); Close(ey[2], 0, "mixed rotation Y basis z");
            Close(ez[0], 0, "mixed rotation Z basis x"); Close(ez[1], -1, "Z basis becomes negative Y"); Close(ez[2], 0, "mixed rotation Z basis z");
            Check(f.Sent.Count == 0, "rotation staging never changes native history or sends");
        }
    }

    static void Basis(JArray quaternion, double[,] rows, string why, double tolerance = 1e-11)
    {
        Check(quaternion.Count == 4, why + " preserves native WXYZ shape");
        for (int column = 0; column < 3; column++)
        {
            var actual = Rotate(quaternion, column == 0 ? 1 : 0, column == 1 ? 1 : 0, column == 2 ? 1 : 0);
            for (int row = 0; row < 3; row++)
                Check(Math.Abs(actual[row] - rows[row, column]) < tolerance,
                    why + " basis " + column + " coordinate " + row);
        }
    }

    static void RotationMetadata()
    {
        // Constants come from independent Rx/Ry/Rz matrix multiplication and
        // matrix-to-quaternion conversion, not the runtime Euler expansion.
        double[] native = { .7685926578370762, .32071547435316106, -.17195247291454624, .5261551652202402 };
        double[,] baseline = {
            { .3871861783412678, -.9190936315766364, .07316939043585247 },
            { .6985023559086851, .24060465324497712, -.6739464812779133 },
            { .6018150231520483, .31205175409238545, .7351478631379983 }
        };
        double[,] edited = {
            { .47331769645983013, -.8460918868721914, .2451507234070809 },
            { .8538877278285976, .37230328690992864, -.36368394358258144 },
            { .21643961393810288, .3814692406015436, .8986852129601369 }
        };
        foreach (double multiplier in new[] { 1.0, 2.0, -3.0 })
        {
            using (var f = new Fixture())
            {
                f.Session.Objects[A]["transform"]["rotation"] = new JArray(
                    native[0] * multiplier, native[1] * multiplier, native[2] * multiplier, native[3] * multiplier);
                Check(f.Numeric.Load("rotation"), "native WXYZ rotation metadata loads and normalizes");
                double[] angles = { 23, -37, 61 };
                for (int i = 0; i < 3; i++)
                {
                    Check(NativeNumericTools.Parse(f.Numeric.Value(i), out double value), "preloaded rotation text is an ordinary finite decimal");
                    Close(value, angles[i], "nontrivial native rotation preloads its equivalent Euler axis " + i);
                }
                Check(f.Numeric.Stage(), "untouched native rotation can stage without inventing zero axes");
                Basis(Vector(f, "to", "object.rotate"), baseline, "loaded 23,-37,61 rotation round trip");
                string x = f.Numeric.Value(0), z = f.Numeric.Value(2);
                f.Type(1, "-12.5");
                Check(f.Numeric.Value(0) == x && f.Numeric.Value(2) == z, "editing Y preserves both untouched native rotation axes");
                Check(f.Numeric.Stage(), "one-axis edit of preloaded native rotation stages");
                Basis(Vector(f, "to", "object.rotate"), edited, "edited 23,-12.5,61 rotation");
                Check(f.Sent.Count == 0, "rotation preload, normalization and local edits send no permission or mutation");
            }
        }
        using (var f = new Fixture())
        {
            f.Session.Objects[A]["transform"]["rotation"] = new JArray(
                .69636424032001898, .12278780396897283, .69636424032001887, -.12278780396897282);
            Check(f.Numeric.Load("rotation") && f.Numeric.Stage(), "native gimbal-pitch rotation loads and stages");
            // Euler values are non-unique at pitch 90. Assert equivalent basis;
            // 1e-7 allows asin's roundoff at its endpoint, not a unique angle.
            Basis(Vector(f, "to", "object.rotate"), new double[,] {
                { 0, .34202014332566866, .9396926207859084 },
                { 0, .9396926207859084, -.34202014332566866 },
                { -1, 0, 0 }
            }, "native 30,90,10 gimbal orientation round trip", 1e-7);
            Check(f.Sent.Count == 0, "gimbal metadata round trip remains a local draft");
        }
        using (var f = new Fixture())
        {
            ((JObject)f.Session.Objects[A]["transform"]).Remove("rotation");
            Check(!f.Numeric.Load("rotation") && !f.Numeric.Stage() && f.Sent.Count == 0,
                "missing native quaternion cannot silently replace the object's orientation");
        }
        foreach (JToken bad in new JToken[] { JValue.CreateNull(), new JObject(), new JArray(1, 0, 0),
            new JArray(1, 0, 0, 0, 0), new JArray("1", 0, 0, 0), new JArray(1, JValue.CreateNull(), 0, 0),
            new JArray(double.NaN, 0, 0, 0), new JArray(1, double.PositiveInfinity, 0, 0), new JArray(0, 0, 0, 0) })
        {
            using (var f = new Fixture())
            {
                f.Session.Objects[A]["transform"]["rotation"] = bad.DeepClone();
                Check(!f.Numeric.Load("rotation") && !f.Numeric.Stage() && f.Sent.Count == 0,
                    "malformed/nonfinite/zero native quaternion refuses the whole numeric intent");
            }
        }
    }

    static void RangesAndParsing()
    {
        foreach (string bad in new[] { "", "-", ".", "1e3", "NaN", "Infinity", "-Infinity", "1,5", " 1", "1 ", "1/2", null })
            Check(!NativeNumericTools.Parse(bad, out _), "invalid decimal text is refused: " + (bad ?? "null"));
        foreach (string mode in new[] { "move", "position", "scale.by", "scale.to", "add.cube", "add.sphere", "add.cylinder" })
        {
            using (var f = new Fixture())
            {
                bool factor = mode.StartsWith("scale", StringComparison.Ordinal), creation = mode.StartsWith("add.", StringComparison.Ordinal);
                Check(f.Numeric.Load(mode), "supported numeric mode loads: " + mode);
                f.Values(factor || creation ? "0.001" : "-1000000", factor ? "1000" : "1000000", factor ? "1.25" : creation ? "0.001" : "0.001");
                Check(f.Numeric.Stage(), "inclusive numeric bounds are accepted: " + mode);
                if (creation)
                {
                    Check((string)f.Session.Draft["op"] == "object.add" && f.Session.Draft["target"] == null, "numeric creation remains the existing targetless add command");
                    Check((string)f.Session.Draft["args"]["primitive"] == mode.Substring(4), "numeric primitive type is preserved");
                    var size = (JArray)f.Session.Draft["args"]["dimensions"];
                    Close((double)size[0], .000001, "inclusive primitive lower dimension in meters");
                    Close((double)size[1], 1000, "inclusive primitive upper dimension in meters");
                    foreach (var v in (JArray)f.Session.Draft["args"]["location"]) Close((double)v, 0, "numeric primitive remains at world origin");
                }
                else if (factor)
                {
                    var args = (JArray)f.Session.Draft["args"][mode == "scale.by" ? "by" : "to"];
                    Close((double)args[0], .001, "factor lower bound is unitless"); Close((double)args[1], 1000, "factor upper bound is unitless");
                }
                foreach (string value in factor ? new[] { "0", "-1", "0.0009", "1000.001" }
                    : creation ? new[] { "0", "-1", "0.0009", "1000000.001" } : new[] { "-1000000.001", "1000000.001" })
                {
                    Check(f.Numeric.Load(mode), "reload a fresh value for out-of-range check"); f.Type(0, value);
                    Check(!f.Numeric.Stage(), "out-of-range entry cannot stage: " + mode + "=" + value);
                }
                f.Numeric.Load(mode); f.Type(0, ""); Check(!f.Numeric.Stage(), "empty axis refuses the whole draft");
                Check(f.Sent.Count == 0, "all invalid numeric drafts emit no permission: " + mode);
            }
        }
        using (var f = new Fixture())
        {
            f.Numeric.Load("rotation"); f.Values("-360000", "360000", "0"); Check(f.Numeric.Stage(), "rotation's inclusive bounded degree range stages");
            f.Numeric.Load("rotation"); f.Type(0, "360000.001"); Check(!f.Numeric.Stage(), "rotation above bound refuses");
            Check(!f.Numeric.Load("not-an-operation") && f.Sent.Count == 0, "unknown mode never creates a new command path");
        }
    }

    static void ContextInvalidation()
    {
        string[] causes = { "revision", "generation", "target", "removal", "welcome", "document", "open_epoch", "disconnect", "scene" };
        foreach (string cause in causes)
        {
            using (var f = new Fixture())
            {
                Check(f.Numeric.Load("move"), "context test starts with a current numeric target"); f.Type(0, "12.5");
                if (cause == "revision") f.Deliver("scene.update", new JObject { ["document"] = Doc(2) });
                else if (cause == "generation") f.Deliver("scene.update", new JObject { ["objects"] = new JArray(Record(generation: 4)) });
                else if (cause == "target") f.Objects.SelectRelative(1);
                else if (cause == "removal")
                {
                    f.Deliver("scene.update", new JObject { ["removed"] = new JArray(A) });
                    f.Deliver("scene.update", new JObject { ["objects"] = new JArray(Record()) });
                }
                else if (cause == "welcome")
                {
                    f.Deliver("welcome", Fixture.Welcome());
                    f.Deliver("scene.snapshot", new JObject { ["document"] = Doc(), ["objects"] = new JArray(Record()) });
                }
                else if (cause == "document") f.Deliver("scene.update", new JObject { ["document"] = Doc(id: Guid.NewGuid().ToString("N")) });
                else if (cause == "open_epoch") f.Deliver("scene.update", new JObject { ["document"] = Doc(epoch: Guid.NewGuid().ToString("N")) });
                else if (cause == "disconnect") f.Session.Disconnect("test");
                else f.Session.SceneCurrent = false;
                Check(!f.Numeric.IsCurrent && !f.Numeric.Stage(), "frozen numeric intent cannot survive changed context: " + cause);
                Check(f.Sent.Count == 0, "stale numeric context requests no permission: " + cause);
            }
        }
    }

    static void CreationReceipt()
    {
        using (var f = new Fixture())
        {
            Check(f.Numeric.Load("add.cylinder"), "numeric cylinder loads"); f.Values("25", "25", "80");
            Check(f.Numeric.Stage() && f.Sent.Count == 0, "numeric creation stages through object tools without sending");
            Check(f.Session.Apply(), "shared session is the only owner of Apply");
            f.Numeric.Invalidate("Applied intent consumed");
            string acquire = (string)f.Sent[f.Sent.Count - 1]["id"];
            f.Deliver("lease.granted", new JObject { ["lease"] = new JObject { ["lease_id"] = Guid.NewGuid().ToString("N") } }, acquire);
            var command = f.Sent[f.Sent.Count - 1];
            Check((string)command["type"] == "command", "existing shared lease flow sends numeric geometry only after grant");
            var size = (JArray)command["payload"]["args"]["dimensions"];
            Close((double)size[0], .025, "native cylinder diameter in X"); Close((double)size[1], .025, "native cylinder diameter in Y"); Close((double)size[2], .08, "native cylinder depth in Z");
            f.Deliver("result", new JObject { ["request_id"] = f.Session.LastSubmittedId, ["op"] = "object.add",
                ["outcome"] = "applied", ["created"] = new JArray(Created), ["summary"] = "Created native cylinder" });
            Check(f.Objects.TargetId == Created && !f.Objects.TargetAvailable, "replacing dimensions preserves own object.add receipt correlation before delayed scene data");
            f.Deliver("scene.update", new JObject { ["objects"] = new JArray(Record(Created, 9)) });
            Check(f.Objects.TargetAvailable && f.Objects.TargetId == Created && !f.Numeric.IsCurrent,
                "real created record enables the exact object while consumed numeric entry stays invalid");
        }
    }

    static int Subscriptions(NativeEditSession session)
    {
        var field = typeof(NativeEditSession).GetField("Changed", BindingFlags.Instance | BindingFlags.NonPublic);
        return (field?.GetValue(session) as Delegate)?.GetInvocationList().Length ?? 0;
    }

    static void PermissionAndDisposal()
    {
        using (var f = new Fixture(false))
            Check(!f.Numeric.Load("move") && !f.Numeric.Load("add.cube") && f.Sent.Count == 0,
                "read-only session cannot arm any numeric command");
        using (var f = new Fixture())
        {
            Check(f.Numeric.Load("move"), "permission test loads editable metadata");
            f.Deliver("session.update", new JObject { ["leases"] = new JArray(new JObject { ["mode"] = "exclusive", ["targets"] = new JArray(),
                ["owner"] = new JObject { ["actor_id"] = "other", ["name"] = "Other editor" } }) });
            Check(f.Numeric.Stage() && !f.Session.Apply() && f.Sent.Count == 0, "shared session retains conflict enforcement after numeric staging");
            int before = Subscriptions(f.Session); f.Numeric.Dispose();
            Check(Subscriptions(f.Session) == before - 1, "disposing numeric tools unsubscribes its native-session listener");
            f.Numeric.Dispose(); Check(Subscriptions(f.Session) == before - 1, "repeated disposal cannot detach another component's listener");
        }
    }
}
