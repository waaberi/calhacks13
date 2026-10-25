using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using Xunit;

public class VoiceIntentTests
{
    static JObject Context()=>JObject.Parse(@"{'mode':'OBJECT','document_id':'doc','open_epoch':'open','revision':7,'native_tool':'builtin.scale','topology_token':'topology','options':{},'gesture_epoch':1,'gesture_active':false,'native_selection':{'objects':[]},'selection':{'component':'object','objects':[],'indices':[]},'objects':[{'id':'a','name':'Cube','generation':3}]}");
    [Theory]
    [InlineData("scale down two times",true)]
    [InlineData("scale down negative two",true)]
    [InlineData("make two times smaller",true)]
    [InlineData("scale down",true)]
    [InlineData("make it bigger",true)]
    [InlineData("scale by two",false)]
    [InlineData("move ten millimeters along x",false)]
    public void QualitativeScaleGoesToInterpretationRatherThanRigidBasicParser(string phrase,bool expected)
        => Assert.Equal(expected,VoiceIntentContext.NeedsInterpretation(phrase));
    [Fact] public void VRSelectionHintDoesNotRewriteNativeFingerprintOrInventMeshSelection()
    {
        var context=Context();string frozen=context.ToString(Formatting.None);
        var hint=VoiceIntentContext.SelectedObject(context,"a");
        Assert.Equal("a",(string)hint["selected_object"]["id"]);Assert.Equal(frozen,context.ToString(Formatting.None));
        var request=GeminiVoiceInterpreter.BuildBody("make two times smaller\nClarification question: Which object?\nUser answer: item selected",context,new JArray(),true,hint);
        var input=JObject.Parse((string)request["contents"][0]["parts"][0]["text"]);
        Assert.Contains("two times smaller",(string)input["utterance"]);Assert.Contains("item selected",(string)input["utterance"]);
        Assert.Equal("a",(string)input["voice_context"]["selected_object"]["id"]);Assert.True(JToken.DeepEquals(context,input["context"]));
        context["mode"]="EDIT_MESH";Assert.Empty(VoiceIntentContext.SelectedObject(context,"a"));
        Assert.Empty(VoiceIntentContext.SelectedObject(Context(),"deleted-id"));
    }
    [Fact] public void TargetQuestionAllowsSelectionAnswerButOtherQuestionsDoNot()
    {
        var a=Context();var b=(JObject)a.DeepClone();b["selection"]["objects"]=new JArray(new JObject { ["id"]="a",["generation"]=3 });
        b["native_selection"]=b["selection"].DeepClone();b["gesture_epoch"]=2;
        Assert.True(VoiceIntentContext.CanRebindTarget(a,b,new JArray("target")));
        Assert.False(VoiceIntentContext.CanRebindTarget(a,b,new JArray("factor")));
        Assert.False(VoiceIntentContext.CanRebindTarget(a,b,new JArray("component_selection")));
    }
    [Theory]
    [InlineData("document_id","another")][InlineData("open_epoch","new")][InlineData("revision",8)]
    [InlineData("mode","EDIT_MESH")][InlineData("native_tool","builtin.inset")][InlineData("topology_token","changed")]
    [InlineData("gesture_active",true)]
    public void TargetAnswerNeverRebindsAcrossModelOrOwnershipChanges(string field,object value)
    {var a=Context();var b=(JObject)a.DeepClone();b[field]=JToken.FromObject(value);Assert.False(VoiceIntentContext.CanRebindTarget(a,b,new JArray("target")));}
    [Fact] public void TargetAnswerRejectsChangedOptionsAndObjectGenerations()
    {
        var a=Context();var b=(JObject)a.DeepClone();b["objects"][0]["generation"]=4;
        Assert.False(VoiceIntentContext.CanRebindTarget(a,b,new JArray("target")));
        b=(JObject)a.DeepClone();b["options"]["changed"]=true;
        Assert.False(VoiceIntentContext.CanRebindTarget(a,b,new JArray("target")));
    }
}
