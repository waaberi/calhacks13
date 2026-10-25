using Newtonsoft.Json.Linq;
using SpatialModeling;
using Xunit;

public class VoiceLimitTests
{
    static JObject Intent()=>VoiceIntentContext.ForRequest(new JObject { ["mode"]="OBJECT" },null,.05);
    static JObject Draft(string tool,string parameter,JArray value)=>new JObject { ["steps"]=new JArray(new JObject {
        ["tool"]=tool,["params"]=new JObject { [parameter]=value } }) };
    [Theory][InlineData(10)][InlineData(.1)][InlineData(-.1)]
    public void ExistingVoiceMoveRangeAppliesEquallyToEveryAxis(double distance)
    {
        foreach(int axis in new[]{0,1,2})
        {var v=new JArray(0d,0d,0d);v[axis]=distance;GeminiVoiceInterpreter.ValidateVoiceLimits(Draft("object.translate","translation_m",v),Intent());}
    }
    [Theory][InlineData(10.1)][InlineData(100)][InlineData(0)]
    public void WiderNativeToolRangeCannotBypassTheVoiceMoveLimit(double distance)
    {Assert.Throws<GeminiVoiceInterpreter.VoiceLimitFailure>(()=>GeminiVoiceInterpreter.ValidateVoiceLimits(Draft("object.translate","translation_m",new JArray(distance,0d,0d)),Intent()));}
    [Theory][InlineData(.01)][InlineData(100)][InlineData(-2)]
    public void ValidScalingIncludingExplicitReflectionRemainsAvailable(double scale)
    {GeminiVoiceInterpreter.ValidateVoiceLimits(Draft("object.scale","scale",new JArray(scale,1d,1d)),Intent());}
    [Theory][InlineData(0)][InlineData(.001)][InlineData(101)]
    public void ScaleBoundsRemainTheExistingVoiceBounds(double scale)
    {Assert.Throws<GeminiVoiceInterpreter.VoiceLimitFailure>(()=>GeminiVoiceInterpreter.ValidateVoiceLimits(Draft("object.scale","scale",new JArray(scale,1d,1d)),Intent()));}
    [Fact] public void AnInvalidLaterStepRefusesTheWholeUnmodifiedPlan()
    {
        var draft=Draft("object.translate","translation_m",new JArray(.1,0d,0d));
        ((JArray)draft["steps"]).Add(((JArray)Draft("object.scale","scale",new JArray(0d,1d,1d))["steps"])[0].DeepClone());
        string original=draft.ToString();Assert.Throws<GeminiVoiceInterpreter.VoiceLimitFailure>(()=>GeminiVoiceInterpreter.ValidateVoiceLimits(draft,Intent()));
        Assert.Equal(original,draft.ToString());Assert.Equal(2,((JArray)draft["steps"]).Count);
    }
    [Theory][InlineData("rotate Cube 0 degrees about x")][InlineData("rotate Cube 720 degrees about x")]
    [InlineData("rotate Cube seven hundred twenty degrees about x")][InlineData("rotate Cube 1e3 degrees about x")]
    public void OriginalRotationAmountCannotBeHiddenByAnIdentityOrWrappedQuaternion(string request)
    {Assert.Throws<GeminiVoiceInterpreter.VoiceLimitFailure>(()=>GeminiVoiceInterpreter.ValidateVoiceLimits(Draft("object.rotate","rotation",new JArray(1d,0d,0d,0d)),Intent(),request));}
    [Theory][InlineData("rotate Cube 360 degrees about x")][InlineData("rotate Cube -360 degrees about x")]
    [InlineData("rotate Cube negative three hundred sixty degrees about y")][InlineData("rotate Cube one full turn about z")]
    [InlineData("rotate Cube -360 about x")]
    public void SignedFullTurnsRemainValidWithIdentityQuaternion(string request)
    {GeminiVoiceInterpreter.ValidateVoiceLimits(Draft("object.rotate","rotation",new JArray(1d,0d,0d,0d)),Intent(),request);}
    [Fact] public void SeparateRotationClausesAreBoundedIndividuallyAndUnrelatedLengthsAreIgnored()
    {
        var plan=Draft("object.rotate","rotation",new JArray(1d,0d,0d,0d));
        ((JArray)plan["steps"]).Add(((JArray)Draft("object.rotate","rotation",new JArray(.70710678,0d,.70710678,0d))["steps"])[0].DeepClone());
        GeminiVoiceInterpreter.ValidateVoiceLimits(plan,Intent(),"add a cube 1000 millimeters wide then rotate it 360 degrees about x then move it 900 millimeters along y then rotate it ninety degrees about z");
        Assert.Throws<GeminiVoiceInterpreter.VoiceLimitFailure>(()=>GeminiVoiceInterpreter.ValidateVoiceLimits(plan,Intent(),"rotate Cube 360 degrees about x then rotate it 720 degrees about z"));
    }
    [Fact] public void ClarificationKeepsTheOriginalAngleAndSeparatelyAnsweredUnit()
    {
        var plan=Draft("object.rotate","rotation",new JArray(1d,0d,0d,0d));
        string request=GeminiVoiceInterpreter.ComposeRequest("rotate Cube 720 degrees","Which axis?","x");
        Assert.Throws<GeminiVoiceInterpreter.VoiceLimitFailure>(()=>GeminiVoiceInterpreter.ValidateVoiceLimits(plan,Intent(),request));
        request=GeminiVoiceInterpreter.ComposeRequest("rotate Cube 360","Which angle unit?","degrees");
        GeminiVoiceInterpreter.ValidateVoiceLimits(plan,Intent(),request);
        Assert.Throws<GeminiVoiceInterpreter.VoiceLimitFailure>(()=>GeminiVoiceInterpreter.ValidateVoiceLimits(plan,Intent(),"rotate Cube to face the wall"));
    }
    [Fact] public void NonRotationRequestsAndDraftsDoNotAcquireAnAngleRequirement()
    {GeminiVoiceInterpreter.ValidateVoiceLimits(Draft("object.scale","scale",new JArray(.5,.5,.5)),Intent(),"make it half the size");}
}
