using System;
using Xunit;
using static SpatialModeling.VoiceCore.Tests.Fixture;

namespace SpatialModeling.VoiceCore.Tests
{
    public class VoiceSessionTests
    {
        [Fact]
        public void PlanExampleDialogueExecutesTheRetainedCommandOnce()
        {
            var f = new Fixture(Cube, Sphere, Cylinder);

            VoiceTurn asked = f.Say("rotate this object ninety degrees");
            Assert.Null(asked.Command);
            Assert.Equal(new[] { "ask_target" }, Prompts(asked));
            Assert.Equal("Please select or point at the object you are referring to.", asked.Prompts[0].Text);
            Assert.Equal(MissingFields.Target | MissingFields.Axis, f.Session.Pending.Missing);
            Assert.Equal(90, f.Session.Pending.Command.Amount.Value);

            VoiceTurn selected = f.Select(Sphere);
            Assert.Null(selected.Command);
            Assert.Equal(new[] { "ask_axis" }, Prompts(selected));
            Assert.Equal("Which axis: X, Y or Z?", selected.Prompts[0].Text);
            Assert.Equal(Sphere.Id, f.Session.Pending.Command.TargetId);

            VoiceTurn done = f.Say("z");
            Assert.Empty(done.Prompts);
            Assert.Equal(CommandKind.Rotate, done.Command.Kind);
            Assert.Equal(Sphere.Id, done.Command.TargetId);
            Assert.Equal(Axis.Z, done.Command.Axis);
            Assert.Equal(Math.PI / 2, done.Command.Radians.Value, 9);
            Assert.Null(f.Session.Pending);

            // Saying the answer again does not execute a second time.
            VoiceTurn again = f.Say("z");
            Assert.Null(again.Command);
            Assert.Equal(new[] { "unsupported" }, Prompts(again));
        }

        [Fact]
        public void ResolvesThisBySelectionThenPointerThenSoleObject()
        {
            var f = new Fixture(Cube, Sphere);
            f.Select(Cube);
            f.Session.SetPointerTarget(Sphere.Id);
            Assert.Equal(Cube.Id, f.Say("rotate this ninety degrees around x").Command.TargetId);

            f.Select();
            Assert.Equal(Sphere.Id, f.Say("rotate it ninety degrees around x").Command.TargetId);

            var single = new Fixture(Cylinder);
            Assert.Equal(Cylinder.Id, single.Say("delete this").Command.TargetId);
        }

