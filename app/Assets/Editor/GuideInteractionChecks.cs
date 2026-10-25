using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using UnityEngine.XR;

// Synthetic production UI and the actual existing Workspace route. No devices,
// native windows, services, keyboard injection, live scene files or runtime.
public static class GuideInteractionChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static object Get(object target,string name)=>target.GetType().GetField(name,Private).GetValue(target);
    static void Set(object target,string name,object value)=>Assign(target.GetType().GetField(name,Private),target,value);
    static void Assign(FieldInfo field,object target,object value)
    {
        Check(field!=null,"fixture reflected field exists");
        Type nullable=Nullable.GetUnderlyingType(field.FieldType),expected=nullable??field.FieldType;
        Check(value==null?(!field.FieldType.IsValueType||nullable!=null):expected.IsInstanceOfType(value),
            "fixture field "+field.DeclaringType.Name+"."+field.Name+" expects "+field.FieldType+", received "+(value?.GetType().ToString()??"null"));
        field.SetValue(target,value);
    }
    static object Invoke(object target,string name,params object[] args)=>target.GetType().GetMethod(name,Private).Invoke(target,args);
    static void Property(object target,string name,object value)=>target.GetType().GetProperty(name).GetSetMethod(true).Invoke(target,new[]{value});
    static void Check(bool value,string why){if(!value)throw new Exception("GUIDE_INTERACTION: "+why);}
    public static void Run()
    {
        GuideCatalogChecks.Run();
        var cameraObject=new GameObject("Guide synthetic head",typeof(Camera));cameraObject.tag="MainCamera";
        try
        {
            Panel(cameraObject.GetComponent<Camera>());Admission();
            foreach(var hand in new[]{XRNode.RightHand,XRNode.LeftHand})Routing(hand);
            HeldEditingAndOffhand();ReviewCoexistence();Capture(cameraObject.GetComponent<Camera>());
        }
        finally{UnityEngine.Object.DestroyImmediate(cameraObject);}
        Debug.Log("GUIDE_INTERACTION_CHECK PASS local typed search/results/all steps+limits/48 query+digits/prefix+empty+no-match; real home action+both pointer roles; refusal in-place/no cancellation; held native/direct owner preserved; offhand mutation paused; Guide grip+nearest fences; close trigger consumed+edge-only rearm; zero native or Gemini commands; world anchor/complete measured pages+2x text; pending review lifetime; synthetic production screenshots; physical acceptance pending");
    }
    static Button Button(SearchableGuidePanel panel,string name)=>panel.Controls.Single(button=>button.name==name);
    static void Click(SearchableGuidePanel panel,string name)
    {var ray=CombinedGlassChecks.ControlRay(Button(panel,name).GetComponent<RectTransform>());Check(panel.Hover(ray,true),"real local control is hit: "+name);}
    static float Preferred(Text text)
    {var settings=text.GetGenerationSettings(new Vector2(text.rectTransform.rect.width,0));settings.verticalOverflow=VerticalWrapMode.Overflow;return text.cachedTextGeneratorForLayout.GetPreferredHeight(text.text,settings)/text.pixelsPerUnit;}
    static void AllTextFits(SearchableGuidePanel panel)
    {
        foreach(var text in panel.VisualRoot.GetComponentsInChildren<Text>())
            Check(!text.supportRichText&&Preferred(text)<=text.rectTransform.rect.height+.6f,"full literal text fits: "+text.text
                +" preferredHeight="+Preferred(text)+" rect="+text.rectTransform.rect.width+"x"+text.rectTransform.rect.height+" font="+text.fontSize+" pixelsPerUnit="+text.pixelsPerUnit);
        foreach(var control in panel.Controls)
        {
            var corners=new Vector3[4];control.GetComponent<RectTransform>().GetWorldCorners(corners);
            foreach(var corner in corners){var local=panel.VisualRoot.transform.InverseTransformPoint(corner);Check(Mathf.Abs(local.x)<=490.01f&&Mathf.Abs(local.y)<=450.01f,"local keys/results remain inside panel bounds");}
        }
    }
    static void Panel(Camera camera)
    {
        var previousSystem=EventSystem.current;var previousSelection=previousSystem?.currentSelectedGameObject;
        var eventOwner=new GameObject("Guide existing input focus fixture",typeof(EventSystem));var sentinel=new GameObject("Existing editor selection");
        var eventSystem=eventOwner.GetComponent<EventSystem>();
        var registered=(IList<EventSystem>)typeof(EventSystem).GetField("m_EventSystems",BindingFlags.Static|BindingFlags.NonPublic).GetValue(null);
        using var panel=new SearchableGuidePanel();
        try
        {
        // Batch EditMode does not invoke this component's normal lifecycle.
        // Register through the real lifecycle, never by mutating its global list.
        if(!registered.Contains(eventSystem))Invoke(eventSystem,"OnEnable");
        Check(registered.Contains(eventSystem),"temporary EventSystem registers through OnEnable");
        EventSystem.current=eventSystem;eventSystem.SetSelectedGameObject(sentinel);
        Check(panel.Open(camera),"world reading panel opens");
        var anchor=panel.WorldPose;var scale=panel.VisualRoot.transform.lossyScale;
        Check(panel.ResultCount==VrGuideCatalog.Articles.Count&&panel.ResultPageCount>1,"empty search exposes complete current manual with paged results");
        Click(panel,"Local key M");Click(panel,"Local key O");Click(panel,"Local key V");
        Check(EventSystem.current.currentSelectedGameObject==sentinel&&panel.Controls.All(button=>button.navigation.mode==Navigation.Mode.None),"local Guide keys preserve existing EventSystem focus and disable keyboard/gamepad navigation");
        Check(panel.Query=="mov"&&panel.ResultCount>0,"actual controller keys perform local prefix search");
        Click(panel,"Local Backspace");Check(panel.Query=="mo","Backspace only changes local query");Click(panel,"Local Clear");
        Click(panel,"Local key 3");Click(panel,"Local key D");Check(panel.Query=="3d"&&panel.ResultCount>0,"common 3D term can be entered using local digits");
        panel.Search("notatopiczzzz");Check(panel.ResultCount==0,"no-match search is explicit");panel.Search("");
        int count=panel.ResultPageCount;for(int i=0;i<count;i++){Check(panel.ResultPage==i,"all result pages reachable");Click(panel,"Next results");}
        Check(panel.ResultPage==count-1,"last result page is bounded");Click(panel,"Previous results");Check(panel.ResultPage==Mathf.Max(0,count-2),"previous page works");
        bool hadTextScale=PlayerPrefs.HasKey("SpatialModeling.Glass.TextScale");float priorScale=GlassTheme.TextScale;
        try
        {
            foreach(float textScale in new[]{1f,2f})
            {
                PlayerPrefs.SetFloat("SpatialModeling.Glass.TextScale",textScale);panel.Tick();
                panel.Search(new string('W',100));Check(panel.Query.Length==SearchableGuidePanel.MaximumQueryLength,"query length is bounded");AllTextFits(panel);
                var queryText=Button(panel,"Search field").GetComponentInChildren<Text>();
                Check(queryText.text.Replace("\n","")=="Search: "+panel.Query&&queryText.fontSize==25,"long unbroken query displays every original character at unchanged readable font");
                foreach(string line in queryText.text.Split('\n'))
                {
                    var settings=queryText.GetGenerationSettings(Vector2.zero);settings.horizontalOverflow=HorizontalWrapMode.Overflow;
                    float width=queryText.cachedTextGeneratorForLayout.GetPreferredWidth(line,settings)/queryText.pixelsPerUnit;
                    Check(width<=queryText.rectTransform.rect.width+.6f,"explicit query line fits full width="+width+" available="+queryText.rectTransform.rect.width);
                }
                panel.Search("");
                foreach(var article in VrGuideCatalog.Articles)
                {
                    Check(panel.Read(article.Id),"all articles open: "+article.Id);
                    var text=new List<string>();int pages=panel.StepPageCount;
                    for(int page=0;page<pages;page++){Check(panel.StepPage==page&&panel.TextFits,"all complete step pages fit");AllTextFits(panel);text.Add(panel.PageText);Click(panel,"Next step");}
                    string combined=string.Join(" ",text);
                    foreach(var step in article.Steps)Check(combined.Contains(step),"complete step retained: "+article.Id);
                    if(article.Limitation.Length>0)Check(combined.Contains(article.Limitation),"honest complete limitation retained: "+article.Id);
                    Click(panel,"Guide Back");Check(panel.ArticleId==null,"Back returns to search without action");
                }
            }
        }
        finally{if(hadTextScale)PlayerPrefs.SetFloat("SpatialModeling.Glass.TextScale",priorScale);else PlayerPrefs.DeleteKey("SpatialModeling.Glass.TextScale");}
        panel.Tick();camera.transform.SetPositionAndRotation(new Vector3(2,1,-3),Quaternion.Euler(20,110,0));panel.Tick();
        Check(panel.VisualRoot.transform.parent==null&&panel.WorldPose.position==anchor.position&&panel.VisualRoot.transform.position==anchor.position&&panel.VisualRoot.transform.rotation==anchor.rotation,"Guide stays world anchored while head turns");
        Check(Vector3.Distance(panel.VisualRoot.transform.lossyScale,scale)<.00001f,"head turn cannot resize text");
        Check(panel.VisualRoot.GetComponentsInChildren<UnityEngine.UI.InputField>().Length==0&&panel.VisualRoot.GetComponentsInChildren<GraphicRaycaster>().Length==0,"search has no physical/native keyboard or automatic UI input module");
        Click(panel,"Close Guide");Check(!panel.Visible,"explicit Close hides only Guide");
        }
        finally
        {
            camera.transform.SetPositionAndRotation(Vector3.zero,Quaternion.identity);
            eventSystem.enabled=false;
            if(registered.Contains(eventSystem))Invoke(eventSystem,"OnDisable");
            if(previousSystem!=null){EventSystem.current=previousSystem;previousSystem.SetSelectedGameObject(previousSelection);}
            UnityEngine.Object.DestroyImmediate(eventOwner);UnityEngine.Object.DestroyImmediate(sentinel);
            Check(!registered.Contains(eventSystem)&&EventSystem.current==previousSystem,"temporary EventSystem is removed and prior input system restored");
        }
    }
    static void Admission()
    {
        using var f=new Fixture();
        Set(f.Native.Preview,"inputEnabled",true);Check(f.Workspace.CanOpenGuide(out _),"idle Input ON is compatible with read-only Guide");
        var actions=f.Table.Menu.GetComponentsInChildren<TableAction>();var menu=f.Table.Menu;var selection=f.Snapshot();
        foreach(string blocked in new[]{"native-button","transition","modal","direct-draft","drawing-draft","placement"})
        {
            if(blocked=="native-button")Set(f.Native.Preview,"mouseHeld",true);
            if(blocked=="transition")Set(f.Native.Preview,"focusRequested",true);
            if(blocked=="modal")f.Native.Drawing.NativeState["modal_active"]=true;
            if(blocked=="direct-draft")
            {
                f.Route(XRNode.RightHand,f.Native.Ray(),true);f.Route(XRNode.RightHand,f.Native.Ray(.05f),true);
                Check(f.Native.Direct.Gesturing&&Get(f.Native.Direct,"ghost")!=null,"busy admission fixture owns a real visible direct draft before requesting Guide");
            }
            if(blocked=="drawing-draft")Set(f.Native.Drawing,"first",(Vector2?)Vector2.zero);
            if(blocked=="placement")f.HandField(XRNode.RightHand,"target",f.Native.Host.Placement);
            bool directHeld=f.Native.Direct.Gesturing;
            f.Table.OpenGuide();
            Check(f.Table.Guide?.Visible!=true&&f.Table.GuideNotice.Length>0,"busy admission refuses help: "+blocked);
            Check(((Text)Get(f.Table,"title")).text.Contains(f.Table.GuideNotice),"refusal is displayed immediately in existing menu text");
            Check(f.Table.Menu==menu&&actions.SequenceEqual(f.Table.Menu.GetComponentsInChildren<TableAction>()),"refusal does not rebuild menu or its controls");
            Check(f.Native.Direct.Gesturing==directHeld,"refusal never calls CancelGrabs or cancels a direct draft");
            if(blocked=="native-button")Set(f.Native.Preview,"mouseHeld",false);
            if(blocked=="transition")Set(f.Native.Preview,"focusRequested",false);
            if(blocked=="modal")f.Native.Drawing.NativeState["modal_active"]=false;
            if(blocked=="direct-draft"){f.Native.Direct.Cancel("fixture cleanup");f.Route(XRNode.RightHand,f.Native.Ray(.05f),false);}
            if(blocked=="drawing-draft")Set(f.Native.Drawing,"first",null);
            if(blocked=="placement")f.HandField(XRNode.RightHand,"target",null);
        }
        Check(f.Native.Sent.Count==0&&f.Events.Count==0,"all Guide refusals send zero commands/input");
        Check((bool)Get(f.Native.Preview,"inputEnabled"),"refusal preserves Input ON");
        // Guarded edge observation must never alter a native-held button.
        Set(f.Native.Preview,"triggerWasDown",true);Set(f.Native.Preview,"mouseHeld",true);
        f.Native.Preview.ObserveLocalUiTriggerRelease(XRNode.RightHand);
        Check((bool)Get(f.Native.Preview,"triggerWasDown")&&f.Events.Count==0,"edge rearm is refused while native button is owned");Set(f.Native.Preview,"mouseHeld",false);
    }
    static void Routing(XRNode primary)
    {
        using var f=new Fixture();Property(f.Native.Preview,"PrimaryHand",primary);Set(f.Native.Preview,"inputEnabled",true);
        string before=f.Snapshot();var open=f.Table.Menu.GetComponentsInChildren<TableAction>().Single(action=>action.name=="Guide");
        Check(!f.Table.Menu.GetComponentsInChildren<Text>().Any(t=>t.text.Contains("Arrange space")||t.text.Contains("Actual size")||t.text.Contains("1:1")),"removed handheld entries stay absent");
        var menuRay=CombinedGlassChecks.ControlRay(open.GetComponent<RectTransform>());
        f.Route(primary,menuRay,true);Check(f.Table.Guide?.Visible==true,"actual home TableAction opens Guide for "+primary);
        var panel=f.Table.Guide;var keyRay=CombinedGlassChecks.ControlRay(Button(panel,"Local key M").GetComponent<RectTransform>());
        f.Route(primary,keyRay,true);Check(panel.Query=="","still-held opening press cannot type a key");f.Route(primary,keyRay,false);
        Check(!(bool)Get(f.Native.Preview,"triggerWasDown"),"consumed primary release rearms only its local trigger edge");
        f.Route(primary,keyRay,true);f.Route(primary,keyRay,false);Check(panel.Query=="m","new deliberate key press types locally");
        var menuPose=new Pose(f.Table.Menu.position,f.Table.Menu.rotation);f.Route(primary,keyRay,false,true);f.Route(primary,keyRay,false,false);
        Check(!f.Workspace.IsHolding&&f.Table.Menu.position==menuPose.position&&f.Table.Menu.rotation==menuPose.rotation,"grip on Guide never grabs handheld menu");
        var closeRay=CombinedGlassChecks.ControlRay(Button(panel,"Close Guide").GetComponent<RectTransform>());
        f.Route(primary,closeRay,true);Check(!panel.Visible,"actual close action hides Guide");
        f.Route(primary,f.Native.Ray(),true);Check(!f.Native.Direct.Gesturing,"held close press cannot become underlying model drag");f.Route(primary,f.Native.Ray(),false);
        Check(f.Snapshot()==before&&f.Native.Sent.Count==0&&f.Events.Count==0,"Guide open/search/close preserve input, selection, geometry, revision and history with zero messages");
        f.Route(primary,f.Native.Ray(),true);Check(f.Native.Direct.Gesturing,"first fresh direct press after Guide still works for "+primary);f.Route(primary,f.Native.Ray(),false);
        // Off-hand local release must not rearm the primary hand's edge.
        XRNode other=primary==XRNode.RightHand?XRNode.LeftHand:XRNode.RightHand;Set(f.Native.Preview,"triggerWasDown",true);
        f.Native.Preview.ObserveLocalUiTriggerRelease(other);Check((bool)Get(f.Native.Preview,"triggerWasDown"),"off-hand Guide release never alters primary edge");
        f.Native.Preview.ObserveLocalUiTriggerRelease(primary);
        f.Table.OpenGuide();panel=f.Table.Guide;
        // A nearer native image fences Guide. Read-only help cannot click through it.
        f.ScreenRoot.transform.position=Vector3.forward;
        var headRay=new Ray(Vector3.zero,panel.VisualRoot.transform.position.normalized);Check(panel.Raycast(headRay,out _),"fixture aims through Guide body");
        f.Route(primary,headRay,true);Check(!(bool)f.HandValue(primary,"guideTriggerOwned"),"nearer visible Blender image prevents Guide from capturing input");f.Route(primary,headRay,false);
    }
    static void HeldEditingAndOffhand()
    {
        using var f=new Fixture();var camera=Camera.main;camera.transform.position=Vector3.right*.9f;f.Table.OpenGuide();camera.transform.position=Vector3.zero;var panel=f.Table.Guide;
        var keyRay=CombinedGlassChecks.ControlRay(Button(panel,"Local key M").GetComponent<RectTransform>());
        f.Route(XRNode.RightHand,f.Native.Ray(),true);Check(f.Native.Direct.Gesturing,"existing primary controller owns a real direct gesture");
        var controls=panel.Controls.ToArray();f.Route(XRNode.LeftHand,keyRay,true);f.Route(XRNode.LeftHand,keyRay,false);
        Check(panel.Query==""&&controls.SequenceEqual(panel.Controls)&&f.Native.Direct.Gesturing&&f.Native.Sent.Count==0,"off-hand Guide press during direct editing does not search, rebuild, cancel or send input");
        f.Route(XRNode.RightHand,keyRay,true);Check(f.Native.Direct.Gesturing&&Get(f.Native.Direct,"ghost")!=null,"visible Guide does not intercept selected editing hand's active draft route");
        f.Native.Direct.Cancel("fixture cleanup");f.Route(XRNode.RightHand,f.Native.Ray(),false);f.Route(XRNode.LeftHand,keyRay,true);f.Route(XRNode.LeftHand,keyRay,false);
        Check(panel.Query=="m","local keys work again after edit ends, without replay");
        controls=panel.Controls.ToArray();Set(f.Native.Preview,"mouseHeld",true);int events=f.Events.Count;
        f.Route(XRNode.LeftHand,keyRay,true);f.Route(XRNode.LeftHand,keyRay,false);
        Check(panel.Query=="m"&&controls.SequenceEqual(panel.Controls)&&(bool)Get(f.Native.Preview,"mouseHeld")&&f.Events.Count==events,"off-hand Guide search while native input holds a button preserves that ownership and queues no input");
        Set(f.Native.Preview,"mouseHeld",false);
    }
    static void ReviewCoexistence()
    {
        using var f=new Fixture();var obj=new GameObject("Guide independent review");obj.SetActive(false);
        try
        {
            var review=obj.AddComponent<PendingCommandPanel>();Invoke(review,"Awake");review.head=Camera.main.transform;
            f.Table.OpenGuide();Check(f.Table.Guide?.Visible==true,"Guide opens before a cached pending review appears");
            review.ShowComposition("Review this plan before confirming.\nNo tutorial step executes an edit.",DateTime.UtcNow.AddMinutes(2),true);
            string text=obj.GetComponent<TextMesh>().text;bool reviewed=review.AllPagesReviewed;
            f.Route(XRNode.RightHand,new Ray(Vector3.zero,Vector3.forward),false);
            Check(!f.Table.Guide.Visible&&review.Visible&&review.AllPagesReviewed==reviewed&&obj.GetComponent<TextMesh>().text==text,"new cached review hides only Guide and preserves actual review fence/content");
            f.Table.OpenGuide();Check(!f.Table.Guide.Visible&&f.Table.GuideNotice.Contains("voice"),"visible voice review blocks opening help without cancellation");
            review.Hide();f.Table.OpenGuide();using var popup=new ToolAvailabilityPopup(null);popup.Show(true,"builtin.shear","Use Blender's 2D view for this tool.",Camera.main,0);
            Check(f.Table.Guide.Visible&&popup.Visible,"independent informational availability popup retains its own lifetime");
            popup.Hide();Check(f.Table.Guide.Visible,"popup dismissal does not close Guide");
            var newOwner=new GameObject("Guide late voice owner");newOwner.SetActive(false);
            try
            {
                Set(f.Workspace,"voice",newOwner.AddComponent<VoiceUiAdapter>());
                f.Route(XRNode.RightHand,new Ray(Vector3.zero,Vector3.forward),false);
                Check(!f.Table.Guide.Visible&&f.Native.Sent.Count==0&&f.Events.Count==0,"no-owner to known voice-owner transition closes Guide for rediscovery without edits or polling");
            }
            finally{UnityEngine.Object.DestroyImmediate(newOwner);}
        }
        finally{UnityEngine.Object.DestroyImmediate(obj);}
    }
    static void Capture(Camera camera)
    {
        string output=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");if(string.IsNullOrEmpty(output))return;Directory.CreateDirectory(output);
        using var panel=new SearchableGuidePanel();camera.transform.SetPositionAndRotation(Vector3.zero,Quaternion.identity);camera.fieldOfView=65;camera.cullingMask=1<<31;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.045f,.055f,.07f);panel.Open(camera);
        void Save(string file)
        {foreach(var t in panel.VisualRoot.GetComponentsInChildren<Transform>(true))t.gameObject.layer=31;panel.VisualRoot.GetComponent<Canvas>().worldCamera=camera;AllTextFits(panel);typeof(GlassChecks).GetMethod("Render",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{camera,Path.Combine(output,file)});}
        panel.Search("move");Save("guide-local-search.png");panel.Read("move");Save("guide-step-instructions.png");
    }
    sealed class Fixture:IDisposable
    {
        public readonly DirectModelEditingChecks.Fixture Native=new DirectModelEditingChecks.Fixture();
        public readonly WorkspaceInteraction Workspace;
        public readonly TablePlacement Table;
        public readonly BlenderScreen Screen;
        public readonly GameObject ScreenRoot;
        readonly GameObject owner;readonly Material material;readonly PreviewInteraction previous;
        readonly Type handType=typeof(WorkspaceInteraction).GetNestedType("Hand",BindingFlags.NonPublic);
        readonly object left,right;
        readonly WorkspaceArrangement arrangement;
        public Queue<JObject> Events=>(Queue<JObject>)Get(Native.Preview,"events");
        public Fixture()
        {
            previous=PreviewInteraction.Current;typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null,new object[]{Native.Preview});
            owner=new GameObject("Guide route fixture");Workspace=owner.AddComponent<WorkspaceInteraction>();Workspace.enabled=false;
            arrangement=owner.AddComponent<WorkspaceArrangement>();Property(arrangement,"Surfaces",owner.AddComponent<WorkspaceSurfaces>());Set(arrangement,"scene",Native.Host);
            Table=owner.AddComponent<TablePlacement>();Set(Native.Host,"table",Table);material=new Material(Shader.Find("UI/Default"));Table.Initialize(Native.Host.Placement,material);
            Set(Table,"seeded",true);Table.Place();Invoke(Table,"CreatePanel");Table.Menu.SetPositionAndRotation(new Vector3(-.8f,.1f,1),Quaternion.identity);Table.Menu.gameObject.SetActive(true);
            Screen=Native.Host.gameObject.AddComponent<BlenderScreen>();ScreenRoot=new GameObject("Guide foreign native image",typeof(RectTransform),typeof(Canvas));ScreenRoot.transform.position=Vector3.forward*3;ScreenRoot.transform.localScale=Vector3.one*.001f;
            var body=new GameObject("Native image body",typeof(RectTransform),typeof(RoundedGlassImage));body.transform.SetParent(ScreenRoot.transform,false);body.GetComponent<RectTransform>().sizeDelta=new Vector2(1800,1100);
            var image=new GameObject("Native image pixels",typeof(RectTransform),typeof(RawImage));image.transform.SetParent(ScreenRoot.transform,false);image.GetComponent<RectTransform>().sizeDelta=new Vector2(1800,1100);
            Set(Screen,"canvasObject",ScreenRoot);Set(Screen,"body",body);Set(Screen,"image",image.GetComponent<RawImage>());Set(Screen,"buttons",Array.Empty<Button>());Set(Native.Preview,"screen",Screen);
            left=Activator.CreateInstance(handType,true);right=Activator.CreateInstance(handType,true);HandField(XRNode.LeftHand,"node",XRNode.LeftHand);HandField(XRNode.RightHand,"node",XRNode.RightHand);HandField(XRNode.LeftHand,"armed",true);HandField(XRNode.RightHand,"armed",true);
            Set(Workspace,"left",left);Set(Workspace,"right",right);Set(Workspace,"scene",Native.Host);Set(Workspace,"screen",Screen);Set(Workspace,"arrangement",arrangement);
            Native.Drawing.Session.Select(Native.View.ObjectId);Physics.SyncTransforms();
            Check(Table.IsPlaced&&Native.Host.DisplayPlacementReady&&Native.Host.Placement.gameObject.activeInHierarchy&&Native.View.gameObject.activeInHierarchy,"fixture has an explicitly placed visible native display");
            Check(Native.Host.PickObject(Native.Ray(),out float modelDistance)==Native.View&&Screen.RaycastSurface(Native.Ray(),out float screenDistance)&&modelDistance<screenDistance,
                "actual visible native mesh is the nearest target before the foreign Blender image");
        }
        object Hand(XRNode node)=>node==XRNode.LeftHand?left:right;
        public void HandField(XRNode node,string name,object value)=>Assign(handType.GetField(name),Hand(node),value);
        public object HandValue(XRNode node,string name)=>handType.GetField(name).GetValue(Hand(node));
        public void Route(XRNode node,Ray ray,bool trigger,bool grip=false)
        {
            bool oldTrigger=(bool)HandValue(node,"triggerDown"),oldGrip=(bool)HandValue(node,"gripDown");HandField(node,"triggerDown",trigger);HandField(node,"gripDown",grip);
            Invoke(Workspace,"RouteHand",Hand(node),Hand(node==XRNode.LeftHand?XRNode.RightHand:XRNode.LeftHand),new Pose(ray.origin,Quaternion.LookRotation(ray.direction)),ray,grip,trigger,grip&&!oldGrip,trigger&&!oldTrigger,Vector2.zero,false);
        }
        public string Snapshot()=>new JObject { ["selection"]=Native.Drawing.Session.SelectedId,["spatial"]=Native.Direct.SelectionSnapshot,["native"]=Native.Drawing.NativeState.DeepClone(),["revision"]=Native.Drawing.Session.Revision,
            ["mode"]=Native.Direct.Active,["input"]=(bool)Get(Native.Preview,"inputEnabled"),["position"]=DirectModelEditMath.ToWire(Native.View.NativePosition),["scale"]=DirectModelEditMath.ToWire(Native.View.NativeScale),
            ["history"]=(Get(arrangement,"history") as IList).Count }.ToString();
        public void Dispose()
        {
            Table.Guide?.Dispose();Set(Workspace,"left",null);Set(Workspace,"right",null);Invoke(Table,"OnDestroy");
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null,new object[]{previous});
            UnityEngine.Object.DestroyImmediate(ScreenRoot);UnityEngine.Object.DestroyImmediate(owner);UnityEngine.Object.DestroyImmediate(material);Native.Dispose();
        }
    }
}
