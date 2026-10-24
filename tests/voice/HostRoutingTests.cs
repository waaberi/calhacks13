using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;
using static SpatialModeling.VoiceCore.Tests.Fixture;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>
    /// VoiceSession with <see cref="VoiceSessionOptions.AskHost"/>: which words go to the host's resolver, the
    /// "which one?" dialogue, and the fallbacks to VoiceCore's own path.
    /// </summary>
    public class HostRoutingTests
    {
        /// <summary>A session that asks a host, and sends each resolve request with a fresh message ID.</summary>
        sealed class Asking
        {
            public readonly Fixture F;
            public string LastId;
            public VoiceResolve LastRequest;
            int next;

            public Asking(params SceneObject[] objects)
            {
                F = new Fixture(objects);
                F.Options.AskHost = true;
            }

            public VoiceSession Session => F.Session;

            /// <summary>Hears the words; a resolve request is "sent" right away.</summary>
            public VoiceTurn Say(string text, float confidence = 0.95f)
            {
                VoiceTurn turn = F.Say(text, confidence);
                if (turn.Resolve != null)
                {
                    LastRequest = turn.Resolve;
                    LastId = "msg" + next++;
                    Assert.Empty(Session.ResolveSent(turn.Resolve, LastId).Prompts);
                }
                return turn;
            }

            public VoiceTurn Answer(VoiceDecision decision, params VoiceCandidate[] candidates) =>
                Session.HostAnswered(LastId, new VoiceCandidates("res-" + LastId, decision, null, 30, candidates));

            public VoiceTurn Reject() => Answer(VoiceDecision.Reject);
        }

        static readonly VoiceCandidate Array = new VoiceCandidate(1, "Array", "object.modifier_add", needsTarget: true);
        static readonly VoiceCandidate Duplicate = new VoiceCandidate(2, "duplicate", "object.duplicate", needsTarget: true);
        static readonly VoiceCandidate Subsurf = new VoiceCandidate(3, "Subdivision Surface", "object.modifier_add", needsTarget: true);
        static readonly VoiceCandidate Monkey = new VoiceCandidate(1, "Monkey", "mesh.primitive_monkey_add");

        static string Describe(VoiceTurn turn) =>
            (turn.Command == null ? "-" : turn.Command.ToString()) + " | " + string.Join(",", Prompts(turn)) + " | " + (turn.Resolve != null);

        // ---------- routing ----------

        [Theory]
        [InlineData("add a cube")]
        [InlineData("create a sphere")]
        [InlineData("move it ten centimeters along x")]
        [InlineData("move it up five millimeters")]
        [InlineData("rotate this ninety degrees around z")]
        [InlineData("rotate this object ninety degrees")]
        [InlineData("scale it by two")]
        [InlineData("scale this to fifty percent")]
        [InlineData("delete this")]
        [InlineData("select the cube")]
        [InlineData("undo")]
        [InlineData("redo")]
        [InlineData("cancel")]
        [InlineData("apply")]
        [InlineData("apply it")]
        [InlineData("undo the move")]
        [InlineData("Okay, rotate the object -90° around the Z axis.")]
        [InlineData("[unk]")]
        [InlineData("[unk] [unk]")]
        [InlineData("move eight add y millimeters")] // two different verbs: the #142 check comes first
        public void TodaysCommandsStayOnVoiceCoresPath(string text)
        {
            var asking = new Asking(Cube, Sphere);
            var plain = new Fixture(Cube, Sphere);
            asking.F.Select(Cube);
            plain.Select(Cube);
            VoiceTurn turn = asking.Say(text);
            Assert.Null(turn.Resolve);
            Assert.Equal(Describe(plain.Say(text)), Describe(turn));
        }

        [Theory]
        [InlineData("shade smooth")]           // no verb
        [InlineData("a monkey")]               // "add" lost at the press
        [InlineData("make it thicker")]
        [InlineData("subdivide it level two")]
        [InlineData("add a monkey")]           // words VoiceCore doesn't know after the verb
        [InlineData("add a mirror modifier")]
        [InlineData("add a donut")]
        [InlineData("select all")]
        [InlineData("apply the scale")]        // apply with more words
        [InlineData("apply the modifier")]
        public void WordsVoiceCoreDoesNotKnowGoToTheHost(string text)
        {
            var asking = new Asking(Cube, Sphere);
            VoiceTurn turn = asking.Say(text);
            Assert.NotNull(turn.Resolve);
            Assert.Equal(text, turn.Resolve.Text);
            Assert.Null(turn.Command);
            Assert.Empty(turn.Prompts);
            Assert.True(asking.Session.WaitingForHost);
        }

        [Theory]
        [InlineData("undo the bevel", CommandKind.Undo)]
        [InlineData("redo the monkey", CommandKind.Redo)]
        [InlineData("cancel the donut", CommandKind.Cancel)]
        public void UndoRedoAndCancelNeverGoToTheHost(string text, CommandKind kind)
        {
            var asking = new Asking(Cube);
            VoiceTurn turn = asking.Say(text);
            Assert.Null(turn.Resolve);
            Assert.Equal(kind, turn.Command.Kind);
        }

        [Fact]
        public void TwoDifferentVerbsAreAMishearingBeforeAnyRouting()
        {
            var asking = new Asking(Cube);
            VoiceTurn turn = asking.Say("add a monkey and delete it");
            Assert.Null(turn.Resolve);
            Assert.Equal(new[] { "low_confidence" }, Prompts(turn));
        }

        [Fact]
        public void WithoutAskHostNothingGoesToTheHost()
        {
            var f = new Fixture(Cube);
            VoiceTurn turn = f.Say("add a monkey");
            Assert.Null(turn.Resolve);
            Assert.Equal(new[] { "ask_shape" }, Prompts(turn));
            Assert.Equal(new[] { "unsupported" }, Prompts(new Fixture(Cube).Say("shade smooth")));
        }

        [Fact]
        public void TheRequestNamesTheObjectTheWordsNameThenTheSelection()
        {
            var asking = new Asking(Cube, Sphere);
            asking.F.Select(Cube);
            Assert.Equal(Sphere.Id, asking.Say("make the sphere thicker").Resolve.TargetId);
            Assert.Equal(Cube.Id, asking.Say("make it thicker").Resolve.TargetId);
            asking.F.Select();
            asking.Session.SetPointerTarget(Sphere.Id);
            Assert.Equal(Sphere.Id, asking.Say("shade smooth").Resolve.TargetId);
            asking.Session.SetPointerTarget(null);
            Assert.Null(asking.Say("shade smooth").Resolve.TargetId);
            Assert.Equal(Cylinder.Id, new Asking(Cylinder).Say("shade smooth").Resolve.TargetId); // the only object
        }

        [Fact]
        public void ThePayloadHasTheTextConfidenceAndTarget()
        {
            var asking = new Asking(Cube);
            VoiceResolve request = asking.Say("make five copies along z", 0.93f).Resolve;
            IReadOnlyDictionary<string, object> payload = request.Payload(12);
            Assert.Equal("make five copies along z", payload["text"]);
            Assert.Equal(0.93, (double)payload["confidence"], 6);
            var target = (IReadOnlyDictionary<string, object>)payload["target"];
            Assert.Equal(Cube.Id, target["id"]);
            Assert.Equal(12L, target["generation"]);
            Assert.False(request.Payload(null).ContainsKey("target")); // generation unknown: no target
            Assert.Equal("voice.resolve", VoiceResolve.Type);
        }

        // ---------- the host's answer ----------

        [Fact]
        public void ARunDecisionSendsVoiceRunWithChoiceOneAtOnce()
        {
            var asking = new Asking(Cube);
            asking.Say("add an array five copies");
            VoiceTurn turn = asking.Answer(VoiceDecision.Run, Array, Duplicate, Subsurf);
            Assert.Empty(turn.Prompts);
            Assert.Equal(CommandKind.Run, turn.Command.Kind);
            Assert.Equal(1, turn.Command.Choice);
            Assert.Equal("Array on Cube", turn.Command.ToString());
            Assert.False(asking.Session.WaitingForHost);

            HostCommand command = HostCommand.From(turn.Command);
            Assert.Equal("voice.run", command.Op);
            Assert.Equal(Cube.Id, command.TargetId);
            Assert.Equal("res-" + asking.LastId, command.Args["resolution"]);
            Assert.Equal(1, command.Args["choice"]);
            Assert.Equal(new[] { "choice", "resolution" }, command.Args.Keys.OrderBy(k => k));
        }

        [Fact]
        public void ACandidateWithoutATargetRunsWithoutOne()
        {
            var asking = new Asking(Cube);
            asking.F.Select(Cube);
            asking.Say("add a monkey");
            HostCommand command = HostCommand.From(asking.Answer(VoiceDecision.Run, Monkey).Command);
            Assert.Null(command.TargetId);
        }

        [Theory]
        [InlineData("selected cylinder")] // Vosk's "select the cylinder": the host would add one
        [InlineData("on cube")]           // "add a cube"
        public void ARunOfACoreShapeWithoutItsVerbOnlyAsks(string text)
        {
            var asking = new Asking(Cube);
            Assert.NotNull(asking.Say(text).Resolve);
            var cylinder = new VoiceCandidate(1, "Cylinder", "mesh.primitive_cylinder_add");
            VoiceTurn turn = asking.Answer(VoiceDecision.Run, cylinder);
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "ask_choice" }, Prompts(turn));
            Assert.Equal(new[] { "1. Cylinder" }, asking.Session.Choice.Candidates.Select(c => c.ToString()));

            asking.Session.Cancel();
            Assert.NotNull(asking.Say("a monkey").Resolve); // no shape of VoiceCore's: still runs at once
            Assert.Equal(CommandKind.Run, asking.Answer(VoiceDecision.Run, Monkey).Command?.Kind);
        }

        [Fact]
        public void AnAskDecisionAsksAndSwitchesToTheChoiceGrammar()
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            VoiceTurn asked = asking.Answer(VoiceDecision.Ask, Array, Duplicate, Subsurf);
            Assert.Null(asked.Command);
            Assert.Equal(new[] { "ask_choice" }, Prompts(asked));
            Assert.True(asked.GrammarChanged);
            Assert.Equal(new[] { "1. Array", "2. duplicate", "3. Subdivision Surface" },
                asking.Session.Choice.Candidates.Select(c => c.ToString()));
            Assert.Equal(asking.F.Now.AddSeconds(30), asking.Session.Choice.ExpiresAt);

            IReadOnlyList<string> grammar = asking.Session.GrammarPhrases();
            Assert.Equal(new[]
            {
                "one", "first", "option one", "number one", "the first one",
                "two", "second", "option two", "number two", "the second one",
                "three", "third", "option three", "number three", "the third one",
                "cancel", "never mind", "[unk]",
            }, grammar);

            VoiceTurn chosen = asking.Say("two");
            Assert.Equal(CommandKind.Run, chosen.Command.Kind);
            Assert.Equal(2, chosen.Command.Choice);
            Assert.True(chosen.GrammarChanged);
            Assert.Null(asking.Session.Choice);
            Assert.Contains("rotate", asking.Session.GrammarPhrases()); // back to the full grammar
            Assert.Null(asking.Say("two").Command); // answered once
        }

        [Theory]
        [InlineData("one", 1)]
        [InlineData("first", 1)]
        [InlineData("the first one", 1)]
        [InlineData("option one", 1)]
        [InlineData("two", 2)]
        [InlineData("second", 2)]
        [InlineData("the second one", 2)] // ordinals first: not "one"
        [InlineData("number two", 2)]
        [InlineData("2", 2)]               // the app's text box
        [InlineData("Option 2.", 2)]
        [InlineData("the third one", 3)]
        [InlineData("number three", 3)]
        [InlineData("the third", 3)]
        public void TheChoiceIsANumberOrAnOrdinal(string text, int expected)
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array, Duplicate, Subsurf);
            Assert.Equal(expected, asking.Say(text).Command.Choice);
        }

        [Theory]
        [InlineData("cancel")]
        [InlineData("never mind")]
        [InlineData("Nevermind.")]
        [InlineData("cancel that")]
        public void CancelEndsTheQuestion(string text)
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array, Duplicate);
            VoiceTurn turn = asking.Say(text);
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "cancelled" }, Prompts(turn));
            Assert.True(turn.GrammarChanged);
            Assert.Null(asking.Session.Choice);
        }

        [Theory]
        [InlineData("[unk] two")]          // Vosk's chatter while asking: never an answer
        [InlineData("[unk]")]
        [InlineData("two please")]         // only exact answers count
        [InlineData("to")]
        [InlineData("make it thicker")]
        [InlineData("three")]              // only two were offered
        public void AnythingButAnExactAnswerAsksAgain(string text)
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array, Duplicate);
            VoiceTurn turn = asking.Say(text);
            Assert.Null(turn.Command);
            Assert.Null(turn.Resolve);
            Assert.Equal(new[] { "ask_choice" }, Prompts(turn));
            Assert.NotNull(asking.Session.Choice);
            Assert.Equal(2, asking.Say("second").Command.Choice);
        }

        [Fact]
        public void AnAnswerBelowTheConfidenceThresholdIsNotTaken()
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array, Duplicate);
            Assert.Equal(new[] { "low_confidence" }, Prompts(asking.Say("one", 0.3f)));
            Assert.Equal(1, asking.Say("one", 0.9f).Command.Choice);
        }

        [Fact]
        public void TheGrammarOffersOnlyTheChoicesThereAre()
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array);
            Assert.Equal(new[] { "one", "first", "option one", "number one", "the first one", "cancel", "never mind", "[unk]" },
                asking.Session.GrammarPhrases());
        }

        [Fact]
        public void AButtonAnswersTheQuestion()
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array, Duplicate, Subsurf);
            Assert.Null(asking.Session.Choose(5).Command);
            Assert.Equal(3, asking.Session.Choose(3).Command.Choice);
            Assert.Null(asking.Session.Choose(3).Command);
        }

        [Fact]
        public void TheQuestionExpiresWithTheHostsResolution()
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Session.HostAnswered(asking.LastId, new VoiceCandidates("r", VoiceDecision.Ask, null, 10, new[] { Array, Duplicate }));
            asking.F.Wait(9);
            Assert.Empty(asking.Session.Tick().Prompts);
            asking.F.Wait(1);
            VoiceTurn turn = asking.Session.Tick();
            Assert.Equal(new[] { "timed_out" }, Prompts(turn));
            Assert.True(turn.GrammarChanged);
            Assert.Null(asking.Session.Choice);
            Assert.Null(asking.Say("one").Command); // now just a word for the host
        }

        [Fact]
        public void TheQuestionExpiresAfterThirtySecondsAtMost()
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Session.HostAnswered(asking.LastId, new VoiceCandidates("r", VoiceDecision.Ask, null, 600, new[] { Array }));
            Assert.Equal(asking.F.Now.AddSeconds(30), asking.Session.Choice.ExpiresAt);
        }

        [Fact]
        public void CancelConnectionLossAndDocumentChangeEndTheQuestion()
        {
            var asking = new Asking(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array);
            VoiceTurn cancelled = asking.Session.Cancel();
            Assert.Equal(new[] { "cancelled" }, Prompts(cancelled));
            Assert.True(cancelled.GrammarChanged);
            Assert.Null(asking.Session.Choice);

            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array);
            Assert.Equal(new[] { "connection_lost" }, Prompts(asking.Session.ConnectionLost()));
            Assert.Null(asking.Session.Choice);

            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array);
            Assert.Equal(new[] { "document_changed" }, Prompts(asking.Session.DocumentChanged()));
            Assert.Null(asking.Session.Choice);
        }

        [Fact]
        public void ADeletedTargetEndsTheQuestion()
        {
            var asking = new Asking(Cube, Sphere);
            asking.F.Select(Cube);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array);
            VoiceTurn turn = asking.Session.SetObjects(new[] { Sphere });
            Assert.Equal(new[] { "target_deleted" }, Prompts(turn));
            Assert.True(turn.GrammarChanged);
            Assert.Null(asking.Session.Choice);
        }

        // ---------- fallbacks ----------

        [Fact]
        public void ARejectIsHandledAsWithoutAHost()
        {
            var asking = new Asking(Cube);
            asking.Say("what is the weather like");
            Assert.Equal(new[] { "unsupported" }, Prompts(asking.Reject()));

            asking.Say("add a banana"); // VoiceCore asks which shape, as before
            Assert.Equal(new[] { "ask_shape" }, Prompts(asking.Reject()));
            Assert.Equal(Shape.Cube, asking.Say("cube").Command.Shape);
        }

        [Fact]
        public void TheHostsReasonIsShownWithTheFallback()
        {
            var asking = new Asking(Cube);
            asking.Say("join them");
            VoiceTurn turn = asking.Session.HostAnswered(asking.LastId,
                new VoiceCandidates("r", VoiceDecision.Reject, "Join isn't available by voice.", 30, new VoiceCandidate[0]));
            Assert.Equal(new[] { "unsupported" }, Prompts(turn));
            Assert.Equal("Join isn't available by voice.", turn.HostReason);
            Assert.Null(asking.Say("undo").HostReason);
        }

        [Fact]
        public void AnAnswerWithoutCandidatesIsAReject()
        {
            var asking = new Asking(Cube);
            asking.Say("shade smooth");
            Assert.Equal(new[] { "unsupported" }, Prompts(asking.Answer(VoiceDecision.Ask)));
        }

        [Fact]
        public void AHostWithoutVoiceIsNotAskedAgainOnThisConnection()
        {
            var asking = new Asking(Cube);
            asking.Say("shade smooth");
            Assert.Equal(new[] { "unsupported" }, Prompts(asking.Session.HostError(asking.LastId, "unknown_type")));
            VoiceTurn next = asking.Say("add a monkey");
            Assert.Null(next.Resolve);
            Assert.Equal(new[] { "ask_shape" }, Prompts(next));

            asking.Session.ConnectionLost(); // the next host may know voice.resolve
            Assert.NotNull(asking.Say("shade smooth").Resolve);
        }

        [Fact]
        public void OtherHostErrorsFallBackButKeepAsking()
        {
            var asking = new Asking(Cube);
            asking.Say("shade smooth");
            Assert.Equal(new[] { "unsupported" }, Prompts(asking.Session.HostError(asking.LastId, "busy")));
            Assert.NotNull(asking.Say("shade smooth").Resolve);
        }

        [Fact]
        public void NoAnswerWithinThreeSecondsFallsBackAndTheLateAnswerIsDropped()
        {
            var asking = new Asking(Cube);
            Assert.Equal(TimeSpan.FromSeconds(3), asking.F.Options.HostTimeout);
            asking.Say("add a monkey");
            asking.F.Wait(2.9);
            Assert.Empty(asking.Session.Tick().Prompts);
            asking.F.Wait(0.1);
            Assert.Equal(new[] { "ask_shape" }, Prompts(asking.Session.Tick()));
            Assert.False(asking.Session.WaitingForHost);

            VoiceTurn late = asking.Answer(VoiceDecision.Run, Monkey);
            Assert.Null(late.Command);
            Assert.Empty(late.Prompts);
            Assert.Equal(Shape.Sphere, asking.Say("sphere").Command.Shape); // the fallback's question still stands
        }

        [Fact]
        public void ALateAnswerFallsBackEvenWithoutATick()
        {
            var asking = new Asking(Cube);
            asking.Say("shade smooth");
            asking.F.Wait(3.5);
            VoiceTurn turn = asking.Answer(VoiceDecision.Run, Monkey);
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "unsupported" }, Prompts(turn));
        }

        [Fact]
        public void AnswersToOtherOrOlderRequestsAreDropped()
        {
            var asking = new Asking(Cube);
            asking.Say("shade smooth");
            string first = asking.LastId;
            Assert.Null(asking.Session.HostAnswered("someone-else", new VoiceCandidates("r", VoiceDecision.Run, null, 30, new[] { Monkey })).Command);
            asking.Say("add a monkey"); // newer words replace the first request
            Assert.Null(asking.Session.HostAnswered(first, new VoiceCandidates("r", VoiceDecision.Run, null, 30, new[] { Monkey })).Command);
            Assert.Equal(CommandKind.Run, asking.Answer(VoiceDecision.Run, Monkey).Command.Kind);
        }

        [Fact]
        public void ARequestThatCouldNotBeSentFallsBackAtOnce()
        {
            var f = new Fixture(Cube);
            f.Options.AskHost = true;
            VoiceTurn turn = f.Say("shade smooth");
            Assert.Equal(new[] { "unsupported" }, Prompts(f.Session.ResolveSent(turn.Resolve, null)));
            Assert.False(f.Session.WaitingForHost);
        }

        // ---------- a core command waiting for a field ----------

        [Fact]
        public void AnswersToAPendingCommandKeepPriority()
        {
            var asking = new Asking(Cube, Sphere);
            asking.F.Select(Cube);
            asking.Say("rotate this ninety degrees");
            VoiceTurn turn = asking.Say("the z axis");
            Assert.Null(turn.Resolve);
            Assert.Equal(Axis.Z, turn.Command.Axis);
        }

        [Fact]
        public void ANewHostCommandWhilePendingIsNotEatenSilently()
        {
            // The critique's case: "add" heard alone asks which shape, then "a monkey".
            var asking = new Asking(Cube);
            Assert.Equal(new[] { "ask_shape" }, Prompts(asking.Say("add")));
            VoiceTurn sent = asking.Say("a monkey");
            Assert.NotNull(sent.Resolve);
            Assert.NotNull(asking.Session.Pending); // kept until the host has understood it
            VoiceTurn run = asking.Answer(VoiceDecision.Run, Monkey);
            Assert.Equal(new[] { "replaced_pending" }, Prompts(run));
            Assert.Equal(CommandKind.Run, run.Command.Kind);
            Assert.Null(asking.Session.Pending);
        }

        [Fact]
        public void WhenTheHostRejectsThePendingCommandAsksAgainAsBefore()
        {
            var asking = new Asking(Cube);
            asking.F.Select(Cube);
            asking.Say("rotate this ninety degrees");
            Assert.NotNull(asking.Say("shade smooth").Resolve);
            Assert.Equal(new[] { "ask_axis" }, Prompts(asking.Reject()));
            Assert.Equal(Axis.X, asking.Say("x").Command.Axis);
        }

        [Fact]
        public void WhileThePendingCommandNeedsItsObjectUnknownWordsAreAName()
        {
            var asking = new Asking(Cube, Sphere);
            asking.Say("rotate this ninety degrees around z");
            VoiceTurn turn = asking.Say("the banana");
            Assert.Null(turn.Resolve);
            Assert.Equal(new[] { "unknown_object", "ask_target" }, Prompts(turn));
            Assert.Null(asking.Say("select the banana").Resolve);
        }

        [Fact]
        public void AHostQuestionReplacesThePendingCommand()
        {
            var asking = new Asking(Cube);
            asking.F.Select(Cube);
            asking.Say("rotate this ninety degrees");
            asking.Say("make it thicker");
            Assert.Equal(new[] { "replaced_pending", "ask_choice" }, Prompts(asking.Answer(VoiceDecision.Ask, Array, Duplicate)));
            Assert.Null(asking.Session.Pending);
        }

        // ---------- confidence ----------

        [Fact]
        public void LowConfidenceWordsStillReachTheHostButOnlyAsAQuestion()
        {
            // Vosk gives "two" 0.46 to 0.50 because "to" is in the grammar too.
            var asking = new Asking(Cube);
            VoiceTurn sent = asking.Say("subdivide it level two", 0.46f);
            Assert.NotNull(sent.Resolve);
            Assert.True(sent.Resolve.LowConfidence);
            Assert.Equal(0.46f, sent.Resolve.Confidence);
            var levelTwo = new VoiceCandidate(1, "Subdivision Surface", "object.modifier_add", needsTarget: true);
            VoiceTurn asked = asking.Answer(VoiceDecision.Run, levelTwo); // a host must not run it; if it does, VoiceCore asks
            Assert.Null(asked.Command);
            Assert.Equal(new[] { "ask_choice" }, Prompts(asked));
            Assert.Equal(1, asking.Say("one").Command.Choice);
        }

        [Fact]
        public void LowConfidenceCoreCommandsAreStillRejected()
        {
            var asking = new Asking(Cube);
            VoiceTurn turn = asking.Say("undo", 0.3f);
            Assert.Null(turn.Resolve);
            Assert.Equal(new[] { "low_confidence" }, Prompts(turn));

            asking.Say("shade smooth", 0.3f);
            Assert.Equal(new[] { "low_confidence" }, Prompts(asking.Reject())); // the fallback is today's answer
        }

        // ---------- grammar ----------

        [Fact]
        public void TheHostsPhrasesAreMergedIntoTheGrammar()
        {
            var asking = new Asking(Cube);
            asking.Session.SetHostGrammar(new[] { "add a monkey", "Shade Smooth", "subdivide level 2", "rotate", "[unk]", "  " });
            IReadOnlyList<string> grammar = asking.Session.GrammarPhrases();
            foreach (string phrase in new[] { "add a monkey", "shade smooth", "subdivide level two", "rotate", "cube", "ninety" })
                Assert.Contains(phrase, grammar);
            Assert.Equal("[unk]", grammar.Last());
            Assert.Equal(grammar.Count, grammar.Distinct().Count());
            Assert.Single(grammar, "[unk]");

            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array);
            Assert.DoesNotContain("add a monkey", asking.Session.GrammarPhrases()); // only the answers while asking

            Assert.True(asking.Session.ConnectionLost().GrammarChanged);
            Assert.DoesNotContain("add a monkey", asking.Session.GrammarPhrases()); // the next host sends its own
        }

        [Fact]
        public void WithoutHostPhrasesTheGrammarIsTodays()
        {
            var asking = new Asking(Cube);
            Assert.Equal(Vocabulary.GrammarPhrases(new[] { "Cube" }), asking.Session.GrammarPhrases());
            Assert.Contains("to", asking.Session.GrammarPhrases());
        }

        [Fact]
        public void WithHostPhrasesToLeavesTheGrammarSoTwoIsHeard()
        {
            var asking = new Asking(Cube);
            asking.Session.SetHostGrammar(new[] { "subdivide level two" });
            Assert.DoesNotContain("to", asking.Session.GrammarPhrases());
            Assert.Contains("two", asking.Session.GrammarPhrases());
            Assert.Equal(0.5, asking.Say("scale this to fifty percent").Command.Factor.Value, 9); // typed "to" still parses
        }

        [Fact]
        public void AHostWithoutVoiceGetsNoRequests()
        {
            var asking = new Asking(Cube);
            asking.Session.HostHasNoVoice(); // voice.grammar_query answered unknown_type
            Assert.Equal(new[] { "unsupported" }, Prompts(asking.Say("shade smooth")));
            asking.Session.ConnectionLost();
            Assert.NotNull(asking.Say("shade smooth").Resolve);
            Assert.Equal("voice.grammar_query", VoiceGrammar.QueryType);
        }

        [Fact]
        public void AnswersNeedTheChoiceConfidence()
        {
            // Measured on real speech: 0.9 keeps the answers and halves the other words taken as answers.
            var asking = new Asking(Cube);
            Assert.Equal(0.9f, asking.F.Options.ChoiceMinConfidence);
            asking.Say("make copies");
            asking.Answer(VoiceDecision.Ask, Array, Duplicate);
            Assert.Equal(new[] { "low_confidence" }, Prompts(asking.Say("two", 0.85f)));
            Assert.Equal(2, asking.Say("two", 0.9f).Command.Choice);
        }
    }
}
