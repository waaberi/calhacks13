using System;
using System.Linq;
using System.Reflection;
using SpatialModeling;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.UI;

public static class GlassStabilityChecks
{
    static void Check(bool ok,string reason){if(!ok)throw new Exception("GLASS_STABILITY: "+reason);}
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    public static void Run(){IdleMesh();Layout();Stereo();}
    public static void RunWithController(){Run();GlassControllerChecks.Run();}
    static void IdleMesh()
    {
        var root=new GameObject("idle glass invalidation fixture",typeof(RectTransform),typeof(Canvas));
        try
        {
            var button=GlassTheme.Action(root.transform,"Stable control",Vector2.zero,new Vector2(300,80),()=>{});
            var image=button.GetComponent<RoundedGlassImage>();var state=button.GetComponent<GlassControl>();
            GlassTheme.State(button);Canvas.ForceUpdateCanvases();int dirty=0;image.RegisterDirtyVerticesCallback(()=>dirty++);
            for(int i=0;i<120;i++){GlassTheme.State(button);state.Refresh();}
            Check(dirty==0,"idle repeated production state refresh must not rebuild rounded/curved meshes");
            GlassTheme.State(button,true);Check(dirty>0,"actual selected-state change still invalidates geometry");dirty=0;
            for(int i=0;i<120;i++){GlassTheme.State(button,true);state.Refresh();}
            Check(dirty==0&&state.Selected,"stable selected state retains visible cue without mesh churn");
            state.Hover();state.Refresh();dirty=0;
            for(int i=0;i<120;i++){state.ClearHover();state.Hover();state.Refresh();}
            Check(dirty==0,"stationary controller hover does not rebuild the same geometry repeatedly");
        }
        finally{UnityEngine.Object.DestroyImmediate(root);}
        Debug.Log("GLASS_IDLE_GEOMETRY_CHECK PASS actual_dirty_callback idle_selected_hover=360 unchanged_refreshes zero_rebuild_requests meaningful_state_change_retained");
    }
    static void Layout()
    {
        var existing=Resources.FindObjectsOfTypeAll<GameObject>().ToHashSet();
        var owner=new GameObject("inactive glass grid fixture");owner.SetActive(false);
        try
        {
            var camera=new GameObject("glass layout camera",typeof(Camera)).GetComponent<Camera>();
            var screen=owner.AddComponent<BlenderScreen>();typeof(BlenderScreen).GetMethod("BuildUi",Private).Invoke(screen,new object[]{camera});
            var drawing=owner.AddComponent<PreviewSpatialDrawing>();var preview=owner.AddComponent<PreviewInteraction>();
            typeof(PreviewInteraction).GetProperty("Drawing").GetSetMethod(true).Invoke(preview,new object[]{drawing});
            typeof(PreviewInteraction).GetField("screen",Private).SetValue(preview,screen);typeof(PreviewInteraction).GetMethod("BuildControls",Private).Invoke(preview,null);
            var panel=(RectTransform)typeof(PreviewInteraction).GetField("panel",Private).GetValue(preview);
            var actions=panel.GetComponentsInChildren<Button>();Check(actions.Length==12,"all twelve production preview controls retained");
            Check(panel.rect.height==176,"input controls fit a compact two-row surface without a lower prose area");
            Check(panel.GetComponentsInChildren<Text>().Length==actions.Length,"input panel contains button captions only, with no status/instruction writing underneath");
            var rows=actions.GroupBy(b=>b.GetComponent<RectTransform>().anchoredPosition.y).OrderByDescending(g=>g.Key).ToArray();
            Check(rows.Length==2&&rows.All(g=>g.Count()==6),"complete action grid is balanced six by two");
            var columns=rows[0].Select(b=>b.GetComponent<RectTransform>().anchoredPosition.x).OrderBy(x=>x).ToArray();
            Check(columns.SequenceEqual(rows[1].Select(b=>b.GetComponent<RectTransform>().anchoredPosition.x).OrderBy(x=>x)),"both action rows share exact column centers");
            foreach(var b in actions)
            {
                var rect=b.GetComponent<RectTransform>();Check(panel.rect.Contains(rect.anchoredPosition+rect.rect.min)&&panel.rect.Contains(rect.anchoredPosition+rect.rect.max),"button remains inside its panel: "+b.name);
                Check(b.GetComponentInChildren<Text>().rectTransform.rect.width<=rect.rect.width-24,"control text has safe horizontal inset: "+b.name);
            }
            var curve=screen.Placement.GetComponent<GlassCurvedCanvas>();
            Check(curve!=null&&panel.GetComponentInParent<GlassCurvedCanvas>()==curve,"native view and its controls share one cylinder instance");
            foreach(var graphic in panel.GetComponentsInChildren<Graphic>())
                Check(graphic.GetComponent<GlassCurveMesh>()!=null&&graphic.GetComponentInParent<GlassCurvedCanvas>()==curve,"every panel background, button and caption follows the screen cylinder: "+graphic.name);
            foreach(var b in actions)
            {
                var flat=curve.transform.InverseTransformPoint(b.transform.position);
                var bent=curve.transform.TransformPoint(curve.Bend(flat));
                var ray=new Ray(bent-screen.Placement.forward*.4f,screen.Placement.forward);
                Check(GlassRaycast.Hit(b.GetComponent<RectTransform>(),ray,out _,out var hit)
                    && Vector2.Distance(hit,Vector2.zero)<.02f,"curved button geometry and controller hit contour agree at each column: "+b.name);
            }
            var frame=screen.Placement.GetComponentsInChildren<Button>().Where(b=>b.transform.parent==screen.Placement).ToArray();
            foreach(var removed in new[]{"Show hide button","Reset arrangement","Undo workspace placement","Recover workspace"})
                Check(!frame.Any(b=>b.name==removed),"requested obsolete frame action is absent: "+removed);
            Check(!screen.Placement.GetComponentsInChildren<Text>().Any(t=>t.text=="BLENDER"),"native view has no extra BLENDER title");
            var lockButton=frame.Single(b=>b.name=="Lock Blender screen position");
            var lockFlat=curve.transform.InverseTransformPoint(lockButton.transform.position);
            var lockBent=curve.transform.TransformPoint(curve.Bend(lockFlat));
            var position=screen.Placement.position;var rotation=screen.Placement.rotation;
            Check(screen.HoverController(new Ray(lockBent-screen.Placement.forward*.4f,screen.Placement.forward),true)
                &&screen.PositionLocked&&screen.Placement.position==position&&screen.Placement.rotation==rotation,
                "near-view lock dispatches through the actual curved controller route without moving the screen");
            var keyboard=(RectTransform)typeof(PreviewInteraction).GetField("keyboard",Private).GetValue(preview);keyboard.gameObject.SetActive(true);
            foreach(var b in keyboard.GetComponentsInChildren<Button>())
            {
                var rect=b.GetComponent<RectTransform>();Check(Mathf.Abs(rect.rect.width-128)<.01f,"all basic keyboard rows use the same key width: "+b.name);
                float col=rect.anchoredPosition.x/136+6;Check(Mathf.Abs(col-Mathf.Round(col))<.001f,"keyboard action/key rows share thirteen-column alignment: "+b.name);
                var label=b.GetComponentInChildren<Text>();float preferred=label.cachedTextGeneratorForLayout.GetPreferredWidth(label.text,label.GetGenerationSettings(Vector2.zero))/label.pixelsPerUnit;
                Check(preferred<=label.rectTransform.rect.width+.5f,"keyboard caption fits one line without split words: "+b.name+" preferred="+preferred+" available="+label.rectTransform.rect.width);
                Check(keyboard.rect.Contains(rect.anchoredPosition+rect.rect.min)&&keyboard.rect.Contains(rect.anchoredPosition+rect.rect.max),"keyboard key stays within panel: "+b.name);
            }
            var status=(Text)typeof(BlenderScreen).GetField("status",Private).GetValue(screen);var corners=new Vector3[4];status.rectTransform.GetWorldCorners(corners);
            float statusTop=corners.Max(c=>screen.Placement.InverseTransformPoint(c).y);
            Check(keyboard.anchoredPosition.y+keyboard.rect.yMin>statusTop+12,"keyboard never overlaps native capture status text");
            Check(keyboard.GetComponent<Image>().color.a>=.94f,"typing surface prevents native UI text bleed-through while retaining the glass contour");
        }
        finally{foreach(var go in Resources.FindObjectsOfTypeAll<GameObject>())if(go!=null&&!existing.Contains(go)&&!EditorUtility.IsPersistent(go))UnityEngine.Object.DestroyImmediate(go);}
        Debug.Log("GLASS_GRID_CHECK PASS actual_twelve_controls compact_six_by_two captions_only exact_shared_curve contour_hit_agreement near_view_lock removed_requested_frame_actions uniform_thirteen_column_keyboard inset_text panel_bounds");
    }
    static void Stereo()
    {
        const int size=64;var source=new Texture2DArray(size,size,2,TextureFormat.RGBA32,false,true);
        source.SetPixels(Enumerable.Repeat(new Color(.85f,.08f,.02f,.6f),size*size).ToArray(),0);
        source.SetPixels(Enumerable.Repeat(new Color(.02f,.08f,.85f,.85f),size*size).ToArray(),1);source.Apply();
        var target=new RenderTexture(size,size,0,RenderTextureFormat.ARGB32,RenderTextureReadWrite.Linear){dimension=TextureDimension.Tex2DArray,volumeDepth=2,vrUsage=VRTextureUsage.TwoEyes};target.Create();
        var blur=new Material(Resources.Load<Shader>("GlassBackdropBlur")){enableInstancing=true};
        var surface=new Material(Resources.Load<Shader>("GlassSurface")){enableInstancing=true};
        var metal=new Material(Resources.Load<Shader>("GlassSatinMetal")){enableInstancing=true};metal.SetColor("_BaseColor",GlassTheme.LeftMetal);
        var controller=GlassController.RoundedCylinder();
        var mesh=new Mesh();mesh.vertices=new[]{new Vector3(-1,-1,0),new Vector3(1,-1,0),new Vector3(1,1,0),new Vector3(-1,1,0)};
        mesh.uv=new[]{Vector2.zero,Vector2.right,Vector2.one,Vector2.up};mesh.colors=Enumerable.Repeat(GlassTheme.Surface,4).ToArray();
        mesh.SetUVs(1,Enumerable.Repeat(new Vector4(640,480,36,1),4).ToArray());mesh.triangles=new[]{0,1,2,0,2,3};
        var commands=new CommandBuffer(){name="Glass real two-eye GPU regression"};
        try
        {
            void Begin()
            {
                commands.Clear();commands.SetRenderTarget(target,0,CubemapFace.Unknown,-1);commands.ClearRenderTarget(false,true,Color.clear);
                commands.EnableShaderKeyword("STEREO_INSTANCING_ON");commands.SetInstanceMultiplier(2);
                commands.SetGlobalVector("_BlitScaleBias",new Vector4(1,1,0,0));commands.SetGlobalVector("_BlitTexture_TexelSize",new Vector4(1f/size,1f/size,size,size));commands.SetGlobalTexture("_BlitTexture",source);
            }
            Color32[] Read()
            {
                commands.DisableShaderKeyword("STEREO_INSTANCING_ON");commands.SetInstanceMultiplier(1);Graphics.ExecuteCommandBuffer(commands);
                var request=AsyncGPUReadback.Request(target,0,TextureFormat.RGBA32);request.WaitForCompletion();Check(!request.hasError,"two-eye texture-array readback succeeds");Check(request.layerCount==2,"readback preserves both eye layers");return request.GetData<Color32>(0).ToArray().Concat(request.GetData<Color32>(1).ToArray()).ToArray();
            }
            for(int pass=0;pass<3;pass++)
            {
                Begin();commands.DrawProcedural(Matrix4x4.identity,blur,pass,MeshTopology.Triangles,3,1);var pixels=Read();
                var left=pixels[size/2*size+size/2];var right=pixels[size*size+size/2*size+size/2];
                Check(left.r>150&&left.b<50&&right.b>150&&right.r<50,"real copy/horizontal/vertical shader keeps each eye separate pass="+pass+" left="+left+" right="+right);
                Check(Mathf.Abs(left.a-153)<5&&Mathf.Abs(right.a-217)<5,"RGBA alpha retained independently in both eyes");
            }
            Begin();commands.SetViewProjectionMatrices(Matrix4x4.identity,Matrix4x4.identity);
            commands.SetGlobalVector("_WorldSpaceCameraPos",new Vector4(0,0,-2,1));
            commands.SetGlobalMatrixArray("unity_StereoMatrixVP",new[]{Matrix4x4.identity,Matrix4x4.identity});
            commands.SetGlobalVectorArray("unity_StereoWorldSpaceCameraPos",new[]{new Vector4(0,0,-2,1),new Vector4(0,0,-2,1)});
            commands.SetGlobalTexture("_GlassBackdrop",source);commands.SetGlobalTexture("_GlassSharpBackdrop",source);
            commands.DrawMesh(mesh,Matrix4x4.identity,surface,0,0);var glass=Read();var l=glass[size/2*size+size/2];var r=glass[size*size+size/2*size+size/2];
            Check(l.r>l.b+25&&r.b>r.r+25&&l.a>150&&r.a>150,"actual glass surface samples its own eye's texture-array slice left="+l+" right="+r);
            Begin();commands.SetViewProjectionMatrices(Matrix4x4.identity,Matrix4x4.identity);commands.SetGlobalMatrixArray("unity_StereoMatrixVP",new[]{Matrix4x4.identity,Matrix4x4.identity});
            commands.DrawMesh(controller,Matrix4x4.TRS(new Vector3(.5f,0,.5f),Quaternion.Euler(0,90,0),Vector3.one*10),metal,0,0);var body=Read();
            int leftBody=body.Take(size*size).Count(c=>c.a>100),rightBody=body.Skip(size*size).Count(c=>c.a>100);
            Check(leftBody>30&&Mathf.Abs(leftBody-rightBody)<=4,"actual metallic controller renders in both eye layers left="+leftBody+" right="+rightBody);
        }
        finally
        {
            commands.Clear();commands.DisableShaderKeyword("STEREO_INSTANCING_ON");commands.SetInstanceMultiplier(1);Graphics.ExecuteCommandBuffer(commands);commands.Release();
            target.Release();foreach(var item in new UnityEngine.Object[]{source,target,blur,surface,mesh,metal,controller})UnityEngine.Object.DestroyImmediate(item);
        }
        Debug.Log("GLASS_STEREO_GPU_CHECK PASS actual_D3D_texture_array two_distinct_eyes copy_horizontal_vertical_surface_controller alpha_retained no_cross_eye_contamination");
    }
}
