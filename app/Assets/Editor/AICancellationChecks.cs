using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.Serialization;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using SpatialModeling.VoiceCore;
using UnityEngine;

// Real HostScene send/callback/receipt and VoiceUiAdapter confirmation/cancel
// routes. The transport is a private fixture socket, never a host or runtime.
public static class AICancellationChecks
{
    const string A="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",Resolution="cccccccccccccccccccccccccccccccc";
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string why){if(!value)throw new Exception("AI_CANCEL: "+why);}
    static object Get(object target,string field)=>target.GetType().GetField(field,Private).GetValue(target);
    static void Set(object target,string field,object value)=>target.GetType().GetField(field,Private).SetValue(target,value);
    static object Invoke(object target,string method,params object[] args)=>target.GetType().GetMethod(method,Private).Invoke(target,args);

    public static void Run()
    {
        ReplacedRequestFence();ReviewPageFence();QueuedCancellation();SentCancellation();ControlRouting();NativeAiContext();
        Debug.Log("AI_CANCELLATION_CHECK PASS actual reviewed-confirm/queued-vs-wire state/Cancel+context fence/no delayed replay/other owner preserved/sent receipt+unknown honest/core Undo+Redo synonyms+Save+Cancel in Edit Mode; no AI service or interactive runtime");
    }
    static void ReplacedRequestFence()
    {
        using(var f=new Fixture())
        {
            f.ReviewAi();f.ReviewAllPages();
            Check(Get(f.Voice,"deleteWaiting")!=null&&f.ReviewPanel.Visible,"old review initially can be confirmed");
            int sequence=(int)Get(f.Voice,"aiSequence");
            // This accepted replacement fails admission before any coroutine or
            // service request, exactly where the old review used to survive.
            f.Drawing.NativeState["model_edit"]=new JObject { ["options"]=new JObject { ["native_context_fingerprint_unavailable"]=true } };
            Invoke(f.Voice,"StartAiRecipe","inset the selected faces two millimeters");
            Check((int)Get(f.Voice,"aiSequence")>sequence&&!(bool)Get(f.Voice,"aiBusy")
                &&Get(f.Voice,"deleteWaiting")==null&&Get(f.Voice,"aiReview")==null&&!f.ReviewPanel.Visible,
                "new request immediately revokes old confirmation even when new admission fails");
            Invoke(f.Voice,"ConfirmDelete");
            Check(!f.DataAvailable&&Get(f.Voice,"aiSubmittedCommand")==null,"old stick confirmation cannot execute after replacement failure");
            Check(!(bool)Invoke(f.Voice,"AcceptAiCandidates","recipe-request",new JObject { ["decision"]="run" }),
                "a late old review response cannot recreate the revoked AI review");
        }
        using(var f=new Fixture())
        {
            f.NativeReady();string id=f.ConfirmAi();
            Check(f.Host.IsCommandQueued(id),"old confirmed edit waits for native release");
            Check((bool)Invoke(f.Voice,"ReplaceAiRequest"),"replacement can cancel own unsent edit");
            f.ReleaseAndFlush();f.ReleaseAndFlush();
            Check(!f.Host.IsCommandQueued(id)&&!f.DataAvailable&&f.Answers.Single(a=>a.RequestId==id).Outcome=="cancelled",
                "native release cannot replay a replaced queued AI edit");
        }
        using(var f=new Fixture())
        {
            string id=f.ConfirmAi();f.Read("command");
            Check(!(bool)Invoke(f.Voice,"ReplaceAiRequest"),"new AI interpretation waits for an already-sent edit receipt");
            Check(f.Host.IsCommandInFlight(id)&&!f.DataAvailable&&!f.Answers.Any(a=>a.RequestId==id),
                "replacement never fabricates a rollback or duplicate for a sent edit");
            f.Answer(id,"voice.run","applied");
            Check(f.Answers.Single(a=>a.RequestId==id).Outcome=="applied","native receipt remains authoritative after replacement refusal");
        }
        Debug.Log("AI_REPLACEMENT_CHECK PASS revoke old review on failed replacement/no late-review resurrection/queued edit no release replay/sent edit waits actual receipt; no AI service");
    }
    static void ReviewPageFence()
    {
        using var f=new Fixture();f.ReviewAi(A,true,8);
        Check(f.ReviewPanel.Visible&&!f.ReviewPanel.AllPagesReviewed,"real AI review panel requires every page before confirmation");
        Invoke(f.Voice,"ConfirmDelete");
        Check(Get(f.Voice,"deleteWaiting")!=null&&Get(f.Voice,"aiSubmittedCommand")==null&&!f.DataAvailable,
            "unreviewed pages retain the deliberate confirmation and send no command");
        f.ReviewAllPages();Invoke(f.Voice,"ConfirmDelete");
        string id=(string)Get(f.Voice,"aiSubmittedCommand");var wire=f.Read("command");
        Check(id!=null&&(string)wire["id"]==id&&(string)wire["payload"]["op"]=="voice.run"&&!f.DataAvailable,
            "visiting actual review pages permits one deliberately confirmed stored recipe");
        f.Answer(id,"voice.run","applied");
    }
    static void QueuedCancellation()
    {
        foreach(string why in new[]{"cancel","context-tick","context-callback"})
        {
            using var f=new Fixture();
            string other=f.Host.SendCommand("history.undo",null,new JObject(),"voice");f.Read("command");
            f.NativeReady();string id=f.ConfirmAi();
            Check(f.Host.IsCommandQueued(id)&&!f.Host.IsCommandInFlight(id)&&!f.DataAvailable,"confirmed AI run waits behind real native input release "+why);
            if(why=="cancel")Invoke(f.Voice,"CancelPressed");
            else
            {
                Set(f.Host,"revision",8L);
                if(why=="context-tick")Invoke(f.Voice,"TickAi");
            }
            if(why!="context-callback")
            {
                Check(!f.Host.IsCommandQueued(id)&&f.Answers.Count(a=>a.RequestId==id&&a.Outcome=="cancelled"&&a.ErrorCode=="cancelled_before_send")==1,
                    "unsent AI request receives one explicit cancellation "+why);
                Check((string)Get(f.Voice,"resultLine")!="unknown","local cancellation never claims a native unknown result");
            }
            Check(f.Host.IsCommandInFlight(other),"AI cancellation preserves an unrelated sent deterministic command "+why);
            f.ReleaseAndFlush();f.ReleaseAndFlush();
            Check(!f.DataAvailable&&!f.Host.IsCommandQueued(id)&&!f.Host.IsCommandInFlight(id),"late acknowledged release cannot replay cancelled AI intent "+why);
            Check(f.Answers.Count(a=>a.RequestId==id)==1,"deferred failure/duplicate callback cannot answer cancellation twice "+why);
            Check(f.Answers.Single(a=>a.RequestId==id).Message.Contains("No edit was sent"),"cancellation accurately states its unsent boundary "+why);
            f.Answer(other,"history.undo","applied");Check(!f.Host.IsCommandInFlight(other),"unrelated transaction still reconciles its actual receipt");
        }
        using(var f=new Fixture())
        {
            f.NativeReady();string id=f.Host.SendCommand("voice.run",A,new JObject { ["resolution"]=Resolution,["choice"]=1 },"voice");
            Check(!f.Host.CancelQueuedAiCommand(id),"AI-specific token cannot cancel an ordinary deterministic voice.run");
            f.ReleaseAndFlush();var envelope=f.Read("command");Check((string)envelope["id"]==id,"ordinary queued voice command retains existing acknowledged-release behavior");
        }
    }
    static void SentCancellation()
    {
        foreach(string outcome in new[]{"applied","unknown"})
        {
            using var f=new Fixture();string id=f.ConfirmAi();var wire=f.Read("command");
            Check((string)wire["id"]==id&&f.Host.IsCommandInFlight(id)&&!f.Host.IsCommandQueued(id),"immediate AI run is tracked as sent "+outcome);
            Invoke(f.Voice,"CancelPressed");
            Check(f.Host.IsCommandInFlight(id)&&!f.Answers.Any(a=>a.RequestId==id)&&!f.DataAvailable,"Cancel cannot invent rollback or replay an already sent transaction "+outcome);
            Check(((string)Get(f.Voice,"resultLine")).Contains("already sent"),"sent cancellation reports waiting for actual Blender receipt");
            f.Answer(id,"voice.run",outcome);
            Check(!f.Host.IsCommandInFlight(id)&&f.Answers.Single(a=>a.RequestId==id).Outcome==outcome,"actual sent outcome remains authoritative "+outcome);
            Check(((string)Get(f.Voice,"resultLine")).StartsWith(outcome+":"),"actual receipt replaces waiting feedback "+outcome);
        }
    }
    static void ControlRouting()
    {
        var control=typeof(VoiceUiAdapter).GetMethod("Control",BindingFlags.Static|BindingFlags.NonPublic);
        foreach(var entry in new[]{("undo that","history.undo"),("redo that","history.redo"),("undo the move","history.undo"),("redo that rotate","history.redo"),
            ("save","voice.resolve"),("save the file","voice.resolve"),("save project","voice.resolve"),("cancel that","")})
        {
            using var f=new Fixture();f.Drawing.NativeState["model_edit"]=new JObject { ["mode"]="EDIT_MESH" };
            var ai=(GeminiVoiceInterpreter)FormatterServices.GetUninitializedObject(typeof(GeminiVoiceInterpreter));
            typeof(GeminiVoiceInterpreter).GetField("apiKey",Private).SetValue(ai,"fixture-key-never-sent");Set(f.Voice,"ai",ai);
            Set(f.Voice,"aiTools",new JArray(new JObject { ["id"]="mesh.bevel" }));
            Check(f.Voice.AiAvailable&&(bool)control.Invoke(null,new object[]{entry.Item1}),"existing control classified before Gemini in Edit Mode: "+entry.Item1);
            Invoke(f.Voice,"HearOrInterpret",new RecognitionResult(entry.Item1,1),false);
            Check(!(bool)Get(f.Voice,"aiBusy"),"history/save/cancel never starts AI interpretation: "+entry.Item1);
            if(entry.Item2.Length>0)
            {
                var wire=f.Read(entry.Item2=="voice.resolve"?"voice.resolve":"command");
                if(entry.Item2!="voice.resolve")Check((string)wire["payload"]["op"]==entry.Item2,"actual core synonym routes exact history command "+entry.Item1);
            }
            else Check(!f.DataAvailable,"Cancel remains a separate local control");
        }
        Check(!(bool)control.Invoke(null,new object[]{"bevel selected faces"}),"ordinary modeling request remains available to AI");
    }
    static void NativeAiContext()
    {
        const string Rig="dddddddddddddddddddddddddddddddd",Camera="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            Light="ffffffffffffffffffffffffffffffff",Other="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",Hidden="11111111111111111111111111111111";
        using var f=new Fixture();var visible=(Dictionary<string,GameObject>)Get(f.Host,"objects");var generations=(Dictionary<string,long>)Get(f.Host,"generations");
        void Add(string id,string name,long generation,bool renderer,bool enabled,bool shown=true)
        {
            if(visible.TryGetValue(id,out var old))UnityEngine.Object.DestroyImmediate(old);
            var obj=new GameObject(name);if(renderer)obj.AddComponent<MeshRenderer>().enabled=enabled;obj.SetActive(shown);visible[id]=obj;generations[id]=generation;
        }
        Add(A,"Mesh",3,true,true);Add(Other,"Other mesh",4,true,true);Add(Rig,"Rig",7,true,false);
        Add(Camera,"Camera",8,false,false);Add(Light,"Light",9,true,false);Add(Hidden,"Hidden rig",10,false,false,false);
        var basic=new List<KeyValuePair<string,string>>();f.Host.GetShownObjects(basic);
        Check(basic.Select(item=>item.Key).OrderBy(id=>id).SequenceEqual(new[]{A,Other}.OrderBy(id=>id)),"basic voice grammar remains mesh-renderer-only");
        Invoke(f.Preview,"EnsureDirectEditing");var direct=f.Preview.DirectEditing;direct.SetActive(true);var live=(DirectLiveController)Get(direct,"live");
        string token=new string('a',64),nativeToken=new string('b',64);
        live.Selection.Pick(A,3,"face",5,token,false);live.Selection.SetAdditive(true);live.Selection.Pick(A,3,"face",8,token,false);
        JObject Model(string mode,string component,string active,JArray objects,JArray indices,bool supported=true,string topology=null)
        {
            var model=new JObject { ["mode"]=mode,["component"]=component,["active_object_id"]=active,["live_supported"]=supported,
                ["native_tool"]="builtin.move",["topology_token"]=topology??token,
                ["selection"]=new JObject { ["active_id"]=active,["component"]=component,["indices"]=indices,["objects"]=objects,["selection_token"]=nativeToken } };
            f.Drawing.NativeState["model_edit"]=model;f.Drawing.NativeState["mode"]=mode;return model;
        }
        JArray Objects(params string[] ids)=>new JArray(ids.Select(id=>(object)new JObject { ["id"]=id,["generation"]=generations[id] }));
        JObject Capture()=>(JObject)Invoke(f.Voice,"CaptureAiContext");
        Model("POSE","object",Rig,Objects(Rig),new JArray(),false);
        var pose=Capture();var catalog=(JArray)pose["objects"];
        Check(catalog.Count==5&&catalog.OfType<JObject>().Any(row=>(string)row["id"]==Rig&&(string)row["name"]=="Rig"&&(long)row["generation"]==7)
            &&catalog.OfType<JObject>().Any(row=>(string)row["id"]==Camera)&&catalog.OfType<JObject>().Any(row=>(string)row["id"]==Light)
            &&!catalog.OfType<JObject>().Any(row=>(string)row["id"]==Hidden),"AI catalog includes visible rendererless/metadata rig, camera and light with IDs/names/generations; hidden excluded");
        Check((string)pose["mode"]=="POSE"&&(string)pose["selection"]["component"]=="object"
            &&(string)pose["selection"]["objects"][0]["id"]==Rig&&((JArray)pose["selection"]["indices"]).Count==0,"actual native Pose selection replaces stale direct mesh faces");
        f.ReviewAi(Rig);Invoke(f.Voice,"OnScene");
        Check(((VoiceCommand)Get(f.Voice,"deleteWaiting"))?.TargetId==Rig,"AI-only native visibility keeps a pending Pose review through actual OnScene refresh");
        f.ReviewAllPages();
        Invoke(f.Voice,"ConfirmDelete");string poseRun=(string)Get(f.Voice,"aiSubmittedCommand");var poseWire=f.Read("command");
        Check((string)poseWire["payload"]["op"]=="voice.run"&&(string)poseWire["payload"]["target"]["id"]==Rig
            &&(long)poseWire["payload"]["target"]["generation"]==7,"reviewed nonmesh Pose candidate reaches actual existing confirmation and wire with native rig identity");
        Check(!((VoiceSession)Get(f.Voice,"session")).Objects.Any(obj=>obj.Id==Rig),"AI confirmation does not add native rig to the ordinary speech-session grammar roster");f.Answer(poseRun,"voice.run","applied");
        f.ReviewAi(Rig);Invoke(f.Voice,"CancelPressed");Invoke(f.Voice,"ConfirmDelete");
        Check(Get(f.Voice,"deleteWaiting")==null&&!f.DataAvailable,"Cancel discards an unsent native Pose review without a delayed send");
        f.ReviewAi(Rig);generations[Rig]=8;Invoke(f.Voice,"OnScene");Invoke(f.Voice,"ConfirmDelete");
        Check(Get(f.Voice,"deleteWaiting")==null&&!f.DataAvailable,"stale native rig generation refuses reviewed confirmation before wire");generations[Rig]=7;
        f.ReviewAi(Rig,false);Invoke(f.Voice,"ConfirmDelete");
        Check(Get(f.Voice,"deleteWaiting")==null&&!f.DataAvailable,"AI candidate without complete recipe review header cannot fall back to an executable core prefix");
        Model("EDIT_MESH","face",Other,Objects(Other),new JArray(2));var changedMesh=Capture();
        Check((string)changedMesh["selection"]["objects"][0]["id"]==Other&&((JArray)changedMesh["selection"]["indices"]).Values<int>().SequenceEqual(new[]{2}),"native active-mesh change excludes old floating target/components");
        var current=Model("EDIT_MESH","face",A,Objects(A),new JArray(5,8));var acknowledged=Capture();
        Check((string)acknowledged["selection"]["selection_token"]==(string)direct.SelectionSnapshot["selection_token"],"fresh matching acknowledged spatial mesh selection remains intact");
        direct.SetActive(false);Check((string)Capture()["selection"]["selection_token"]==nativeToken,"disabled direct mode uses actual native selection");direct.SetActive(true);
        current["live_supported"]=false;Check((string)Capture()["selection"]["selection_token"]==nativeToken,"unsupported live mode/tool does not reuse old spatial intent");current["live_supported"]=true;
        current["selection"]["indices"]=new JArray(8,5);Check(((JArray)Capture()["selection"]["indices"]).Values<int>().SequenceEqual(new[]{8,5}),"actual native component order wins over stale spatial order");current["selection"]["indices"]=new JArray(5,8);
        generations[A]=4;current["selection"]["objects"]=Objects(A);
        Check((long)Capture()["selection"]["objects"][0]["generation"]==4&&(string)Capture()["selection"]["selection_token"]==nativeToken,"stale spatial generation cannot mask fresh native selection");generations[A]=3;
        f.Voice.SelectObject(A);live.Selection.Clear();live.Selection.Pick(A,3,"object",-1,token,false);
        Model("OBJECT","object",A,new JArray(),new JArray());
        Check(f.Voice.SelectedObjectId==A&&((JArray)Capture()["selection"]["objects"]).Count==0,"explicit native Object Mode deselection cannot resurrect stale voice/spatial selected object or active object");
        live.Selection.SetAdditive(true);live.Selection.Pick(Other,4,"object",-1,token,false);
        Model("OBJECT","object",Other,Objects(A,Other),new JArray());
        Check((string)Capture()["selection"]["selection_token"]==(string)direct.SelectionSnapshot["selection_token"],"fresh acknowledged Object Mode multi-selection is preserved");
        Check(!f.DataAvailable,"AI context capture only reads selection and metadata; it sends no native command");
        Debug.Log("AI_NATIVE_CONTEXT_CHECK PASS actual CaptureAiContext/visible nonmesh catalog/Pose+native-active-domain/native deselect authoritative/retained acknowledged spatial selection+order+generation; basic grammar unchanged");
    }
    sealed class Fixture:IDisposable
    {
        readonly IDisposable common;
        readonly Type commonType;
        readonly TcpClient sender,receiver;
        readonly StreamReader reader;
        readonly GameObject feedback,reviewPanelObject;
        public readonly HostScene Host;
        public readonly PreviewInteraction Preview;
        public readonly PreviewSpatialDrawing Drawing;
        public readonly VoiceUiAdapter Voice;
        public readonly PendingCommandPanel ReviewPanel;
        public readonly List<CommandAnswer> Answers=new List<CommandAnswer>();
        public bool DataAvailable=>receiver.GetStream().DataAvailable;
        public Fixture()
        {
            commonType=typeof(P25CommonUiChecks).GetNestedType("Fixture",BindingFlags.Public|BindingFlags.NonPublic);
            common=(IDisposable)Activator.CreateInstance(commonType);
            Host=(HostScene)commonType.GetField("Host").GetValue(common);Preview=(PreviewInteraction)commonType.GetField("Preview").GetValue(common);
            Drawing=(PreviewSpatialDrawing)commonType.GetField("Drawing").GetValue(common);
            var listener=new TcpListener(IPAddress.Loopback,0);listener.Start();sender=new TcpClient();sender.Connect((IPEndPoint)listener.LocalEndpoint);
            receiver=listener.AcceptTcpClient();listener.Stop();reader=new StreamReader(receiver.GetStream());
            var linkType=typeof(HostScene).Assembly.GetType("SpatialModeling.HostLink");var link=FormatterServices.GetUninitializedObject(linkType);
            linkType.GetField("stream",Private).SetValue(link,sender.GetStream());linkType.GetField("writeLock",Private).SetValue(link,new object());Set(Host,"link",link);
            foreach(string field in new[]{"welcomed","canEdit","connected"})Set(Host,field,true);
            foreach(var pair in new[]{("sessionId","session"),("hostEpoch","host"),("welcomeDocumentId","doc"),("welcomeOpenEpoch","open"),("actorId","actor")})Set(Host,pair.Item1,pair.Item2);
            ((Dictionary<string,long>)Get(Host,"generations"))[A]=3;
            var meshObject=new GameObject("Alpha",typeof(MeshRenderer));((Dictionary<string,GameObject>)Get(Host,"objects"))[A]=meshObject;
            Voice=Host.gameObject.AddComponent<VoiceUiAdapter>();Voice.host=Host;
            var session=new VoiceSession(new VoiceSessionOptions { AskHost=true },()=>DateTime.UtcNow);session.EnableComposition(true);session.SetObjects(new[]{new SceneObject(A,"Alpha")});session.SetSelection(new[]{A});Set(Voice,"session",session);
            feedback=new GameObject("AI cancellation fixture feedback",typeof(TextMesh));Set(Voice,"feedback",feedback.GetComponent<TextMesh>());
            reviewPanelObject=new GameObject("AI cancellation fixture review panel");reviewPanelObject.SetActive(false);
            reviewPanelObject.transform.SetParent(Host.transform,false);
            ReviewPanel=reviewPanelObject.AddComponent<PendingCommandPanel>();
            if(Get(ReviewPanel,"text")==null)Invoke(ReviewPanel,"Awake");
            ReviewPanel.head=Host.transform;Set(Voice,"panel",ReviewPanel);
            Host.CommandAnswered+=answer=>{Answers.Add(answer);Invoke(Voice,"OnAnswered",answer);};
        }
        public void NativeReady()=>commonType.GetMethod("NativeReady").Invoke(common,new object[]{"OBJECT"});
        public void ReviewAi(string target=A,bool reviewHeader=true,int stepCount=1)
        {
            string transcript=target==A?"bevel selected edges two millimeters":"reset the selected rig pose bone Forearm";
            var session=(VoiceSession)Get(Voice,"session");var turn=session.ResolveRecipe(transcript);session.ResolveSent(turn.Resolve,"recipe-request");
            var context=(JObject)Invoke(Voice,"CaptureAiContext");Set(Voice,"aiExpectedContext",context.DeepClone());Set(Voice,"aiOriginal",transcript);
            Set(Voice,"aiRecipeRequest","recipe-request");Set(Voice,"aiFingerprint",context.ToString(Formatting.None));
            var steps=new JArray();for(int index=0;index<stepCount;index++)steps.Add(new JObject { ["id"]="step"+(index+1),["tool"]=target==A?"mesh.bevel":"rig.pose_reset",["target"]=target,
                ["params"]=target==A?new JObject{["width_m"]=.002}:new JObject{["bone"]="Forearm"} });
            var payload=new JObject { ["resolution"]=Resolution,["decision"]="run",["expires_in"]=30,
                ["recipe_plan"]=new JObject { ["steps"]=steps },
                ["candidates"]=new JArray(new JObject { ["choice"]=1,["say"]="Reviewed native edit",["needs_target"]=true,["requires_confirmation"]=true,["target_id"]=target }) };
            if(!reviewHeader)payload.Remove("recipe_plan");
            Check((bool)Invoke(Voice,"AcceptAiCandidates","recipe-request",payload),"AI-only recipe response is fully handled without ordinary grammar fallback");
        }
        public void ReviewAllPages()
        {
            Check(ReviewPanel.Visible,"the actual pending-command panel displays the stored AI review");
            int pages=0;while(!ReviewPanel.AllPagesReviewed)
                Check(pages++<128&&ReviewPanel.MovePage(1),"actual next-page navigation visits every AI review page within the bounded fixture");
        }
        public string ConfirmAi(string target=A)
        {
            ReviewAi(target);
            Check(Get(Voice,"deleteWaiting")!=null,"reviewed AI command requires existing deliberate confirmation");
            ReviewAllPages();
            Invoke(Voice,"ConfirmDelete");string id=(string)Get(Voice,"aiSubmittedCommand");Check(id!=null,"confirmed AI command keeps its exact cancellable request ID");return id;
        }
        public void ReleaseAndFlush()
        {
            Set(Preview,"endAfterRelease",false);commonType.GetMethod("Fresh").Invoke(common,null);Invoke(Preview,"FlushNativeCommand");
        }
        public JObject Read(string expected)
        {
            Check(SpinWait.SpinUntil(()=>DataAvailable,1000),"fixture wire receives "+expected);var envelope=JObject.Parse(reader.ReadLine());
            Check((string)envelope["type"]==expected,"wire type "+expected);return envelope;
        }
        public void Answer(string id,string op,string outcome)=>Invoke(Host,"Answer",id,op,outcome,"","Native "+outcome,(long?)7,false,null);
        public void Dispose()
        {
            Set(Host,"link",null);common.Dispose();
            if(reviewPanelObject!=null)UnityEngine.Object.DestroyImmediate(reviewPanelObject);
            UnityEngine.Object.DestroyImmediate(feedback);reader.Dispose();receiver.Dispose();sender.Dispose();
        }
    }
}
