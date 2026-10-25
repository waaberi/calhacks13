using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using Json.Schema;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>The repository's contracts/ folder: examples, schemas, and a sender like the Unity app's.</summary>
    static class Contract
    {
        public static readonly string Root = FindRoot();

        static readonly Lazy<JsonSchema> CommandSchema = new Lazy<JsonSchema>(() =>
        {
            string dir = Path.Combine(Root, "contracts", "schemas");
            foreach (string file in Directory.GetFiles(dir, "*.schema.json"))
                SchemaRegistry.Global.Register(JsonSchema.FromFile(file)); // so the $refs between them resolve
            return (JsonSchema)SchemaRegistry.Global.Get(new Uri(Path.Combine(dir, "command.schema.json")));
        });

        static string FindRoot()
        {
            string dir = AppContext.BaseDirectory;
            while (dir != null && !Directory.Exists(Path.Combine(dir, "contracts", "schemas")))
                dir = Path.GetDirectoryName(dir);
            return dir ?? throw new DirectoryNotFoundException("contracts/ not found above " + AppContext.BaseDirectory);
        }

        public static JsonNode Example(string name) => JsonNode.Parse(File.ReadAllText(Path.Combine(Root, "contracts", "examples", name)));

        public static JsonNode Schema(string name) => JsonNode.Parse(File.ReadAllText(Path.Combine(Root, "contracts", "schemas", name)));

        /// <summary>The visible objects with a mesh in scene.snapshot.json: what the VR app shows.</summary>
        public static SceneObject[] SnapshotObjects() =>
            Example("scene.snapshot.json")["payload"]["objects"].AsArray()
                .Where(o => (bool)o["visible"] && o["mesh"] != null)
                .Select(o => new SceneObject((string)o["id"], (string)o["name"]))
                .ToArray();

        public static long Generation(string objectId) =>
            (long)Example("scene.snapshot.json")["payload"]["objects"].AsArray().Single(o => (string)o["id"] == objectId)["generation"];

        /// <summary>What the app's sender does: the request fields from welcome.json, base_revision, the target's
        /// generation, and an envelope.</summary>
        public static JsonObject Envelope(HostCommand command, long baseRevision)
        {
            JsonNode welcome = Example("welcome.json")["payload"];
            var payload = new JsonObject
            {
                ["session_id"] = (string)welcome["session_id"],
                ["host_epoch"] = (string)welcome["host_epoch"],
                ["document_id"] = (string)welcome["document"]["id"],
                ["open_epoch"] = (string)welcome["document"]["open_epoch"],
                ["actor_id"] = (string)welcome["actor_id"],
                ["base_revision"] = baseRevision,
                ["source"] = HostCommand.Source,
                ["op"] = command.Op,
            };
            if (command.TargetId != null)
                payload["target"] = new JsonObject { ["id"] = command.TargetId, ["generation"] = Generation(command.TargetId) };
            payload["args"] = ToJson(command.Args);
            return new JsonObject { ["v"] = 1, ["type"] = "command", ["id"] = Guid.NewGuid().ToString("N"), ["payload"] = payload };
        }

        /// <summary>Args as plain data to JSON, like Newtonsoft's JObject.FromObject in the app.</summary>
        public static JsonNode ToJson(object value)
        {
            switch (value)
            {
                case IReadOnlyDictionary<string, object> map:
                    var obj = new JsonObject();
                    foreach (KeyValuePair<string, object> kv in map)
                        obj[kv.Key] = ToJson(kv.Value);
                    return obj;
                case double[] numbers:
                    return new JsonArray(numbers.Select(n => (JsonNode)n).ToArray());
                case double number:
                    return number;
                case int integer:
                    return integer;
                case long integer:
                    return integer;
                case string text:
                    return text;
                default:
                    throw new ArgumentException("Not plain data: " + value?.GetType());
            }
        }

        public static EvaluationResults Validate(JsonNode message) =>
            CommandSchema.Value.Evaluate(message, new EvaluationOptions { OutputFormat = OutputFormat.List });

        /// <summary>Whether contracts/schemas has this schema (the voice ones arrive with the host's voice branch).</summary>
        public static bool HasSchema(string name) => File.Exists(Path.Combine(Root, "contracts", "schemas", name));

        /// <summary>Checks a message against any schema in contracts/schemas.</summary>
        public static EvaluationResults Validate(string schema, JsonNode message)
        {
            _ = CommandSchema.Value; // registers every schema, so the $refs resolve
            var registered = (JsonSchema)SchemaRegistry.Global.Get(new Uri(Path.Combine(Root, "contracts", "schemas", schema)));
            return registered.Evaluate(message, new EvaluationOptions { OutputFormat = OutputFormat.List });
        }

        public static string Errors(EvaluationResults results) =>
            string.Join("; ", (results.Details ?? new List<EvaluationResults>())
                .Where(d => d.Errors != null)
                .SelectMany(d => d.Errors.Select(e => d.InstanceLocation + ": " + e.Value)));
    }
}
