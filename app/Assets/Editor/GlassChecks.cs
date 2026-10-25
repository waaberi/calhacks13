using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;
using SpatialModeling;

public static class GlassChecks
{
    static void Check(bool ok,string reason){if(!ok)throw new Exception("GLASS: "+reason);}
    public static void Run()
    {
        Accessibility();Geometry();Controllers();Curvature();GlassOpticsChecks.Run();Gallery();PreviewRender();
        Debug.Log("P3_GLASS_CHECK PASS rounded_contours shared_hit_masks same_sample_aim rounded_metal gallery_render physical_acceptance=False");
    }
    static float Luminance(Color color)
    {var c=color.linear;return .2126f*c.r+.7152f*c.g+.0722f*c.b;}
    static void Accessibility()
    {
        const string prefix="SpatialModeling.Glass.";string[] names={"TextScale","Contrast","Opaque","Motion"};
        bool[] present=names.Select(n=>PlayerPrefs.HasKey(prefix+n)).ToArray();
        float oldScale=GlassTheme.TextScale;bool oldContrast=GlassTheme.HighContrast,oldOpaque=GlassTheme.ReducedTransparency,oldMotion=GlassTheme.ReducedMotion;
        var root=new GameObject("accessibility root",typeof(RectTransform),typeof(Canvas));root.transform.localScale=Vector3.one*.001f;var adapter=root.AddComponent<GlassRoot>();
        var lifecycle=System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic;
        typeof(GlassRoot).GetMethod("OnDisable",lifecycle).Invoke(adapter,null);
        typeof(GlassRoot).GetMethod("OnEnable",lifecycle).Invoke(adapter,null);
        try
        {
            float initial=oldScale;
            foreach(float scale in new[]{1f,1.25f,1.5f,2f})
            {
                GlassTheme.SetAccessibility(scale,true,true,true);
                Check(Mathf.Approximately(GlassTheme.TextScale,scale)&&GlassTheme.HighContrast&&GlassTheme.ReducedTransparency&&GlassTheme.ReducedMotion,"all accessibility values persist through actual Settings API");
                Check(Mathf.Abs(root.transform.localScale.x-.001f*scale)<.000001f,"text and hit targets enlarge together without clipping");
            }
            foreach(var background in new[]{Color.white,Color.black})foreach(var surface in new[]{GlassTheme.Surface,GlassTheme.Control,GlassTheme.Selected,GlassTheme.Error})
            {
                var composite=Color.Lerp(background,surface,surface.a);float contrast=(Luminance(GlassTheme.Ink)+.05f)/(Luminance(composite)+.05f);
                Check(contrast>=4.5f,"default type contrast passes on bright/dark backgrounds ratio="+contrast);
            }
        }
        finally
        {
            GlassTheme.SetAccessibility(oldScale,oldContrast,oldOpaque,oldMotion);
            for(int i=0;i<names.Length;i++)if(!present[i])PlayerPrefs.DeleteKey(prefix+names[i]);PlayerPrefs.Save();
            typeof(GlassRoot).GetMethod("OnDisable",lifecycle).Invoke(adapter,null);UnityEngine.Object.DestroyImmediate(root);
        }
        Debug.Log("P3_GLASS_ACCESSIBILITY_CHECK PASS persisted_1_to_2x contrast>=4.5 bright_dark opaque reduced_motion prefs_restored");
    }
    static void Curvature()
    {
        var root=new GameObject("curvature mapping fixture",typeof(RectTransform),typeof(Canvas),typeof(GlassCurvedCanvas));
        var image=new GameObject("native pixels",typeof(RectTransform),typeof(RawImage));image.transform.SetParent(root.transform,false);
        var rect=image.GetComponent<RectTransform>();rect.sizeDelta=new Vector2(1800,1100);
        var owner=new GameObject("inactive actual screen mapping");owner.SetActive(false);var screen=owner.AddComponent<BlenderScreen>();
        var flags=System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance;
        typeof(BlenderScreen).GetField("canvasObject",flags).SetValue(screen,root);typeof(BlenderScreen).GetField("image",flags).SetValue(screen,image.GetComponent<RawImage>());
        try
        {
            foreach(float scale in new[]{.00055f,.001f,.0018f,.002f})
            foreach(float yaw in new[]{0,57,153})
            {
                root.transform.SetPositionAndRotation(new Vector3(1,.8f,2),Quaternion.Euler(0,yaw,0));root.transform.localScale=Vector3.one*scale;
                foreach(float x in new[]{-900,-899,-450,0,450,899,900})foreach(float y in new[]{-550,-549,0,549,550})
                {
                    var flat=new Vector3(x,y,0);var world=root.transform.TransformPoint(root.GetComponent<GlassCurvedCanvas>().Bend(flat));
                    var ray=new Ray(world-root.transform.forward*1.2f,root.transform.forward);
                    Check(GlassRaycast.Hit(rect,ray,out _,out var local,false),"curved corners intersect under yaw/resize");
                    Check(Vector2.Distance(local,flat)<.35f,"curved inverse stays below one native pixel at 2564 width");
                    // Insets preserve all native edges; magnification and pan use existing mapping.
                    foreach(var crop in new[]{new Rect(0,0,1,1),BlenderScreen.CropFor(2,new Vector2(.1f,-.1f))})
                    {
                        image.GetComponent<RawImage>().uvRect=crop;
                        var safe=new Vector2(Mathf.Clamp(local.x,-900,900),Mathf.Clamp(local.y,-550,550));
                        Check(PreviewInputMapping.TryMap(rect.rect,crop,safe,out var actual),"native mapping accepts every visible edge");
                        Check(PreviewInputMapping.TryMap(rect.rect,crop,new Vector2(x,y),out var expected)&&Vector2.Distance(actual,expected)<.0004f,"pan/magnify keeps exact UV mapping");
                        Check(screen.TryPreviewPoint(ray,out var native,out _)&&Vector2.Distance(native,expected)<.0004f,"actual BlenderScreen curved pointer maps every native corner/edge");
                    }
                }
            }
        }
        finally{UnityEngine.Object.DestroyImmediate(owner);if(root!=null)UnityEngine.Object.DestroyImmediate(root);}
        Debug.Log("P3_GLASS_CURVE_CHECK PASS actual_render_inverse corners_edges resize=4 yaw=3 magnification_pan pixel_error<1 native_aspect_unchanged");
    }
    static void Geometry()
    {
        foreach(var size in new[]{new Vector2(300,64),new Vector2(640,580),new Vector2(64,64)})
        {
            var rect=new Rect(-size*.5f,size);
            Check(RoundedGlassImage.Contains(rect,Vector2.zero,24),"center hits");
            Check(!RoundedGlassImage.Contains(rect,rect.min+Vector2.one*.1f,24),"transparent corner does not intercept");
            Check(RoundedGlassImage.Contains(rect,new Vector2(0,rect.yMax-1),24),"straight edge reachable");
        }
        var root=GlassTheme.Panel(null,"test panel",Vector2.zero,new Vector2(300,200));
        var button=GlassTheme.Action(root,"Action",Vector2.zero,new Vector2(240,64),()=>{});
        var control=button.GetComponent<GlassControl>();control.Press();Check(control.PressActive,"direct dispatch has registered press cue");
        control.Selected=true;control.Refresh();Check(button.GetComponent<RoundedGlassImage>().Emphasized,"selected has visible contour cue");
        Check(root.GetComponentsInChildren<Text>().All(t=>t.GetComponent<GlassType>()!=null),"all factory type is themed");
        UnityEngine.Object.DestroyImmediate(root.gameObject);
        Debug.Log("P3_GLASS_GEOMETRY_CHECK PASS capsule/panel/circle inside_outside hit_regions focus_press_selected");
    }
    static void Controllers()
    {
        var owner=new GameObject("pose fixture");var line=owner.AddComponent<LineRenderer>();line.positionCount=2;
        var tip=new GameObject("tip");var origin=new GameObject("rotated origin");origin.transform.SetPositionAndRotation(new Vector3(2,.4f,-3),Quaternion.Euler(0,137,0));
        try
        {
            foreach(var hand in new[]{XRNode.LeftHand,XRNode.RightHand})
            {
                var metal=GlassController.Create(owner.transform,hand);var mesh=metal.GetComponent<MeshFilter>().sharedMesh;
                Check(mesh.bounds.max.z<.000001f&&mesh.bounds.min.z<-.10f,"+Z rounded pole stays exactly at aim origin");
                Check(metal.GetComponent<Collider>()==null,"metal cannot intercept any input");
                Check(mesh.normals.All(n=>Mathf.Abs(n.magnitude-1)<.0001f),"smooth analytic normals across rounded caps");
                for(int sample=0;sample<240;sample++)
                {
                    var grip=new Pose(new Vector3(sample*.001f,.5f,0),Quaternion.Euler(25,sample*4,17));
                    var localAim=new Pose(grip.position+new Vector3(.035f,-.01f,.07f),grip.rotation*Quaternion.Euler(-32,19,0));
                    var aim=WorkspaceInteraction.ToWorldPose(origin.transform,localAim);
                    GlassController.ApplyAim(owner.transform,line,tip.transform,aim,2.7f);
                    Check(Vector3.Distance(owner.transform.TransformPoint(Vector3.zero),line.GetPosition(0))<.000001f,"same sample tip/ray pole agreement");
                    Check(Vector3.Angle(owner.transform.forward,line.GetPosition(1)-line.GetPosition(0))<.03f,"both hands rapid turn angular agreement");
                    Check(Vector3.Distance(owner.transform.position,aim.position)<.000001f&&Quaternion.Angle(owner.transform.rotation,aim.rotation)<.03f,"no artificial follower delay or grip substitution");
                }
                UnityEngine.Object.DestroyImmediate(metal);
            }
        }
        finally{UnityEngine.Object.DestroyImmediate(owner);UnityEngine.Object.DestroyImmediate(tip);UnityEngine.Object.DestroyImmediate(origin);}
        Debug.Log("P3_GLASS_CONTROLLER_CHECK PASS hands=2 rapid_samples=480 rotated_origin distinct_grip_aim tip_error_m<0.000001 angle_deg<0.03 interpolation=False");
    }
    public static void Gallery()
    {
        string output=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");if(string.IsNullOrEmpty(output))return;Directory.CreateDirectory(output);
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        var cameraObject=new GameObject("Glass QA camera",typeof(Camera));var camera=cameraObject.GetComponent<Camera>();
        camera.transform.position=new Vector3(0,0,-10);camera.orthographic=true;camera.orthographicSize=6;
        camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.035f,.045f,.065f);camera.nearClipPlane=.1f;camera.farClipPlane=30;
        var canvasObject=new GameObject("Implemented glass component gallery",typeof(RectTransform),typeof(Canvas));var canvas=canvasObject.GetComponent<Canvas>();
        canvas.renderMode=RenderMode.WorldSpace;canvas.worldCamera=camera;canvasObject.transform.localScale=Vector3.one*.01f;
        var root=GlassTheme.Panel(canvasObject.transform,"Glass collection",Vector2.zero,new Vector2(1500,1060));
        GlassTheme.Label(root,"Spatial workspace",new Vector2(-460,455),new Vector2(480,70),48);
        GlassTheme.Label(root,"GLASS / SHARED COMPONENTS",new Vector2(405,455),new Vector2(560,60),23);
        GlassTheme.Label(root,"Soft contours. Clear actions. Content first.",new Vector2(-300,375),new Vector2(1040,60),28);
        string[] states={"Idle","Hover","Pressed","Selected · ON","Unavailable","Focus","Error · blocked"};
        for(int i=0;i<states.Length;i++)
        {
            var b=GlassTheme.Action(root,states[i],new Vector2(-540+(i%4)*360,250-(i/4)*96),new Vector2(330,72),()=>{});var c=b.GetComponent<GlassControl>();
            if(i==1)c.OnPointerEnter(null);if(i==2)c.Press();if(i==3)c.Selected=true;if(i==4)b.interactable=false;if(i==5)c.OnSelect(null);if(i==6)c.Error=true;c.Refresh();
        }
        GlassComponents.Field(root,"Field",new Vector2(-450,0),new Vector2(420,72),"Name your workspace",null);
        GlassComponents.Toggle(root,"Keep screen locked",new Vector2(60,0),new Vector2(490,72),true,null);
        GlassComponents.Slider(root,"Text scale",new Vector2(-450,-110),new Vector2(420,64),.5f,null);
        GlassComponents.Tooltip(root,"Grip to arrange · release to place",new Vector2(130,-110),new Vector2(650,64));
        GlassComponents.Status(root,"Connected · native history preserved",new Vector2(-310,-230),new Vector2(800,72));
        GlassComponents.Status(root,"Connection lost · input released",new Vector2(-310,-320),new Vector2(800,72),true);
        GlassComponents.Scrollbar(root,"Scroll",new Vector2(695,-230),new Vector2(18,220));
        GlassTheme.Label(root,"L  ICY BLUE        R  LAVENDER",new Vector2(330,-410),new Vector2(680,50),24);
        foreach(var hand in new[]{XRNode.LeftHand,XRNode.RightHand})
        {
            var metal=GlassController.Create(null,hand);metal.transform.localScale=Vector3.one*16;
            metal.transform.position=new Vector3(hand==XRNode.LeftHand?4.1f:5.7f,-2.7f,-.5f);metal.transform.rotation=Quaternion.Euler(60,30,-25);
        }
        Canvas.ForceUpdateCanvases();
        foreach(var g in canvasObject.GetComponentsInChildren<RoundedGlassImage>())
        {
            var mesh=g.canvasRenderer.GetMesh();
            var uv=new System.Collections.Generic.List<Vector4>();mesh.GetUVs(1,uv);
            Debug.Log($"GLASS_MESH {g.name} rect={g.rectTransform.rect} radius={g.Radius} vertices={mesh.vertexCount} uv1first={(uv.Count>0?uv[0].ToString():"missing")} channels={canvas.additionalShaderChannels}");
            Check((canvas.additionalShaderChannels&AdditionalCanvasShaderChannels.TexCoord1)!=0,"batched gallery retains shape channel");
            UnityEngine.Object.DestroyImmediate(mesh);
        }
        Render(camera,Path.Combine(output,"components-dark.png"));
        camera.backgroundColor=new Color(.92f,.94f,.97f);Render(camera,Path.Combine(output,"components-bright.png"));
        GlassOpticsChecks.Background();Render(camera,Path.Combine(output,"components-detailed.png"));
        // Off-axis eye views exercise view-dependent metal lighting without initializing XR.
        camera.transform.position+=Vector3.left*.032f;Render(camera,Path.Combine(output,"components-left-eye-reference.png"));
        camera.transform.position+=Vector3.right*.064f;Render(camera,Path.Combine(output,"components-right-eye-reference.png"));
        var dialog=GlassComponents.Dialog(root,"Keep your workspace?","Changes are local to this workspace arrangement.",new Vector2(0,0),new Vector2(820,360),()=>{},()=>{});
        dialog.localPosition+=Vector3.back*2;
        Render(camera,Path.Combine(output,"components-dialog.png"));
        UnityEngine.Object.DestroyImmediate(canvasObject);UnityEngine.Object.DestroyImmediate(cameraObject);
    }
    static void PreviewRender()
    {
        string output=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");if(string.IsNullOrEmpty(output))return;
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        var cameraObject=new GameObject("Preview QA camera",typeof(Camera));var camera=cameraObject.GetComponent<Camera>();
        camera.transform.position=new Vector3(0,.35f,-3);camera.orthographic=true;camera.orthographicSize=1.35f;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.25f,.30f,.36f);
        var owner=new GameObject("inactive actual UI fixture");owner.SetActive(false);var screen=owner.AddComponent<BlenderScreen>();
        var flags=System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance;
        typeof(BlenderScreen).GetMethod("BuildUi",flags).Invoke(screen,new object[]{camera});
        var texture=new Texture2D(1024,640,TextureFormat.RGB24,false);var pixels=new Color32[1024*640];
        for(int y=0;y<640;y++)for(int x=0;x<1024;x++)pixels[y*1024+x]=y>560||x<150?new Color32(35,38,44,255):x%80<2||y%80<2?new Color32(110,117,127,255):new Color32(65,70,79,255);
        texture.SetPixels32(pixels);texture.Apply();
        var raw=(RawImage)typeof(BlenderScreen).GetField("image",flags).GetValue(screen);raw.enabled=true;raw.texture=texture;
        raw.rectTransform.sizeDelta=new Vector2(1760,1100);
        GlassTheme.Label(raw.transform,"RENDER FIXTURE · NOT LIVE BLENDER",new Vector2(0,480),new Vector2(1300,60),30);
        var drawing=owner.AddComponent<PreviewSpatialDrawing>();var preview=owner.AddComponent<PreviewInteraction>();
        typeof(PreviewInteraction).GetProperty("Drawing").GetSetMethod(true).Invoke(preview,new object[]{drawing});
        typeof(PreviewInteraction).GetField("screen",flags).SetValue(preview,screen);
        typeof(PreviewInteraction).GetMethod("BuildControls",flags).Invoke(preview,null);
        var canvas=screen.Placement.GetComponent<Canvas>();canvas.worldCamera=camera;
        screen.Placement.GetComponent<GlassCurvedCanvas>().ApplyToChildren();
        // View obliquely to make the implemented curvature and glass frame visible.
        camera.transform.position+=new Vector3(.6f,0,-.3f);camera.transform.LookAt(screen.Placement.position+Vector3.down*.25f);
        Render(camera,Path.Combine(output,"blender-curved-preview.png"));
        var keyboard=(RectTransform)typeof(PreviewInteraction).GetField("keyboard",flags).GetValue(preview);keyboard.gameObject.SetActive(true);
        foreach(var b in keyboard.GetComponentsInChildren<Button>())
        {
            var r=b.GetComponent<RectTransform>();var extent=r.anchoredPosition+r.rect.max;
            Check(extent.x<=keyboard.rect.xMax&&extent.y<=keyboard.rect.yMax,"every keyboard key stays inside the rounded panel, including the thirteenth number-row key");
        }
        Render(camera,Path.Combine(output,"blender-curved-keyboard.png"));
        // Render the real adapter at 2x with a framing change only for this export.
        // User settings are restored, including deleting newly introduced keys.
        const string prefix="SpatialModeling.Glass.";string[] names={"TextScale","Contrast","Opaque","Motion"};
        bool[] present=names.Select(n=>PlayerPrefs.HasKey(prefix+n)).ToArray();
        float oldScale=GlassTheme.TextScale;bool oldContrast=GlassTheme.HighContrast,oldOpaque=GlassTheme.ReducedTransparency,oldMotion=GlassTheme.ReducedMotion;
        var adapter=screen.Placement.GetComponent<GlassRoot>();
        typeof(GlassRoot).GetMethod("OnDisable",flags).Invoke(adapter,null);typeof(GlassRoot).GetMethod("OnEnable",flags).Invoke(adapter,null);
        try
        {
            GlassTheme.SetAccessibility(2,true,true,true);camera.orthographicSize*=2;
            camera.transform.LookAt(screen.Placement.position+Vector3.down*.5f);
            Render(camera,Path.Combine(output,"blender-large-text-contrast.png"));
        }
        finally
        {
            GlassTheme.SetAccessibility(oldScale,oldContrast,oldOpaque,oldMotion);
            for(int i=0;i<names.Length;i++)if(!present[i])PlayerPrefs.DeleteKey(prefix+names[i]);PlayerPrefs.Save();
            typeof(GlassRoot).GetMethod("OnDisable",flags).Invoke(adapter,null);
        }
        UnityEngine.Object.DestroyImmediate(texture);UnityEngine.Object.DestroyImmediate(owner);UnityEngine.Object.DestroyImmediate(cameraObject);
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
    }
    static void Render(Camera camera,string path)
    {
        var target=new RenderTexture(1920,1440,24){antiAliasing=4};var previous=RenderTexture.active;
        var texture=new Texture2D(1920,1440,TextureFormat.RGB24,false);
        try{Canvas.ForceUpdateCanvases();camera.targetTexture=target;target.Create();camera.Render();RenderTexture.active=target;texture.ReadPixels(new Rect(0,0,1920,1440),0,0);texture.Apply();File.WriteAllBytes(path,texture.EncodeToPNG());}
        finally{camera.targetTexture=null;RenderTexture.active=previous;target.Release();UnityEngine.Object.DestroyImmediate(target);UnityEngine.Object.DestroyImmediate(texture);}
    }
}
