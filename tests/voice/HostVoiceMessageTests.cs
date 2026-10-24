using System;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using Xunit;
using static SpatialModeling.VoiceCore.Tests.Fixture;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>The voice messages between VoiceCore and the host: voice.resolve out, voice.candidates and voice.grammar
    /// in, and voice.run as a normal command. The shapes are the agreed proposal; the schema checks run once
    /// contracts/ has the voice schemas.</summary>
    public class HostVoiceMessageTests
    {
        /// <summary>The proposal's voice.candidates example (the payload).</summary>
        const string CandidatesPayload = @"{
  ""resolution"": ""e3a9d1c4b7f24e0a8c6b5d4e3f2a1b09"",
  ""decision"": ""run"",
  ""reason"": null,
  ""expires_in"": 30,
  ""candidates"": [
    { ""choice"": 1, ""say"": ""Array"", ""operator"": ""object.modifier_add"", ""properties"": { ""type"": ""ARRAY"" },
      ""set"": { ""count"": 5, ""relative_offset_displace"": [0.0, 0.0, 1.0] }, ""needs_target"": true },
    { ""choice"": 2, ""say"": ""duplicate"", ""operator"": ""object.duplicate"", ""properties"": {}, ""set"": {}, ""needs_target"": true },
    { ""choice"": 3, ""say"": ""Subdivision Surface"", ""operator"": ""object.modifier_add"", ""properties"": { ""type"": ""SUBSURF"" },
      ""set"": { ""levels"": 1, ""render_levels"": 1 }, ""needs_target"": true }
  ]
}";

        [Fact]
        public void ReadsTheCandidatesExample()
        {
            VoiceCandidates answer = VoiceCandidates.FromJson(CandidatesPayload);
            Assert.Equal("e3a9d1c4b7f24e0a8c6b5d4e3f2a1b09", answer.Resolution);
            Assert.Equal(VoiceDecision.Run, answer.Decision);
            Assert.Null(answer.Reason);
            Assert.Equal(30, answer.ExpiresIn);
            Assert.Equal(new[] { "1. Array", "2. duplicate", "3. Subdivision Surface" }, answer.Candidates.Select(c => c.ToString()));
            Assert.Equal("object.modifier_add", answer.Candidates[0].Operator);
            Assert.All(answer.Candidates, c => Assert.True(c.NeedsTarget));
        }

        [Fact]
        public void ReadsAnAskAndAReject()
        {
            VoiceCandidates ask = VoiceCandidates.FromJson(
                "{\"resolution\":\"r1\",\"decision\":\"ask\",\"reason\":\"not sure: \\\"thicker\\\"\",\"expires_in\":12.5," +
                "\"candidates\":[{\"choice\":1,\"say\":\"Solidify\\u00e9\"}]}");
            Assert.Equal(VoiceDecision.Ask, ask.Decision);
            Assert.Equal("not sure: \"thicker\"", ask.Reason);
            Assert.Equal(12.5, ask.ExpiresIn);
            Assert.Equal("Solidifyé", ask.Candidates.Single().Say);
            Assert.False(ask.Candidates.Single().NeedsTarget);
            Assert.Null(ask.Candidates.Single().Operator);

            VoiceCandidates reject = VoiceCandidates.FromJson("{ \"resolution\" : \"r2\", \"decision\" : \"reject\", \"reason\" : \"no match\", \"candidates\" : [ ] }");
            Assert.Equal(VoiceDecision.Reject, reject.Decision);
            Assert.Empty(reject.Candidates);
            Assert.Equal(30, reject.ExpiresIn); // the contract's default
        }

        [Theory]
        [InlineData("")]
        [InlineData("[]")]
        [InlineData("{\"resolution\":\"r\",\"decision\":\"maybe\",\"candidates\":[]}")]
        [InlineData("{\"decision\":\"run\",\"candidates\":[]}")]
        [InlineData("{\"resolution\":\"r\",\"decision\":\"run\",\"candidates\":[{\"say\":\"x\"}]}")]
        [InlineData("{\"resolution\":\"r\",\"decision\":\"run\"")]
        [InlineData("{\"resolution\":\"r\",\"decision\":\"run\"} x")]
        public void RefusesWhatIsNotACandidatesPayload(string json)
        {
            Assert.Throws<FormatException>(() => VoiceCandidates.FromJson(json));
        }

        [Fact]
        public void ReadsTheGrammarExample()
        {
            const string payload = "{\"version\":\"demo-1\",\"phrases\":[\"a\",\"about\",\"add\",\"add a boolean\",\"add a monkey\"]}";
            Assert.Equal(new[] { "a", "about", "add", "add a boolean", "add a monkey" }, VoiceGrammar.FromJson(payload));
            Assert.Equal("voice.grammar", VoiceGrammar.Type);
            Assert.Throws<FormatException>(() => VoiceGrammar.FromJson("{\"phrases\":[1]}"));
        }

        [Fact]
        public void TheResolveRequestMatchesTheProposal()
        {
            var f = new Fixture(Contract.SnapshotObjects());
            f.Options.AskHost = true;
            const string shaft = "fd7bd4ddae444528a4fedbc562fe018b";
            f.Session.SetSelection(new[] { shaft });
            VoiceResolve request = f.Say("make five copies along z", 0.93f).Resolve;
            JsonObject message = Envelope(VoiceResolve.Type, Contract.ToJson(request.Payload(Contract.Generation(shaft))));
            JsonNode payload = message["payload"];
            Assert.Equal(new[] { "confidence", "target", "text" }, payload.AsObject().Select(p => p.Key).OrderBy(k => k));
            Assert.Equal(shaft, (string)payload["target"]["id"]);
            Assert.Equal(Contract.Generation(shaft), (long)payload["target"]["generation"]);
            if (Contract.HasSchema("voice.resolve.schema.json"))
                AssertValid("voice.resolve.schema.json", message);
        }

        [Fact]
        public void VoiceRunIsANormalCommand()
        {
            var f = new Fixture(Contract.SnapshotObjects());
            f.Options.AskHost = true;
            const string shaft = "fd7bd4ddae444528a4fedbc562fe018b";
            f.Session.SetSelection(new[] { shaft });
            VoiceTurn sent = f.Say("make five copies along z");
            f.Session.ResolveSent(sent.Resolve, "5b1f0c7e9a2d4e61b3f8c0a4d6e2f917");
            VoiceTurn run = f.Session.HostAnswered("5b1f0c7e9a2d4e61b3f8c0a4d6e2f917", VoiceCandidates.FromJson(CandidatesPayload));
            HostCommand command = HostCommand.From(run.Command);
            JsonObject message = Contract.Envelope(command, 41);
            JsonNode payload = message["payload"];
            Assert.Equal("voice.run", (string)payload["op"]);
            Assert.Equal("voice", (string)payload["source"]);
            Assert.Equal(shaft, (string)payload["target"]["id"]);
            Assert.Equal("{\"resolution\":\"e3a9d1c4b7f24e0a8c6b5d4e3f2a1b09\",\"choice\":1}", payload["args"].ToJsonString());

            string schema = File.ReadAllText(Path.Combine(Contract.Root, "contracts", "schemas", "command.schema.json"));
            if (schema.Contains("voice.run"))
            {
                var results = Contract.Validate(message);
                Assert.True(results.IsValid, message.ToJsonString() + "\n" + Contract.Errors(results));
            }
        }

        [Fact]
        public void TheContractsExamplesAreReadable()
        {
            // Present once the host's voice branch adds them; until then there is nothing to check.
            string examples = Path.Combine(Contract.Root, "contracts", "examples");
            foreach (string file in Directory.GetFiles(examples, "voice.candidates*.json"))
            {
                VoiceCandidates answer = VoiceCandidates.FromJson(Contract.Example(Path.GetFileName(file))["payload"].ToJsonString());
                Assert.InRange(answer.Candidates.Count, answer.Decision == VoiceDecision.Reject ? 0 : 1, 3);
            }
            foreach (string file in Directory.GetFiles(examples, "voice.grammar*.json"))
                Assert.NotEmpty(VoiceGrammar.FromJson(Contract.Example(Path.GetFileName(file))["payload"].ToJsonString()));
        }

        [Fact]
        public void RunsAreDisplayedWithTheirTarget()
        {
            var f = new Fixture(Cube);
            f.Options.AskHost = true;
            VoiceTurn sent = f.Say("shade smooth");
            f.Session.ResolveSent(sent.Resolve, "m");
            VoiceTurn run = f.Session.HostAnswered("m", new VoiceCandidates("r", VoiceDecision.Run, null, 30,
                new[] { new VoiceCandidate(1, "Shade Smooth", "object.shade_smooth", needsTarget: true) }));
            Assert.Equal("Shade Smooth on Cube", run.Command.ToString());
            Assert.False(run.Command.RequiresConfirmation);
            Assert.Equal(Prompt.Done, HostCommand.PromptFor("voice.run", "applied", null));
            Assert.Equal(Prompt.Failed, HostCommand.PromptFor("voice.run", "rejected", "failed"));
        }

        static JsonObject Envelope(string type, JsonNode payload) =>
            new JsonObject { ["v"] = 1, ["type"] = type, ["id"] = Guid.NewGuid().ToString("N"), ["payload"] = payload };

        static void AssertValid(string schema, JsonObject message)
        {
            var results = Contract.Validate(schema, message);
            Assert.True(results.IsValid, message.ToJsonString() + "\n" + Contract.Errors(results));
        }
    }
}
