using System;
using System.Linq;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    public class CompositionTests
    {
        const string A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        DateTime now = new DateTime(2026, 10, 25, 0, 0, 0, DateTimeKind.Utc);
        VoiceSession New(bool enabled = true)
        {
            var s = new VoiceSession(new VoiceSessionOptions { AskHost = true }, () => now);
            s.SetObjects(new[] { new SceneObject(A, "Cube"), new SceneObject(B, "Sphere") });
            s.EnableComposition(enabled);
            return s;
        }
        static VoiceTurn Begin(VoiceSession s, string text, string id = "request")
        {
            VoiceTurn t = s.Hear(new RecognitionResult(text, 1));
            Assert.Null(t.Command); Assert.NotNull(t.Resolve);
            s.ResolveSent(t.Resolve, id); return t;
        }
        static VoiceTurn Clarify(VoiceSession s, string field, string id = "request") =>
            s.HostAnswered(id, new VoiceCandidates(A, VoiceDecision.Clarify, "Step 1: " + field, 30, null, field));

        [Theory]
        [InlineData("add cube then rotate it forty five degrees around x")]
        [InlineData("apply rotation and scale")]
        [InlineData("shade smooth and move it one centimeter along x")]
        [InlineData("scale it down twenty percent")]
        [InlineData("scale it by negative one along x")]
        [InlineData("scale it along z by two")]
        [InlineData("colour it purple")]
        [InlineData("make it darker")]
        [InlineData("duplicate it ten centimeters along y")]
        [InlineData("set its height twenty millimeters")]
        [InlineData("reset its rotation")]
        [InlineData("add cube at x twenty centimeters")]
        public void EntireNewSyntaxGoesToCapabilityAdvertisedHost(string text)
        {
            var s = New(); var t = Begin(s, text);
            Assert.Equal(text, t.Resolve.Text);
        }

        [Theory]
        [InlineData("add cube then teleport it")]
        [InlineData("add cube and teleport it")]
        [InlineData("add cube and sing")]
        [InlineData("shade smooth and teleport it")]
        [InlineData("add cube then cancel")]
        [InlineData("add cube then delete it")]
        public void RejectionAndTransportTimeoutNeverExecuteAPrefix(string text)
        {
            var s = New(); Begin(s, text);
            var t = s.HostAnswered("request", new VoiceCandidates(A, VoiceDecision.Reject, "No", 30, null));
            Assert.Null(t.Command); Assert.Null(t.Resolve);
            Begin(s, text); now = now.AddSeconds(4); t = s.Tick();
            Assert.Null(t.Command); Assert.Null(s.CompositionQuestion);
        }

        [Fact]
        public void StandaloneAndPreservesUnknownTailAndCannotFallBackAfterTransportFailure()
        {
            const string text = "add cube and teleport it";
            var s = New(); var t = Begin(s, text);
            Assert.True(t.Resolve.Composition);
            Assert.Equal(text, t.Resolve.Text);
            t = s.HostError("request", "busy");
            Assert.Null(t.Command); Assert.Null(t.Resolve);
            Assert.Contains(Prompt.Failed, t.Prompts);
            Assert.False(VoiceSession.IsCompositionRequest("select Candy"));
        }

        [Fact]
        public void ControllerSelectionAndFieldAnswerResumeTheSamePlan()
        {
            var s=New(); Begin(s,"move it ten centimeters then colour it blue");
            Clarify(s,"target");
            var t=s.SetSelection(new[]{ B });
            Assert.Equal(A,t.Resolve.Continuation); Assert.Equal(B,t.Resolve.TargetId);
            Assert.Equal(A,t.Resolve.Payload(0)["continuation"]);
            s.ResolveSent(t.Resolve,"selected"); Clarify(s,"axis","selected");
            t=s.Hear(new RecognitionResult("x",1)); Assert.Equal(A,t.Resolve.Continuation);
            s.ResolveSent(t.Resolve,"axis");
            t=s.HostAnswered("axis",new VoiceCandidates(A,VoiceDecision.Run,null,30,
                new[]{new VoiceCandidate(1,"Move Sphere; colour Sphere blue","voice.sequence",true,false,B)}));
            Assert.Equal(CommandKind.Run,t.Command.Kind); Assert.Equal(B,t.Command.TargetId);
            Assert.Null(s.CompositionQuestion);
        }

        [Theory]
        [InlineData("cancel")]
        [InlineData("disconnect")]
        [InlineData("document")]
        [InlineData("timeout")]
        public void PendingPlanInvalidatesAndLateReplyCannotRun(string reason)
        {
            var s=New(); Begin(s,"colour it"); Clarify(s,"colour");
            if(reason=="cancel")s.Cancel();
            else if(reason=="disconnect")s.ConnectionLost();
            else if(reason=="document")s.DocumentChanged();
            else{now=now.AddSeconds(31);s.Tick();}
            Assert.Null(s.CompositionQuestion);
            Assert.Null(s.HostAnswered("request",new VoiceCandidates(A,VoiceDecision.Run,null,30,
                new[]{new VoiceCandidate(1,"Should not run")})).Command);
        }

        [Fact]
        public void DestructivePlanRetainsConfirmationAndExactTarget()
        {
            var s=New(); Begin(s,"colour it red then delete it");
            var t=s.HostAnswered("request",new VoiceCandidates(A,VoiceDecision.Run,null,30,
                new[]{new VoiceCandidate(1,"Colour Sphere red; delete Sphere","voice.sequence",true,true,B)}));
            Assert.True(t.Command.RequiresConfirmation); Assert.Equal(B,t.Command.TargetId);
        }

        [Fact]
        public void LowConfidenceDoesNotFillOrExecuteAPlan()
        {
            var s=New(); Begin(s,"colour it"); Clarify(s,"colour");
            var t=s.Hear(new RecognitionResult("red",.1f));
            Assert.Null(t.Command);Assert.Null(t.Resolve);Assert.NotNull(s.CompositionQuestion);
        }

        [Fact]
        public void ExistingBasicCommandStaysOnFastPath()
        {
            var s=New();s.SetSelection(new[]{A});
            var t=s.Hear(new RecognitionResult("rotate it forty five degrees around x",1));
            Assert.Equal(CommandKind.Rotate,t.Command.Kind);Assert.Null(t.Resolve);
        }

        [Fact]
        public void ReadyPlanCannotTargetADeletedObject()
        {
            var s=New();Begin(s,"colour it red");s.SetObjects(new[]{new SceneObject(A,"Cube")});
            var t=s.HostAnswered("request",new VoiceCandidates(A,VoiceDecision.Run,null,30,
                new[]{new VoiceCandidate(1,"Colour Sphere red","voice.sequence",true,false,B)}));
            Assert.Null(t.Command);Assert.Contains(Prompt.TargetDeleted,t.Prompts);
        }

        [Fact]
        public void CompoundParameterNamesCannotOverrideControllerContext()
        {
            var s=New();
            s.SetObjects(new[]{new SceneObject(A,"Cube"),new SceneObject(B,"Red")});
            s.SetSelection(new[]{A});
            var t=Begin(s,"colour it red then scale it by two");
            Assert.Equal(A,t.Resolve.TargetId);
        }

        [SkippableFact]
        public void NewCompositionVocabularyExistsInPackagedFallbackModel()
        {
            Skip.IfNot(System.IO.Directory.Exists(VoskTests.ModelPath), "No packaged Vosk model available");
            using(var model=SpatialModeling.VoiceCore.Vosk.VoskSpeechRecognizer.Load(VoskTests.ModelPath))
                foreach(string word in new[]{"then","color","paint","lighter","darker","lighten","darken","duplicate","reset","rotation","width","height","depth","wide","tall","deep","negative","positive","half","double","red","green","blue","yellow","orange","purple","pink","cyan","white","black","gray","grey","brown"})
                    Assert.True(model.HasWord(word),"Fallback model lacks new grammar word: "+word);
        }

        [Fact]
        public void WireConfirmationAndClarificationFieldsParse()
        {
            var a=VoiceCandidates.FromJson("{\"resolution\":\""+A+"\",\"decision\":\"clarify\",\"reason\":\"Step 1: colour\",\"expires_in\":30,\"missing\":\"colour\",\"candidates\":[]}");
            Assert.Equal(VoiceDecision.Clarify,a.Decision);Assert.Equal("colour",a.Missing);
            var c=VoiceCandidates.FromJson("{\"resolution\":\""+A+"\",\"decision\":\"run\",\"candidates\":[{\"choice\":1,\"say\":\"Delete Sphere\",\"requires_confirmation\":true,\"needs_target\":true,\"target_id\":\""+B+"\"}]}");
            Assert.True(c.Candidates.Single().RequiresConfirmation);Assert.Equal(B,c.Candidates.Single().TargetId);
        }
    }
}
