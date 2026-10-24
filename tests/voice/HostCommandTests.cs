using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using Xunit;
using static SpatialModeling.VoiceCore.Tests.Fixture;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>Voice commands against contracts/: the examples, the schemas and their bounds.</summary>
    public class HostCommandTests
    {
        const string Shaft = "fd7bd4ddae444528a4fedbc562fe018b";
        const string BasePlate = "f21f7d20394f4c02afce7ab1e6f4a1a8";
        const string Camera = "c498249e5a674e29bc24b0e23246406a";

        static Fixture Snapshot() => new Fixture(Contract.SnapshotObjects());

        static HostCommand Say(Fixture f, string text) => HostCommand.From(f.Say(text).Command);

        /// <summary>Sends like the app and checks the message against command.schema.json.</summary>
        static JsonObject Send(HostCommand command, long baseRevision = 42)
        {
            JsonObject message = Contract.Envelope(command, baseRevision);
            var results = Contract.Validate(message);
            Assert.True(results.IsValid, message.ToJsonString() + "\n" + Contract.Errors(results));
            return message;
        }

        static void AssertSameCommand(string example, JsonObject sent)
        {
            JsonNode expected = Contract.Example(example)["payload"];
            JsonNode actual = sent["payload"];
            Assert.Equal((string)expected["op"], (string)actual["op"]);
            Assert.Equal(expected["target"]?["id"]?.ToJsonString(), actual["target"]?["id"]?.ToJsonString());
            AssertJsonEqual(expected["args"], actual["args"]);
        }

        static void AssertJsonEqual(JsonNode expected, JsonNode actual)
        {
            if (expected is JsonObject eo)
            {
                var ao = Assert.IsType<JsonObject>(actual);
                Assert.Equal(eo.Select(p => p.Key).OrderBy(k => k), ao.Select(p => p.Key).OrderBy(k => k));
                foreach (var p in eo)
                    AssertJsonEqual(p.Value, ao[p.Key]);
            }
            else if (expected is JsonArray ea)
            {
                var aa = Assert.IsType<JsonArray>(actual);
                Assert.Equal(ea.Count, aa.Count);
                for (int i = 0; i < ea.Count; i++)
                    AssertJsonEqual(ea[i], aa[i]);
            }
            else if (expected.GetValueKind() == System.Text.Json.JsonValueKind.Number)
                Assert.Equal((double)expected, (double)actual, 6); // the examples round to 6 decimals
            else
                Assert.Equal(expected.ToJsonString(), actual.ToJsonString());
        }

        [Fact]
        public void SnapshotObjectsAreTheOnesTheAppShows()
        {
            SceneObject[] objects = Contract.SnapshotObjects();
            Assert.Equal(new[] { BasePlate, Shaft }, objects.Select(o => o.Id));
            Assert.All(objects, o => Assert.Matches("^[0-9a-f]{32}$", o.Id));
        }

        [Fact]
        public void PlanExampleOnTheExampleSceneSendsTheRotateExample()
        {
            Fixture f = Snapshot();
            Assert.Equal(new[] { "ask_target" }, Prompts(f.Say("rotate this object ninety degrees")));
            Assert.Equal(new[] { "ask_axis" }, Prompts(f.Session.SetSelection(new[] { Shaft })));
            VoiceTurn done = f.Say("z");
            JsonObject sent = Send(HostCommand.From(done.Command));
            AssertSameCommand("command.object.rotate.json", sent);
            Assert.Equal(Contract.Generation(Shaft), (long)sent["payload"]["target"]["generation"]);
            Assert.Equal("voice", (string)sent["payload"]["source"]);
        }

        [Fact]
        public void TheCameraIsNotEligibleSoTheShaftIsTheOnlyObjectLeftAfterDeletingThePlate()
        {
            Fixture f = Snapshot();
            Assert.Equal(new[] { "ask_target" }, Prompts(f.Say("move this ten millimeters along x")));
            f.Session.Cancel();
            f.Session.SetObjects(Contract.SnapshotObjects().Where(o => o.Id != BasePlate));
            AssertSameCommand("command.json", Send(Say(f, "move this ten millimeters along x")));
        }

        [Fact]
        public void MoveByNameMatchesTheMoveExample()
        {
            AssertSameCommand("command.json", Send(Say(Snapshot(), "move the shaft ten millimeters along x")));
            AssertSameCommand("command.json", Send(Say(Snapshot(), "Move Shaft 1 cm along the X axis.")));
        }

        [Fact]
        public void ScaleSendsAUniformFactor()
        {
            JsonObject sent = Send(Say(Snapshot(), "scale the shaft by one point five"));
            Assert.Equal("object.scale", (string)sent["payload"]["op"]);
            Assert.Equal("[1.5,1.5,1.5]", sent["payload"]["args"]["by"].ToJsonString());
        }

        [Fact]
        public void DeleteHasATargetAndNoArgs()
        {
            Fixture f = Snapshot();
            VoiceCommand command = f.Say("delete the base plate").Command;
            Assert.True(command.RequiresConfirmation);
            JsonObject sent = Send(HostCommand.From(command));
            Assert.Equal("object.delete", (string)sent["payload"]["op"]);
            Assert.Equal(BasePlate, (string)sent["payload"]["target"]["id"]);
            Assert.Equal("{}", sent["payload"]["args"].ToJsonString());
        }

        [Theory]
        [InlineData("undo", "command.history.undo.json")]
        [InlineData("redo", "command.history.redo.json")]
        public void UndoAndRedoHaveNoTarget(string text, string example)
        {
            Fixture f = Snapshot();
            f.Select(new SceneObject(Shaft, "Shaft")); // a selection doesn't become a target
            JsonObject sent = Send(Say(f, text));
            AssertSameCommand(example, sent);
            Assert.Null(sent["payload"]["target"]);
        }

        [Fact]
        public void AddUsesTheGivenPlacement()
        {
            VoiceCommand add = Snapshot().Say("add a cylinder").Command;
            AssertSameCommand("command.object.add.json",
                Send(HostCommand.From(add, new[] { -0.02, 0, 0.03 }, new[] { 0.02, 0.02, 0.04 })));

            JsonObject byDefault = Send(HostCommand.From(add));
            Assert.Equal("[0,0,0]", byDefault["payload"]["args"]["location"].ToJsonString());
            Assert.Equal("[0.05,0.05,0.05]", byDefault["payload"]["args"]["dimensions"].ToJsonString());
            Assert.Throws<ArgumentOutOfRangeException>(() => HostCommand.From(add, new[] { 2000.0, 0, 0 }));
            Assert.Throws<ArgumentOutOfRangeException>(() => HostCommand.From(add, null, new[] { 0.0, 1, 1 }));
        }

        [Fact]
        public void PlacementArraysAreCopied()
        {
            var location = new[] { 0.1, 0.2, 0.3 };
            HostCommand command = HostCommand.From(Snapshot().Say("add a cube").Command, location);
            location[0] = 5;
            Assert.Equal(0.1, ((double[])command.Args["location"])[0]);
        }

        [Theory]
        [InlineData("select the shaft")]
        [InlineData("apply")]
        [InlineData("cancel")]
        public void LocalCommandsAreNotSent(string text)
        {
            VoiceCommand command = Snapshot().Say(text).Command;
            Assert.NotNull(command);
            Assert.Null(HostCommand.From(command));
        }

        [Fact]
        public void IncompleteCommandsAreRefused()
        {
            Fixture f = Snapshot();
            f.Say("rotate this ninety degrees");
            Assert.Throws<ArgumentException>(() => HostCommand.From(f.Session.Pending.Command));
        }

        // Every value voice accepts is inside the contract's bounds, at both ends.
        [Theory]
        [InlineData("move it ten meters along x")]
        [InlineData("move it minus ten meters along y")]
        [InlineData("move it down ten meters")]
        [InlineData("move it zero point zero zero one millimeters along z")]
        [InlineData("rotate it three hundred sixty degrees around x")]
        [InlineData("rotate it minus three hundred sixty degrees around y")]
        [InlineData("rotate it zero point one degrees around z")]
        [InlineData("scale it by one percent")]
        [InlineData("scale it by zero point zero one")]
        [InlineData("scale it one hundred times")]
        public void VoiceExtremesAreValidCommands(string text)
        {
            var f = new Fixture(new SceneObject(Shaft, "Shaft"));
            VoiceTurn turn = f.Say(text);
            Assert.NotNull(turn.Command);
            Send(HostCommand.From(turn.Command));
        }

        [Theory]
        [InlineData("move it ten point one meters along x")]
        [InlineData("move it zero meters along x")]
        [InlineData("rotate it three hundred sixty one degrees around x")]
        [InlineData("rotate it zero degrees around x")]
        [InlineData("scale it by zero point zero zero nine")]
        [InlineData("scale it by one hundred point one")]
        [InlineData("scale it by minus two")]
        public void JustBeyondTheVoiceLimitsIsOutOfRange(string text)
        {
            var f = new Fixture(new SceneObject(Shaft, "Shaft"));
            VoiceTurn turn = f.Say(text);
            Assert.Null(turn.Command);
            Assert.Equal("out_of_range", turn.Prompts[0].Id);
        }

        [Fact]
        public void VoiceLimitsAndMappingChecksMatchTheSchemaBounds()
        {
            JsonNode defs = Contract.Schema("envelope.schema.json")["$defs"];
            double coordinate = (double)defs["coordinate"]["maximum"];
            double minLength = (double)defs["length"]["minimum"], maxLength = (double)defs["length"]["maximum"];
            double minFactor = (double)defs["factor"]["minimum"], maxFactor = (double)defs["factor"]["maximum"];
            JsonNode angle = Contract.Schema("command.schema.json")["$defs"]["rotate"]["oneOf"][0]["properties"]["by"]["properties"]["angle"];

            Assert.Equal(-coordinate, (double)defs["coordinate"]["minimum"]);
            Assert.Equal(HostCommand.MaxCoordinate, coordinate);
            Assert.Equal(HostCommand.MinLength, minLength);
            Assert.Equal(HostCommand.MaxLength, maxLength);
            Assert.Equal(HostCommand.MinFactor, minFactor);
            Assert.Equal(HostCommand.MaxFactor, maxFactor);
            Assert.Equal(HostCommand.MaxAngle, (double)angle["maximum"]);
            Assert.Equal(-(double)angle["maximum"], (double)angle["minimum"]);

            Assert.InRange(VoiceLimits.MaxMoveMeters, 0, coordinate);
            Assert.InRange(VoiceLimits.MaxTurnDegrees * Math.PI / 180, 0, HostCommand.MaxAngle);
            Assert.InRange(VoiceLimits.MinScaleFactor, minFactor, maxFactor);
            Assert.InRange(VoiceLimits.MaxScaleFactor, minFactor, maxFactor);
            Assert.InRange(HostCommand.DefaultAddSize, minLength, maxLength);
        }

        [Fact]
        public void VoiceAxesAreTheContractAxes()
        {
            JsonNode axes = Contract.Schema("command.schema.json")["$defs"]["rotate"]["oneOf"][0]["properties"]["by"]["properties"]["axis"]["enum"];
            Assert.Equal(axes.AsArray().Select(a => (string)a), Enum.GetNames(typeof(Axis)));
            JsonNode primitives = Contract.Schema("command.schema.json")["$defs"]["add"]["properties"]["primitive"]["enum"];
            Assert.Equal(primitives.AsArray().Select(a => (string)a), Enum.GetNames(typeof(Shape)).Select(s => s.ToLowerInvariant()));
        }

        static readonly Dictionary<string, string> PromptByCode = new Dictionary<string, string>
        {
            { "invalid_message", "out_of_range" }, { "unsupported_version", "failed" }, { "message_too_large", "failed" },
            { "unknown_type", "failed" }, { "busy", "busy" }, { "internal_error", "outcome_unknown" },
            { "permission_denied", "read_only" }, { "wrong_session", "document_changed" }, { "wrong_document", "document_changed" },
            { "not_found", "target_deleted" }, { "stale_revision", "changed" }, { "lease_conflict", "locked" },
            { "duplicate_request", "failed" }, { "solver_conflict", "failed" }, { "failed", "failed" },
        };

        [Fact]
        public void EveryContractErrorCodeHasAPrompt()
        {
            IEnumerable<string> codes = Contract.Schema("envelope.schema.json")["$defs"]["error_code"]["enum"].AsArray().Select(c => (string)c);
            Assert.Equal(codes.OrderBy(c => c), PromptByCode.Keys.OrderBy(c => c));
            foreach (KeyValuePair<string, string> pair in PromptByCode)
            {
                Assert.Equal(pair.Value, HostCommand.PromptFor("object.move", "rejected", pair.Key).Id);
                Assert.Equal(pair.Value, HostCommand.PromptFor("object.move", null, pair.Key).Id); // an error reply
            }
        }

        [Fact]
        public void OutcomesAndUndoFailuresHaveTheirOwnPrompts()
        {
            Assert.Equal("done", HostCommand.PromptFor("object.move", "applied", null).Id);
            Assert.Equal("outcome_unknown", HostCommand.PromptFor("object.move", "unknown", "internal_error").Id);
            Assert.Equal("nothing_to_undo", HostCommand.PromptFor("history.undo", "rejected", "failed").Id);
            Assert.Equal("nothing_to_redo", HostCommand.PromptFor("history.redo", "rejected", "failed").Id);
            Assert.Equal("locked", HostCommand.PromptFor("history.undo", "rejected", "lease_conflict").Id);
        }

        [Theory]
        [InlineData("result.json", "done")]
        [InlineData("result.stale_revision.json", "changed")]
        public void ResultExamplesGiveTheirPrompts(string example, string prompt)
        {
            JsonNode p = Contract.Example(example)["payload"];
            Assert.Equal(prompt, HostCommand.PromptFor((string)p["op"], (string)p["outcome"], (string)p["error"]?["code"]).Id);
        }
    }
}
