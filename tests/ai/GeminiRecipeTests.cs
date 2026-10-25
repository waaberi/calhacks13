using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine.Networking;
using Xunit;

[assembly: CollectionBehavior(DisableTestParallelization=true)]
public class GeminiRecipeTests : IDisposable
{
    readonly string oldKey;
    public GeminiRecipeTests()
    { oldKey=Environment.GetEnvironmentVariable("GEMINI_API_KEY");Environment.SetEnvironmentVariable("GEMINI_API_KEY","codex_fake_test_key_not_a_real_secret"); }
    public void Dispose() { Environment.SetEnvironmentVariable("GEMINI_API_KEY",oldKey);UnityWebRequest.Responder=null; }
    static JArray Catalog()=>JArray.Parse("[{\"id\":\"mesh.inset\",\"parameters\":{\"type\":\"object\",\"properties\":{\"thickness_m\":{\"type\":\"number\"}},\"required\":[\"thickness_m\"],\"additionalProperties\":false},\"outputs\":[\"inner_faces\"]}]");
    static string Reply(string draft,string finish="STOP")=>new JObject { ["candidates"]=new JArray(new JObject { ["finishReason"]=finish,
        ["content"]=new JObject { ["parts"]=new JArray(new JObject { ["text"]=draft }) } }) }.ToString();
    const string Valid="{\"decision\":\"propose\",\"steps\":[{\"id\":\"one\",\"tool\":\"mesh.inset\",\"target\":\"selected\",\"selection\":\"captured\",\"params\":{\"thickness_m\":0.002}}],\"missing\":[],\"reason\":\"\",\"unhandled_intent\":[]}";
    static void Drain(IEnumerator routine) { while(routine.MoveNext())if(routine.Current is IEnumerator child)Drain(child); }

    [Fact] public void ProductionRequestUsesFullUtteranceCatalogAndTypedSchema()
    {
        const string utterance="inset selected faces two millimeters then extrude five millimeters then bevel the new boundary";
        var body=GeminiVoiceInterpreter.BuildBody(utterance,new JObject { ["selection"]=new JObject { ["indices"]=new JArray(1,2) } },Catalog(),true);
        Assert.Contains(utterance,body["contents"].ToString());
        Assert.Equal("application/json",(string)body["generationConfig"]["responseMimeType"]);
        Assert.Equal("mesh.inset",(string)body["generationConfig"]["responseJsonSchema"]["properties"]["steps"]["items"]["anyOf"][0]["properties"]["tool"]["enum"][0]);
        Assert.DoesNotContain("return the first",body.ToString());
        Assert.Null(body["tools"]); // No auto-executing model tool calls.
    }
    [Fact] public void CompleteOrderedReplyNeverTrimsAClauseOrLine()
    {
        var draft=JObject.Parse(Valid);var steps=(JArray)draft["steps"];
        for(int i=2;i<=6;i++){var next=(JObject)steps[0].DeepClone();next["id"]="step"+i;steps.Add(next);}
        var read=GeminiVoiceInterpreter.Read(Reply(draft.ToString()));
        Assert.Equal(6,((JArray)read["steps"]).Count);
        Assert.Equal("step6",(string)read["steps"][5]["id"]);
    }
    [Theory]
    [InlineData("MAX_TOKENS")][InlineData("SAFETY")][InlineData("OTHER")]
    public void TruncatedOrBlockedResponsesCannotProduceAnExecutablePrefix(string finish)
    { Assert.Throws<FormatException>(()=>GeminiVoiceInterpreter.Read(Reply(Valid,finish))); }
    [Theory]
    [InlineData("{\"decision\":\"propose\",\"steps\":[]}")]
    [InlineData("{\"phrase\":\"add a cube\"}")]
    [InlineData("{\"decision\":\"propose\",\"steps\":[],\"missing\":[],\"reason\":\"\",\"unhandled_intent\":[],\"python\":\"exec()\"}")]
    public void MissingOrUnexpectedFieldsAreRefused(string draft)
    { Assert.Throws<FormatException>(()=>GeminiVoiceInterpreter.Read(Reply(draft))); }
    [Theory][InlineData(0)][InlineData(401)][InlineData(403)][InlineData(429)][InlineData(500)]
    public void FaultsReturnNoPlanAndDoNotRetryOrExecute(int status)
    {
        int requests=0;UnityWebRequest.Responder=web=>{requests++;Assert.True(web.HasKeyHeader);return(status,"{}");};
        GeminiVoiceInterpreter.Answer answer=null;var interpreter=new GeminiVoiceInterpreter();
        Drain(interpreter.Interpret("inset faces",new JObject(),Catalog(),()=>true,value=>answer=value));
        Assert.Equal(1,requests);Assert.NotNull(answer.Error);Assert.Null(answer.Draft);
    }
    [Fact] public void UnsupportedThinkingSettingRetriesOnlyPureInterpretationOnce()
    {
        var bodies=new List<JObject>();UnityWebRequest.Responder=web=>{bodies.Add(JObject.Parse(web.Body));return bodies.Count==1?(400,"{}"): (200,Reply(Valid));};
        GeminiVoiceInterpreter.Answer answer=null;Drain(new GeminiVoiceInterpreter().Interpret("inset faces",new JObject(),Catalog(),()=>true,value=>answer=value));
        Assert.Equal(2,bodies.Count);Assert.NotNull(bodies[0]["generationConfig"]["thinkingConfig"]);Assert.Null(bodies[1]["generationConfig"]["thinkingConfig"]);Assert.NotNull(answer.Draft);
    }
    [Fact] public void StaleContextAfterNetworkReturnDropsResponseWithoutFallback()
    {
        bool current=true,called=false;UnityWebRequest.Responder=web=>(200,Reply(Valid));
        var interpreter=new GeminiVoiceInterpreter();var routine=interpreter.Interpret("inset faces",new JObject(),Catalog(),()=>current,_=>called=true);
        Assert.True(routine.MoveNext());current=false;interpreter.Cancel();Drain(routine);Assert.False(called);
    }
    [Fact] public void ClarificationRetainsMissingFieldsAndDoesNotInventAnAmount()
    {
        const string draft="{\"decision\":\"clarify\",\"steps\":[],\"missing\":[\"thickness_m\"],\"reason\":\"How far should the faces be inset?\",\"unhandled_intent\":[]}";
        var read=GeminiVoiceInterpreter.Read(Reply(draft));Assert.Equal("clarify",(string)read["decision"]);Assert.Empty((JArray)read["steps"]);
    }
}
