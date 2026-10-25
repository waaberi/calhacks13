using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using SpatialModeling;
using SpatialModeling.VoiceCore;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

public static class CombinedGlassChecks
{
    // Aim at the actual rendered/hit-test center of curved controls. Flat
    // Transform.position points no longer describe their displayed surface.
    public static Ray ControlRay(RectTransform rect,float distance=.4f)
    {
        var curve=rect.GetComponentInParent<GlassCurvedCanvas>();
        if(curve==null)return new Ray(rect.position-rect.forward*distance,rect.forward);
        var flat=curve.transform.InverseTransformPoint(rect.TransformPoint(rect.rect.center));
        var point=curve.transform.TransformPoint(curve.Bend(flat));
        float angle=flat.x/curve.Radius;
        var normal=curve.transform.TransformDirection(new Vector3(Mathf.Sin(angle),0,Mathf.Cos(angle)));
        return new Ray(point-normal*distance,normal);
    }
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string reason){if(!value)throw new Exception("COMBINED_GLASS: "+reason);}
    static object Get(object owner,string name)=>owner.GetType().GetField(name,Private).GetValue(owner);
    static void Invoke(object owner,string name,params object[] args)=>owner.GetType().GetMethod(name,Private).Invoke(owner,args);
    public static void Run()
    {
        bool had=PlayerPrefs.HasKey(VoiceUiAdapter.TranscriptionPreference);int saved=PlayerPrefs.GetInt(VoiceUiAdapter.TranscriptionPreference);
        bool hadPopups=PlayerPrefs.HasKey(VoiceUiAdapter.SelectionPopupPreference);int savedPopups=PlayerPrefs.GetInt(VoiceUiAdapter.SelectionPopupPreference);
        var existing=new HashSet<GameObject>(Resources.FindObjectsOfTypeAll<GameObject>());
        var owner=new GameObject("inactive combined appearance fixture");owner.SetActive(false);
        try
        {
            PlayerPrefs.DeleteKey(VoiceUiAdapter.TranscriptionPreference);
            PlayerPrefs.DeleteKey(VoiceUiAdapter.SelectionPopupPreference);
            var cam=new GameObject("combined camera",typeof(Camera));cam.tag="MainCamera";
            var voice=owner.AddComponent<VoiceUiAdapter>();Invoke(voice,"Awake");
            var status=(TextMesh)Get(voice,"status");var feedback=(TextMesh)Get(voice,"feedback");
            Invoke(voice,"PlaceStatus");Check(!voice.ShowTranscription&&!status.gameObject.activeSelf,"first run hides passive status/transcription");
            Invoke(voice,"Note","Heard: rotate cube");Check(!feedback.gameObject.activeSelf,"recognized transcript cannot leak through transient feedback when disabled");
            Invoke(voice,"Note","Selected: Cube");Check(!voice.SelectionPopups&&!feedback.gameObject.activeSelf,"selection titles default hidden independently of transcription");
            Invoke(voice,"Note","Cannot edit a disconnected document");Check(feedback.gameObject.activeSelf,"actionable failures stay visible with selection popups OFF");
            var pending=(PendingCommandPanel)Get(voice,"panel");if(Get(pending,"text")==null)Invoke(pending,"Awake");pending.ShowDelete("Delete Cube",DateTime.UtcNow.AddSeconds(15));
            Check(pending.Visible&&pending.gameObject.activeSelf&&pending.GetComponent<TextMesh>().text.Contains("Confirm:"),"actionable delete confirmation stays visible with transcription OFF");
            var session=new VoiceSession();session.Hear(new RecognitionResult("rotate this ninety degrees around x",1));
            Check(session.Pending!=null,"missing target fixture enters pending turn");pending.Show(session.Pending);
            Check(pending.Visible&&pending.GetComponent<TextMesh>().text.Contains("Missing:"),"missing-field question stays available with transcription OFF");
            Check(status.GetComponent<GlassVoiceText>()!=null&&pending.GetComponent<GlassVoiceText>()!=null,"all retained voice dialogs share the glass surface");
            var arrangement=owner.AddComponent<WorkspaceArrangement>();Invoke(arrangement,"Awake");
            var table=owner.AddComponent<TablePlacement>();
            var display=new GameObject("combined display fixture");display.transform.SetParent(owner.transform,false);
            table.Initialize(display.transform,AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            table.SeedFromHead(new Vector3(0,1.65f,0),Vector3.forward);table.Place();
            table.UpdateLeftHandMenu(new Pose(new Vector3(-.3f,1.15f,.3f),Quaternion.identity),new Vector3(0,1.65f,0),true);
            var dockedMenuScale=table.Menu.localScale;table.PinMenu();
            Check(Vector3.Distance(table.Menu.localScale,dockedMenuScale/TablePlacement.DockedMenuFactor)<.000001f,"compact production menu expands to the existing full scale when pinned");
            var page=typeof(TablePlacement).GetNestedType("MenuPage",BindingFlags.NonPublic);
            void Settings()=>Invoke(table,"ChangeMenu",Enum.Parse(page,"Settings"));
            TableAction[] Actions()=>table.Menu.GetComponentsInChildren<TableAction>(true);
            var arrangeNames=Actions().Select(a=>a.name).ToArray();
            foreach(var name in new[]{"Surface detection: ON","Undo placement","Add horizontal plane","Add vertical plane","Manage planes","Actual size","Return to left hand","Clear selection"})
                Check(arrangeNames.Contains(name),"arrange control preserved: "+name);
            foreach(var name in new[]{"Select object","Pin menu here","Recover workspace"})
                Check(!arrangeNames.Contains(name),"human-requested menu action removed: "+name);
            Settings();
            Check(Vector3.Distance(table.Menu.localScale,dockedMenuScale/TablePlacement.DockedMenuFactor)<.000001f,"page rebuild preserves the full pinned menu scale");
            foreach(var name in new[]{"Show room geometry","Auto surfaces on/off","Environment setup","Manage planes","Actual size","Lock Blender screen","Pointer: Right","Back to arrange","Appearance / accessibility","Voice transcription: OFF","Blender view: "+(BlenderViewAppearance.Opaque?"opaque":"transparent")})
                Check(Actions().Any(a=>a.name==name),"Settings control preserved: "+name);
            void Toggle(string label)
            {
                var action=Actions().Single(a=>a.name==label);var rect=action.GetComponent<RectTransform>();
                Physics.SyncTransforms();var ray=ControlRay(rect,.4f);
                Check(table.HoverController(ray,true),"actual menu collider dispatches "+label);
            }
            Toggle("Voice transcription: OFF");
            Check(voice.ShowTranscription&&status.gameObject.activeSelf&&PlayerPrefs.GetInt(VoiceUiAdapter.TranscriptionPreference)==1,"menu toggle shows and saves transcription ON");
            var reload=new GameObject("inactive reload");reload.SetActive(false);var second=reload.AddComponent<VoiceUiAdapter>();Invoke(second,"Awake");
            Check(second.ShowTranscription,"choice survives a new adapter/session");
            Toggle("Voice transcription: ON");Check(!voice.ShowTranscription&&!status.gameObject.activeSelf,"menu toggle hides transcription again");
            Toggle("Selection popups: OFF");Check(voice.SelectionPopups&&PlayerPrefs.GetInt(VoiceUiAdapter.SelectionPopupPreference)==1,"selection popup menu saves ON");
            Invoke(voice,"Note","Selected: Cube");Check(feedback.gameObject.activeSelf&&feedback.text=="Selected: Cube","selection title can be enabled separately");
            var popupReload=new GameObject("inactive selection preference reload");popupReload.SetActive(false);
            var third=popupReload.AddComponent<VoiceUiAdapter>();Invoke(third,"Awake");Check(third.SelectionPopups,"selection preference survives a new adapter/session");
            Toggle("Selection popups: ON");Check(!voice.SelectionPopups&&!feedback.gameObject.activeSelf,"turning popups OFF immediately hides current selection title");
            Invoke(voice,"Note","Deselected: Cube");Check(!feedback.gameObject.activeSelf,"deselection title also stays hidden");
            foreach(var a in Actions().Where(a=>a.GetComponent<RoundedGlassImage>()!=null))
            {
                var rect=a.GetComponent<RectTransform>();Check(rect.anchoredPosition.y-rect.rect.height/2>=-290,"all expanded Settings actions stay in panel");
                Check(a.GetComponent<GlassControl>()!=null,"every retained Settings action receives glass state feedback");
            }
            string output=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");
            if(!string.IsNullOrEmpty(output))
            {
                File.WriteAllText(Path.Combine(output,"combined-menu-controls.json"),JsonUtility.ToJson(new Inventory{arrange=arrangeNames,settings=Actions().Select(a=>a.name).ToArray()},true));
                var camera=cam.GetComponent<Camera>();camera.orthographic=true;camera.orthographicSize=.36f;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.32f,.37f,.43f);
                camera.transform.position=new Vector3(0,0,-1);table.Menu.SetPositionAndRotation(Vector3.zero,Quaternion.identity);table.Menu.GetComponent<Canvas>().worldCamera=camera;
                pending.Hide();feedback.gameObject.SetActive(false);
                typeof(GlassChecks).GetMethod("Render",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{camera,Path.Combine(output,"combined-settings-transcription-off.png")});
                table.Menu.gameObject.SetActive(false);camera.orthographicSize=.6f;pending.head=camera.transform;pending.offset=new Vector3(0,0,1);
                pending.ShowDelete("Delete Cube",DateTime.UtcNow.AddSeconds(15));Invoke(pending,"LateUpdate");
                var promptMaterial=pending.transform.Find("VoiceTextBacking").GetComponent<RoundedGlassImage>().material;
                Check(promptMaterial.renderQueue==4000&&promptMaterial.GetInt("unity_GUIZTestMode")== (int)UnityEngine.Rendering.CompareFunction.Always,"reactivated voice prompt preserves overlay depth and draw order");
                typeof(GlassChecks).GetMethod("Render",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{camera,Path.Combine(output,"combined-voice-confirmation-transcription-off.png")});
                AssertText(Path.Combine(output,"combined-voice-confirmation-transcription-off.png"));
                pending.Hide();voice.SetShowTranscription(true);Invoke(voice,"PlaceStatus");
                typeof(GlassChecks).GetMethod("Render",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{camera,Path.Combine(output,"combined-voice-transcription-on.png")});
                AssertText(Path.Combine(output,"combined-voice-transcription-on.png"));
                voice.SetShowTranscription(false);
            }
            Debug.Log("COMBINED_GLASS_CHECK PASS default_hidden saved_menu_collider_toggle reload no_transcript_leak selection_feedback missing_field delete_confirmation glass_voice retained_arrange_settings_controls");
        }
        finally
        {
            if(had)PlayerPrefs.SetInt(VoiceUiAdapter.TranscriptionPreference,saved);else PlayerPrefs.DeleteKey(VoiceUiAdapter.TranscriptionPreference);PlayerPrefs.Save();
            if(hadPopups)PlayerPrefs.SetInt(VoiceUiAdapter.SelectionPopupPreference,savedPopups);else PlayerPrefs.DeleteKey(VoiceUiAdapter.SelectionPopupPreference);PlayerPrefs.Save();
            foreach(var go in Resources.FindObjectsOfTypeAll<GameObject>())if(go!=null&&!existing.Contains(go)&&!EditorUtility.IsPersistent(go))UnityEngine.Object.DestroyImmediate(go);
        }
    }
    static void AssertText(string path)
    {
        var image=new Texture2D(2,2,TextureFormat.RGB24,false);
        try{image.LoadImage(File.ReadAllBytes(path));Check(image.GetPixels32().Count(p=>p.r>150&&p.g>190&&p.b>80)>200,"actual voice render contains foreground text above glass: "+path);}
        finally{UnityEngine.Object.DestroyImmediate(image);}
    }
    [Serializable] class Inventory{public string[] arrange,settings;}
}
