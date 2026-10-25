using System;
using System.IO;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UI;
using SpatialModeling;

// GPU readback of the real renderer feature and the same material used by live UI.
public static class GlassOpticsChecks
{
    public static GameObject Background()
    {
        var texture=new Texture2D(1024,1024,TextureFormat.RGBA32,false);
        var pixels=new Color[1024*1024];
        for(int y=0;y<1024;y++)for(int x=0;x<1024;x++)
        {
            var color=Color.HSVToRGB((x/1024f*.6f+y/1024f*.2f),.65f,.7f);
            float detail=((x/12+y/12)%2)==0?.7f:1;
            color*=detail;color.a=1;pixels[y*1024+x]=color;
        }
        texture.SetPixels(pixels);texture.Apply();
        var backdrop=GameObject.CreatePrimitive(PrimitiveType.Quad);backdrop.name="Detailed Unity scene backdrop (test fixture)";
        backdrop.transform.position=new Vector3(0,0,3);backdrop.transform.localScale=new Vector3(22,16,1);
        var material=new Material(Shader.Find("Universal Render Pipeline/Unlit"));material.SetTexture("_BaseMap",texture);
        backdrop.GetComponent<MeshRenderer>().sharedMaterial=material;
        return backdrop;
    }
    public static void Run()
    {
        string output=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");
        if(string.IsNullOrEmpty(output))throw new Exception("Missing optics evidence directory");
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        var camera=new GameObject("Optics camera",typeof(Camera)).GetComponent<Camera>();
        camera.transform.position=new Vector3(0,0,-10);camera.orthographic=true;camera.orthographicSize=6;
        camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=Color.clear;
        var background=Background();
        var canvas=new GameObject("Optics actual UI",typeof(RectTransform),typeof(Canvas)).GetComponent<Canvas>();
        canvas.renderMode=RenderMode.WorldSpace;canvas.worldCamera=camera;canvas.transform.localScale=Vector3.one*.01f;
        var panel=GlassTheme.Panel(canvas.transform,"Optical sample",Vector2.zero,new Vector2(800,800));
        panel.gameObject.SetActive(false);var before=Read(camera);
        panel.gameObject.SetActive(true);var material=panel.GetComponent<Image>().material;
        material.SetFloat("_Frost",0);var tinted=Read(camera);material.SetFloat("_Frost",1);
        panel.gameObject.SetActive(true);var after=Read(camera);
        File.WriteAllBytes(Path.Combine(output,"optics-source.png"),before.EncodeToPNG());
        File.WriteAllBytes(Path.Combine(output,"optics-glass.png"),after.EncodeToPNG());
        File.WriteAllBytes(Path.Combine(output,"optics-clear-reference.png"),tinted.EncodeToPNG());
        float sourceDetail=Detail(before),clearDetail=Detail(tinted),glassDetail=Detail(after);
        if(sourceDetail<.001f||glassDetail/clearDetail>.45f)throw new Exception($"Glass failed actual background diffusion source={sourceDetail} clear={clearDetail} glass={glassDetail}");
        material.SetFloat("_Refraction",0);var unbent=Read(camera);material.SetFloat("_Refraction",1);
        float edgeDelta=0;int edgeCount=0;
        for(int y=170;y<598;y++)for(int x=258;x<766;x++)
        {
            // Side strips inside the bevel, excluding the rounded corners.
            if((x<265||x>758)&&y>230&&y<530)
            {edgeDelta+=Vector4.Distance(after.GetPixel(x,y),unbent.GetPixel(x,y));edgeCount++;}
        }
        edgeDelta/=Mathf.Max(1,edgeCount);
        if(edgeDelta<.0003f)throw new Exception($"Glass bevel does not refract scene pixels: {edgeDelta}");
        background.GetComponent<Renderer>().sharedMaterial.SetColor("_BaseColor",new Color(.15f,.7f,1,1));
        var changed=Read(camera);
        if(Vector4.Distance(after.GetPixel(512,384),changed.GetPixel(512,384))<.025f)throw new Exception("Glass does not respond to scene changes");
        background.SetActive(false);var alpha=Read(camera);
        float inside=alpha.GetPixel(512,384).a,outside=alpha.GetPixel(20,20).a;
        if(inside<.35f||inside>.98f||outside>.01f)throw new Exception($"Passthrough alpha lost inside={inside} outside={outside}");
        File.WriteAllBytes(Path.Combine(output,"optics-compositor-fallback.png"),alpha.EncodeToPNG());
        string result=$"P3_GLASS_OPTICS_CHECK PASS real_GPU_diffusion source_detail={sourceDetail:F6} clear_detail={clearDetail:F6} glass_detail={glassDetail:F6} ratio_vs_same_tint={glassDetail/clearDetail:F4} bevel_refraction_delta={edgeDelta:F6} scene_change=True fallback_alpha={inside:F4} outside_alpha={outside:F4} compositor_sampled=False";
        File.WriteAllText(Path.Combine(output,"optics-result.txt"),result);Debug.Log(result);
        foreach(var t in new[]{before,tinted,after,unbent,changed,alpha})UnityEngine.Object.DestroyImmediate(t);
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
    }
    static float Detail(Texture2D texture)
    {
        float total=0;int count=0;
        for(int y=270;y<480;y++)for(int x=390;x<630;x++)
        {total+=Mathf.Abs(texture.GetPixel(x,y).grayscale-texture.GetPixel(x+1,y).grayscale);count++;}
        return total/count;
    }
    static Texture2D Read(Camera camera)
    {
        var target=new RenderTexture(1024,768,24,RenderTextureFormat.ARGB32);target.Create();
        var previous=RenderTexture.active;var texture=new Texture2D(1024,768,TextureFormat.RGBA32,false);
        try{Canvas.ForceUpdateCanvases();camera.targetTexture=target;camera.Render();RenderTexture.active=target;texture.ReadPixels(new Rect(0,0,1024,768),0,0);texture.Apply();return texture;}
        finally{camera.targetTexture=null;RenderTexture.active=previous;target.Release();UnityEngine.Object.DestroyImmediate(target);}
    }
}
