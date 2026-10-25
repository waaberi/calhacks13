using System;
using Xunit;
using static SpatialModeling.VoiceCore.Tests.Fixture;

namespace SpatialModeling.VoiceCore.Tests
{
    public class AxisRoutingRegressionTests
    {
        [Theory]
        [InlineData("x",Axis.X)][InlineData("ex axis",Axis.X)]
        [InlineData("y",Axis.Y)][InlineData("why",Axis.Y)][InlineData("the why axis",Axis.Y)]
        [InlineData("z",Axis.Z)][InlineData("zee",Axis.Z)][InlineData("zed axis",Axis.Z)]
        [InlineData("z i mean y",Axis.Y)][InlineData("x actually z",Axis.Z)]
        public void PendingRotationAcceptsAxisSpeechAndCorrectionOnce(string answer,Axis expected)
        {
            var f=new Fixture(Cube,Sphere);f.Options.AskHost=true;f.Select(Cube);
            Assert.Null(f.Say("rotate this object ninety degrees").Command);
            var done=f.Say(answer);Assert.NotNull(done.Command);Assert.Equal(AxisKind(done),expected);
            Assert.Equal(Cube.Id,done.Command.TargetId);Assert.Equal(Math.PI/2,done.Command.Radians.Value,9);
            Assert.Null(f.Session.Pending);Assert.Null(f.Say(answer).Command);
        }
        static Axis AxisKind(VoiceTurn turn)=>turn.Command.Axis.Value;
        [Theory][InlineData("x",Axis.X)][InlineData("why",Axis.Y)][InlineData("zee",Axis.Z)]
        public void PendingMovePreservesAmountUnitTargetAndAxis(string answer,Axis expected)
        {
            var f=new Fixture(Cube,Sphere);f.Options.AskHost=true;f.Select(Sphere);
            f.Say("move this object ten centimeters");
            var turn=f.Say(answer);Assert.NotNull(turn.Command);Assert.Equal(expected,turn.Command.Axis);
            Assert.Equal(.1,turn.Command.Meters.Value,9);Assert.Equal(Sphere.Id,turn.Command.TargetId);
        }
        [Fact] public void HomophonesCannotExecuteOutsideAxisSlotOrAfterExpiryOrLowConfidence()
        {
            var f=new Fixture(Cube);f.Options.AskHost=true;Assert.Null(f.Say("why").Command);
            f.Say("rotate Cube ninety degrees");Assert.Null(f.Say("why",.1f).Command);
            f.Wait(31);Assert.Null(f.Say("why").Command);
            f.Say("move Cube along x");Assert.Null(f.Say("why").Command);
        }
        [Theory][InlineData("x y")][InlineData("why then delete Cube")][InlineData("z i mean y then export")]
        public void AxisAnswerCannotDropAmbiguityOrAnotherClause(string text)
        {Assert.Null(AxisClarification.Normalize(text));}
        [Theory]
        [InlineData("move Cube ten centimeters along x")][InlineData("move Cube ten centimeters along y")]
        [InlineData("move Cube ten centimeters along z")][InlineData("rotate Cube ninety degrees about y")]
        [InlineData("move Cube ten centimeters along x then rotate it forty five degrees around z")]
        [InlineData("move Cube ten centimeters along x and move it five centimeters along z")]
        [InlineData("move Cube ten centimeters along x then export it")]
        public void EveryModelingRequestAndWholeTailUsesGeminiWhenAvailable(string text)
        {Assert.Equal(VoiceRoute.Gemini,VoiceRouting.Decide(text,true,true,false));}
        [Theory][InlineData("undo that")][InlineData("redo that rotate")][InlineData("cancel")]
        [InlineData("save project")][InlineData("select Cube")]
        public void ImmediateControlsKeepLocalAuthority(string text)
        {Assert.Equal(VoiceRoute.Core,VoiceRouting.Decide(text,true,true,false));}
        [Fact] public void OfflineAndPendingAxisDialogueRemainSupportedButNewChainsReplaceIt()
        {
            Assert.Equal(VoiceRoute.Core,VoiceRouting.Decide("move Cube ten centimeters along y",true,false,false));
            Assert.Equal(VoiceRoute.Core,VoiceRouting.Decide("why",true,true,true));
            Assert.Equal(VoiceRoute.Gemini,VoiceRouting.Decide("move Cube ten centimeters along y then scale it by two",true,true,true));
        }
    }
}