        [Fact]
        public void SeveralSelectedObjectsAreAQuestion()
        {
            var f = new Fixture(Cube, Sphere);
            f.Select(Cube, Sphere);
            VoiceTurn turn = f.Say("delete this");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "ask_target" }, Prompts(turn));
            Assert.Equal(Cube.Id, f.Select(Cube).Command.TargetId);
        }

        [Fact]
        public void SeveralSelectedObjectsAreAQuestionEvenWithAPointerTarget()
        {
            var f = new Fixture(Cube, Sphere);
            f.Session.SetPointerTarget(Sphere.Id);
            f.Select(Cube, Sphere);
            VoiceTurn turn = f.Say("delete this");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "ask_target" }, Prompts(turn));
        }

        [Fact]
        public void ASelectedObjectThatIsNotEligibleIsAQuestion()
        {
            // The camera is selected but not among the objects; the sole eligible object must not take its place.
            var f = new Fixture(Cube);
            f.Session.SetSelection(new[] { "id-camera" });
            VoiceTurn turn = f.Say("delete this");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "ask_target" }, Prompts(turn));

            // A selection that contains it alongside an eligible object is not a single object either.
            var g = new Fixture(Cube, Sphere);
            g.Session.SetSelection(new[] { Cube.Id, "id-camera" });
            Assert.Equal(new[] { "ask_target" }, Prompts(g.Say("delete this")));
            Assert.Equal(Cube.Id, g.Select(Cube).Command.TargetId);
        }

        [Fact]
        public void SelectingByVoiceIgnoresTheCurrentSelection()
        {
            var f = new Fixture(Cube, Sphere);
            f.Select(Cube);
            f.Session.SetPointerTarget(Sphere.Id);
            Assert.Equal(Sphere.Id, f.Say("select this").Command.TargetId);
        }

        [Fact]
        public void ResolvedTargetIsShownWhilePending()
        {
            var f = new Fixture(Cube, Sphere);
            f.Select(Cube);
            f.Say("rotate this ninety degrees");
            Assert.Equal("Cube", f.Session.Pending.Command.TargetName);
            Assert.Equal("Rotate Cube 90 degrees around ?", f.Session.Pending.Command.ToString());
        }

        [Fact]
        public void PointingAnswersTheTargetQuestionAfterADwell()
        {
            var f = new Fixture(Cube, Sphere);
            Assert.Equal(new[] { "ask_target" }, Prompts(f.Say("rotate this ninety degrees around z")));

            f.Session.SetPointerTarget(Cube.Id);
            f.Wait(0.2);
            Assert.Null(f.Session.SetPointerTarget(Sphere.Id).Command); // ray sweeping across objects
            f.Wait(0.3);
            Assert.Null(f.Session.Tick().Command);
            f.Wait(0.3);
            VoiceTurn turn = f.Session.Tick();
            Assert.Equal(Sphere.Id, turn.Command.TargetId);
        }

        [Fact]
        public void ThisOneWhilePointingAnswersTheTargetWithoutBecomingAnAmount()
        {
            var f = new Fixture(Cube, Sphere);
            Assert.Equal(new[] { "ask_target" }, Prompts(f.Say("rotate it")));
            f.Session.SetPointerTarget(Sphere.Id);
            VoiceTurn turn = f.Say("this one");
            Assert.Equal(new[] { "ask_axis" }, Prompts(turn));
            Assert.Equal(Sphere.Id, f.Session.Pending.Command.TargetId);
            Assert.Null(f.Session.Pending.Command.Amount);
        }

        [Fact]
        public void AsksOnlyForTheMissingAxis()
        {
            var f = new Fixture(Cube, Sphere);
            f.Select(Cube);
            VoiceTurn asked = f.Say("rotate this by forty five degrees");
            Assert.Equal(new[] { "ask_axis" }, Prompts(asked));
            Assert.Equal(MissingFields.Axis, f.Session.Pending.Missing);

            VoiceTurn done = f.Say("around the x axis");
            Assert.Equal(Axis.X, done.Command.Axis);
            Assert.Equal(Math.PI / 4, done.Command.Radians.Value, 9);
        }

        [Fact]
        public void NegativeAxisAnswerFlipsTheRetainedAngle()
        {
            var f = new Fixture(Cube);
            f.Say("rotate it ninety degrees");
            VoiceCommand command = f.Say("negative z").Command;
            Assert.Equal(-Math.PI / 2, command.Radians.Value, 9);
        }

        [Theory]
        [InlineData("move this ten millimeters along x", Axis.X, 0.01)]
        [InlineData("move this ten centimeters along y", Axis.Y, 0.1)]
        [InlineData("move this one point five meters along z", Axis.Z, 1.5)]
        [InlineData("move it minus five centimeters along x", Axis.X, -0.05)]
        [InlineData("move it ten centimeters along negative x", Axis.X, -0.1)]
        [InlineData("move it up ten centimeters", Axis.Z, 0.1)]
        [InlineData("move it down twenty five millimeters", Axis.Z, -0.025)]
        [InlineData("Move it 25 cm along the X axis.", Axis.X, 0.25)]
        public void MoveNormalizesExplicitUnitsToMeters(string text, Axis axis, double meters)
        {
            var f = new Fixture(Cube);
            VoiceCommand command = f.Say(text).Command;
            Assert.Equal(CommandKind.Move, command.Kind);
            Assert.Equal(axis, command.Axis);
            Assert.Equal(meters, command.Meters.Value, 9);
        }

        [Fact]
        public void MoveWithoutAUnitAsksForTheUnit()
        {
            var f = new Fixture(Cube);
            Assert.Equal(new[] { "ask_unit" }, Prompts(f.Say("move it ten along x")));
            Assert.Equal(0.1, f.Say("centimeters").Command.Meters.Value, 9);
        }

        [Theory]
        [InlineData("move it ninety degrees along x", "wrong_unit_distance", "ask_distance")]
        [InlineData("rotate it ten centimeters around z", "wrong_unit_angle", "ask_angle")]
        [InlineData("scale it by ten meters", "wrong_unit_factor", "ask_factor")]
        public void WrongUnitsExplainAndAskForTheAmountAgain(string text, string notice, string question)
        {
            var f = new Fixture(Cube);
            VoiceTurn turn = f.Say(text);
            Assert.Null(turn.Command);
            Assert.Equal(new[] { notice, question }, Prompts(turn));
            Assert.Equal(MissingFields.Amount, f.Session.Pending.Missing & MissingFields.Amount);
        }

        [Fact]
        public void WrongUnitKeepsTheRestAndAcceptsACorrectedAmount()
        {
            var f = new Fixture(Cube);
            f.Say("move it ninety degrees along y");
            VoiceCommand command = f.Say("ten centimeters").Command;
            Assert.Equal(Axis.Y, command.Axis);
            Assert.Equal(0.1, command.Meters.Value, 9);
        }

        [Theory]
        [InlineData("move it twenty meters along x")]
        [InlineData("rotate it five hundred degrees around x")]
        [InlineData("scale it by zero")]
        public void OutOfRangeAmountsNeverExecute(string text)
        {
            var f = new Fixture(Cube);
            VoiceTurn turn = f.Say(text);
            Assert.Null(turn.Command);
            Assert.Equal("out_of_range", turn.Prompts[0].Id);
        }

        [Theory]
        [InlineData("move it minus twenty meters along x", "minus ten centimeters", -0.1)]
        [InlineData("move it minus twenty meters along x", "ten centimeters", 0.1)]
        [InlineData("move it twenty meters along negative x", "ten centimeters", -0.1)]
        [InlineData("move it twenty meters along negative x", "minus ten centimeters", 0.1)]
        [InlineData("move it down twenty meters", "five centimeters", -0.05)]
        public void ACorrectedAmountBringsItsOwnSignAndKeepsTheAxisDirection(string first, string answer, double meters)
        {
            var f = new Fixture(Cube);
            Assert.Equal(new[] { "out_of_range", "ask_distance" }, Prompts(f.Say(first)));
            Assert.Equal(meters, f.Say(answer).Command.Meters.Value, 9);
        }

        [Fact]
        public void ACorrectedAmountAsksForItsUnitAgain()
        {
            var f = new Fixture(Cube);
            f.Say("move it twenty meters along x");
            Assert.Equal(new[] { "ask_unit" }, Prompts(f.Say("five")));
            Assert.Equal(0.05, f.Say("centimeters").Command.Meters.Value, 9);

            f.Say("scale it by zero percent");
            Assert.Equal(2.0, f.Say("two").Command.Factor.Value, 9); // two times, not two percent
        }

        [Fact]
        public void NegationsBelongToTheFollowingAxisOrNumber()
        {
            var f = new Fixture(Cube);
            Assert.Equal(-0.1, f.Say("move it minus ten centimeters along x").Command.Meters.Value, 9);
            Assert.Equal(0.1, f.Say("move it minus ten centimeters along negative x").Command.Meters.Value, 9);
            Assert.Equal(-0.1, f.Say("move it ten centimeters along the negative x axis").Command.Meters.Value, 9);
            Assert.Equal(0.1, f.Say("move it minus minus ten centimeters along x").Command.Meters.Value, 9);
            Assert.Equal(0.05, f.Say("move it down minus five centimeters").Command.Meters.Value, 9);
            Assert.Equal(-Math.PI / 2, f.Say("rotate it minus ninety degrees around z").Command.Radians.Value, 9);
        }

        [Theory]
        [InlineData("scale this two fifty percent", "ask_factor")] // Vosk heard "to fifty" as "two fifty"
        [InlineData("rotate it one eighty degrees around z", "ask_angle")]
        public void TwoNumbersAreAmbiguousAndAskForTheAmount(string text, string question)
        {
            var f = new Fixture(Cube);
            VoiceTurn turn = f.Say(text);
            Assert.Null(turn.Command);
            Assert.Equal(new[] { question }, Prompts(turn));
        }

        [Theory]
        [InlineData("scale this by two", 2.0)]
        [InlineData("scale it to fifty percent", 0.5)]
        [InlineData("scale it by one point five", 1.5)]
        [InlineData("scale it three times", 3.0)]
        public void ScaleUsesAUniformFactor(string text, double factor)
        {
            var f = new Fixture(Cube);
            VoiceCommand command = f.Say(text).Command;
            Assert.Equal(CommandKind.Scale, command.Kind);
            Assert.Equal(factor, command.Factor.Value, 9);
        }

        [Fact]
        public void LowConfidenceNeverProducesACommand()
        {
            var f = new Fixture(Cube, Sphere);
            VoiceTurn turn = f.Say("undo", 0.3f);
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "low_confidence" }, Prompts(turn));

            f.Select(Cube);
            f.Say("rotate this ninety degrees");
            Assert.Null(f.Say("z", 0.3f).Command);
            Assert.Equal(MissingFields.Axis, f.Session.Pending.Missing);
            Assert.NotNull(f.Say("z", 0.9f).Command);
        }

        [Fact]
        public void ConfidenceThresholdIsConfigurable()
        {
            var f = new Fixture(Cube);
            f.Options.MinConfidence = 0.2f;
            Assert.Equal(CommandKind.Undo, f.Say("undo", 0.3f).Command.Kind);
        }

        [Fact]
        public void CancelClearsThePendingCommand()
        {
            var f = new Fixture(Cube, Sphere);
            f.Say("rotate this ninety degrees around z");
            VoiceTurn turn = f.Say("cancel");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "cancelled" }, Prompts(turn));
            Assert.Null(f.Session.Pending);
            Assert.Null(f.Select(Cube).Command);

            f.Select();
            f.Say("rotate this ninety degrees around z");
            Assert.Equal(new[] { "cancelled" }, Prompts(f.Session.Cancel()));
            Assert.Null(f.Select(Cube).Command);
        }

        [Fact]
        public void CancelWithNothingPendingCancelsTheUiDraft()
        {
            var f = new Fixture(Cube);
            Assert.Equal(CommandKind.Cancel, f.Say("cancel").Command.Kind);
            Assert.Equal(CommandKind.Apply, f.Say("apply").Command.Kind);
        }

        [Fact]
        public void PendingCommandTimesOut()
        {
            var f = new Fixture(Cube, Sphere);
            f.Say("rotate this ninety degrees around z");
            Assert.Equal(f.Now.AddSeconds(30), f.Session.Pending.ExpiresAt);

            f.Wait(29);
            Assert.Empty(f.Session.Tick().Prompts);
            f.Wait(2);
            Assert.Equal(new[] { "timed_out" }, Prompts(f.Session.Tick()));
            Assert.Null(f.Session.Pending);
            Assert.Null(f.Select(Cube).Command);
        }

        [Fact]
        public void LateAnswerAfterTimeoutDoesNotExecute()
        {
            var f = new Fixture(Cube);
            f.Say("rotate it ninety degrees");
            f.Wait(31);
            VoiceTurn turn = f.Say("z");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "timed_out", "unsupported" }, Prompts(turn));
        }

        [Fact]
        public void NewCommandReplacesThePendingOneExplicitly()
        {
            var f = new Fixture(Cube, Sphere);
            f.Say("rotate this ninety degrees");
            VoiceTurn turn = f.Say("add a sphere");
            Assert.Equal(new[] { "replaced_pending" }, Prompts(turn));
            Assert.Equal(CommandKind.AddShape, turn.Command.Kind);
            Assert.Equal(Shape.Sphere, turn.Command.Shape);
            Assert.Null(f.Session.Pending);
            Assert.Null(f.Select(Cube).Command); // the dropped rotate never runs

            f.Say("rotate this ninety degrees");
            VoiceTurn move = f.Say("move it ten centimeters along x");
            Assert.Equal(CommandKind.Move, move.Command.Kind);
            Assert.Equal(new[] { "replaced_pending" }, Prompts(move));
        }

        [Fact]
        public void AnswersOnlyFillMissingFields()
        {
            var f = new Fixture(Cube);
            f.Say("rotate it ninety degrees");
            VoiceCommand command = f.Say("forty five degrees around z").Command;
            Assert.Equal(90, command.Amount.Value);
        }

        [Fact]
        public void DeletedTargetCancelsThePendingCommand()
        {
            var f = new Fixture(Cube, Sphere);
            Assert.Equal(new[] { "ask_axis" }, Prompts(f.Say("rotate the cube ninety degrees")));
            Assert.Equal(Cube.Id, f.Session.Pending.Command.TargetId);

            VoiceTurn turn = f.Session.SetObjects(new[] { Sphere });
            Assert.Equal(new[] { "target_deleted" }, Prompts(turn));
            Assert.Null(f.Session.Pending);
            Assert.Null(f.Say("z").Command);
        }

        [Fact]
        public void DocumentChangeClearsPendingState()
        {
            var f = new Fixture(Cube, Sphere);
            f.Say("rotate this ninety degrees");
            Assert.Equal(new[] { "document_changed" }, Prompts(f.Session.DocumentChanged()));
            Assert.Null(f.Session.Pending);
            Assert.Empty(f.Session.Objects);
        }

        [Fact]
        public void LostConnectionClearsThePendingCommandButKeepsTheObjects()
        {
            var f = new Fixture(Cube, Sphere);
            f.Say("rotate this ninety degrees");
            Assert.Equal(new[] { "connection_lost" }, Prompts(f.Session.ConnectionLost()));
            Assert.Null(f.Session.Pending);
            Assert.Equal(2, f.Session.Objects.Count);
            Assert.Null(f.Select(Cube).Command);
            Assert.Empty(f.Session.ConnectionLost().Prompts);
        }

        [Theory]
        [InlineData("undo", CommandKind.Undo)]
        [InlineData("redo", CommandKind.Redo)]
        public void UndoAndRedoNeedNoTarget(string text, CommandKind kind)
        {
            var f = new Fixture(Cube, Sphere);
            VoiceTurn turn = f.Say(text);
            Assert.Empty(turn.Prompts);
            Assert.Equal(kind, turn.Command.Kind);
            Assert.Null(turn.Command.TargetId);
        }

        [Fact]
        public void SelectsByVisibleName()
        {
            var cube1 = new SceneObject("id-1", "Cube.001");
            var cube2 = new SceneObject("id-2", "Cube.002");
            var f = new Fixture(cube1, cube2, Sphere);

            VoiceCommand command = f.Say("select cube two").Command;
            Assert.Equal(CommandKind.Select, command.Kind);
            Assert.Equal("id-2", command.TargetId);
            Assert.Equal("id-sphere", f.Say("select the sphere").Command.TargetId);

            VoiceTurn ambiguous = f.Say("select the cube");
            Assert.Equal(new[] { "ambiguous_name", "ask_target" }, Prompts(ambiguous));
            Assert.Equal("id-1", f.Select(cube1).Command.TargetId);

            Assert.Equal(new[] { "unknown_object", "ask_target" }, Prompts(f.Say("select the banana")));
        }

        [Fact]
        public void SpokenNameAnswersTheTargetQuestion()
        {
            var f = new Fixture(Cube, Sphere);
            f.Say("rotate this ninety degrees around z");
            Assert.Equal(Sphere.Id, f.Say("the sphere").Command.TargetId);

            f.Say("rotate this ninety degrees around z");
            Assert.Equal(Cube.Id, f.Say("select the cube").Command.TargetId);
        }

        [Fact]
        public void UnknownNameAsksInsteadOfUsingTheSelection()
        {
            var f = new Fixture(Cube, Sphere);
            f.Select(Cube);
            VoiceTurn turn = f.Say("rotate the cylinder ninety degrees around z");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "unknown_object", "ask_target" }, Prompts(turn));
        }

        [Fact]
        public void UnrecognizedSpeechDuringAQuestionDoesNotFillIt()
        {
            var f = new Fixture(Cube, Sphere);
            f.Say("rotate this ninety degrees around z");
            f.Session.SetPointerTarget(Cube.Id);
            VoiceTurn turn = f.Say("[unk]");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "unknown_object", "ask_target" }, Prompts(turn));
        }

        [Fact]
        public void AddShapeAsksForTheShape()
        {
            var f = new Fixture();
            Assert.Equal(Shape.Cube, f.Say("add a cube").Command.Shape);
            Assert.Equal(new[] { "ask_shape" }, Prompts(f.Say("create")));
            Assert.Equal(Shape.Cylinder, f.Say("cylinder").Command.Shape);
        }

        [Fact]
        public void DeleteRequiresConfirmationInTheUi()
        {
            var f = new Fixture(Cube);
            VoiceCommand command = f.Say("delete it").Command;
            Assert.Equal(CommandKind.Delete, command.Kind);
            Assert.True(command.RequiresConfirmation);
        }

        [Fact]
        public void IgnoresSpeechWhilePromptPlays()
        {
            var f = new Fixture(Cube);
            f.Session.SetPromptPlaying(true);
            VoiceTurn turn = f.Say("undo");
            Assert.Null(turn.Command);
            Assert.Empty(turn.Prompts);
            f.Session.SetPromptPlaying(false);
            Assert.NotNull(f.Say("undo").Command);
        }

        [Fact]
        public void EmptyResultsAreIgnored()
        {
            var f = new Fixture(Cube);
            Assert.Empty(f.Session.Hear(default(RecognitionResult)).Prompts);
            Assert.Empty(f.Say("  ").Prompts);
        }

        [Fact]
        public void UnsupportedWordingGivesAnExample()
        {
            var f = new Fixture(Cube);
            VoiceTurn turn = f.Say("what is the weather like");
            Assert.Null(turn.Command);
            Assert.Equal(new[] { "unsupported" }, Prompts(turn));
            Assert.Contains("rotate this object", turn.Prompts[0].Text);
        }

        [Fact]
        public void AcceptsDictationStyleText()
        {
            var f = new Fixture(Cube, Sphere);
            f.Select(Sphere);
            VoiceCommand command = f.Say("Okay, rotate the object -90° around the Z axis.").Command;
            Assert.Equal(Sphere.Id, command.TargetId);
            Assert.Equal(-Math.PI / 2, command.Radians.Value, 9);
        }

        [Fact]
        public void PromptIdsAreUniqueAndHaveText()
        {
            var ids = new System.Collections.Generic.HashSet<string>();
            foreach (Prompt prompt in Prompt.All)
            {
                Assert.True(ids.Add(prompt.Id), prompt.Id);
                Assert.False(string.IsNullOrWhiteSpace(prompt.Text));
            }
        }
    }
}
