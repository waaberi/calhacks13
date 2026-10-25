using System;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    public class ExternalRecipeTests
    {
        [Theory]
        [InlineData("add cube but ignore this unsupported tail")]
        [InlineData("inset the selected faces")]
        [InlineData("make the edge rounded")]
        public void ExternalRecipeAlwaysUsesWholeHostResolutionAndNeverFallsBack(string text)
        {
            var now=DateTime.UtcNow;
            var session=new VoiceSession(new VoiceSessionOptions { AskHost=true },()=>now);
            var turn=session.ResolveRecipe(text);
            Assert.Null(turn.Command); Assert.Equal(text,turn.Resolve.Text); Assert.True(turn.Resolve.Composition);
            session.ResolveSent(turn.Resolve,"recipe");
            turn=session.HostError("recipe","busy");
            Assert.Null(turn.Command); Assert.Null(turn.Resolve); Assert.Contains(Prompt.Failed,turn.Prompts);
            turn=session.ResolveRecipe(text);session.ResolveSent(turn.Resolve,"timeout");now=now.AddSeconds(10);
            Assert.Null(session.Tick().Command);
        }

        [Fact]
        public void HostPreparedRecipeRequiresControllerConfirmationAndActualTarget()
        {
            const string id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
            var s=new VoiceSession();s.SetObjects(new[]{new SceneObject(id,"Cube")});
            var t=s.ResolveRecipe("inset selected faces two millimeters");s.ResolveSent(t.Resolve,"r");
            t=s.HostAnswered("r",new VoiceCandidates(id,VoiceDecision.Run,"Review all steps",30,
                new[]{new VoiceCandidate(1,"Inset 2mm","voice.recipe",true,true,id)}));
            Assert.Equal(CommandKind.Run,t.Command.Kind);Assert.True(t.Command.RequiresConfirmation);Assert.Equal(id,t.Command.TargetId);
        }
    }
}
