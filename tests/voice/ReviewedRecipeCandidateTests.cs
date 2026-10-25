using System;
using System.Linq;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    public class ReviewedRecipeCandidateTests
    {
        const string Rig="dddddddddddddddddddddddddddddddd",Other="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",Resolution="cccccccccccccccccccccccccccccccc";
        static VoiceCandidate Candidate(int choice=1,bool confirm=true,bool needs=true,string target=Rig)
            =>new VoiceCandidate(choice,"Reset Forearm pose","voice.recipe",needs,confirm,target);
        [Fact]
        public void Exact_native_target_uses_existing_confirmed_run_contract()
        {
            var command=VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(),new SceneObject(Rig,"Rig"));
            Assert.Equal(CommandKind.Run,command.Kind);Assert.True(command.RequiresConfirmation);Assert.Equal(Rig,command.TargetId);
            var wire=HostCommand.From(command);Assert.Equal("voice.run",wire.Op);Assert.Equal(Rig,wire.TargetId);Assert.Equal(Resolution,wire.Args["resolution"]);
        }
        [Fact]
        public void Creation_may_have_no_target_without_a_fallback_object()
        {
            var command=VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(needs:false,target:null),null);
            Assert.Null(command.TargetId);Assert.True(command.RequiresConfirmation);Assert.Equal("voice.run",HostCommand.From(command).Op);
        }
        [Theory]
        [InlineData(null)]
        [InlineData("")]
        [InlineData("   ")]
        public void Missing_stored_resolution_is_refused(string resolution)
            =>Assert.Throws<ArgumentException>(()=>VoiceCommand.ReviewedRecipeCandidate(resolution,Candidate(),new SceneObject(Rig,"Rig")));
        [Theory]
        [InlineData(-1)]
        [InlineData(0)]
        [InlineData(4)]
        public void Choice_outside_existing_protocol_bounds_is_refused(int choice)
            =>Assert.Throws<ArgumentException>(()=>VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(choice),new SceneObject(Rig,"Rig")));
        [Fact]
        public void Null_or_unconfirmed_candidate_cannot_bypass_review()
        {
            Assert.Throws<ArgumentNullException>(()=>VoiceCommand.ReviewedRecipeCandidate(Resolution,null,null));
            Assert.Throws<ArgumentException>(()=>VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(confirm:false),new SceneObject(Rig,"Rig")));
        }
        [Fact]
        public void Target_must_exactly_match_host_candidate_and_target_requirement()
        {
            Assert.Throws<ArgumentException>(()=>VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(),null));
            Assert.Throws<ArgumentException>(()=>VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(),new SceneObject(Other,"Other")));
            Assert.Throws<ArgumentException>(()=>VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(target:null),new SceneObject(Rig,"Rig")));
            Assert.Throws<ArgumentException>(()=>VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(needs:false,target:null),new SceneObject(Rig,"Rig")));
        }
        [Fact]
        public void Reviewed_native_target_does_not_mutate_basic_speech_object_roster()
        {
            var basic=new VoiceSession();basic.SetObjects(new[]{new SceneObject(Other,"Mesh")});
            VoiceCommand.ReviewedRecipeCandidate(Resolution,Candidate(),new SceneObject(Rig,"Rig"));
            Assert.Equal(new[]{Other},basic.Objects.Select(obj=>obj.Id));
        }
    }
}
