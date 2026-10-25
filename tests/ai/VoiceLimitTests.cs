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
}
