using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;

public static class DirectToolGuidesChecks
{
    static void Check(bool ok,string why){if(!ok)throw new Exception("DIRECT_TOOL_GUIDES: "+why);}
    static void Near(Vector3 actual,Vector3 expected,string why)=>Check(Vector3.Distance(actual,expected)<.00001f,why);
    static JObject Mesh()=>JObject.Parse(@"{
      'component':'face','native_tool':'builtin.extrude_region','settings':{},
      'vertices':[{'index':10,'position':[-0.22,0,-0.17]},{'index':20,'position':[0,0,-0.17]},
        {'index':30,'position':[0,0,0.17]},{'index':40,'position':[-0.22,0,0.17]},
        {'index':50,'position':[0.22,0,-0.17]},{'index':60,'position':[0.22,0,0.17]}],
      'edges':[{'index':11,'vertices':[10,40]},{'index':12,'vertices':[20,30]},
        {'index':13,'vertices':[50,60]},{'index':14,'vertices':[10,20]},
        {'index':15,'vertices':[20,50]},{'index':16,'vertices':[40,30]},{'index':17,'vertices':[30,60]}],
      'faces':[{'index':101,'vertices':[10,20,30,40]},{'index':102,'vertices':[20,50,60,30]}]
    }");
    static DirectToolGuides.Frame Frame(string tool,string component,int[] indices)=>new DirectToolGuides.Frame{Tool=tool,Component=component,Indices=indices,Model=Mesh()};
    public static void Run()
    {
        SelectionAndNormals();ExactQuadRing();KnifeRadiusAndReadouts();RealResourcesAndAppearance();
        Debug.Log("DIRECT_TOOL_GUIDES_CHECK PASS native_sparse_indices/face_normals/native_mirror/reflected_nonuniform_map/exact_quad_ring/no_fake_nonquad/knife_samples/actual_snap/native_radius/ACK_only/read_only/bounded_pool/dispose/production_render; physical acceptance pending");
    }
    static void SelectionAndNormals()
    {
        var frame=Frame("mesh.selection","vertex",new[]{40,10,999,40});string original=frame.Model.ToString(Formatting.None);
        var result=DirectToolGuides.Build(frame);Check(result.Valid&&result.Points.Count==2,"only actual captured native vertex IDs become selectable points");
        Check(result.Points[0].NativeIndex==40&&result.Points[1].NativeIndex==10,"sparse native IDs retain identity/order rather than array positions");
        frame.Component="edge";frame.Indices=new[]{12};result=DirectToolGuides.Build(frame);
        Check(result.Segments.Count==1&&result.Points.Count==2,"edge outline and endpoints use actual native edge");
        frame.HoverIndex=102;frame.HoverComponent="face";result=DirectToolGuides.Build(frame);Check(result.Segments.Count(s=>s.Kind=="hovered native face")==4,"only actual visibility-fenced native hover face ID outlines its four real edges");frame.HoverIndex=-1;
        frame.Component="face";frame.Indices=new[]{101};frame.Tool="mesh.extrude";frame.ExtrudeNormalConstrained=true;
        frame.Map=Matrix4x4.TRS(new Vector3(1,2,-3),Quaternion.Euler(23,-41,16),new Vector3(-2,.4f,3));
        result=DirectToolGuides.Build(frame);var arrow=result.Segments.First(s=>s.Kind=="native face normal");
        Near((arrow.B-arrow.A).normalized,frame.Map.MultiplyVector(Vector3.back).normalized,"native face displacement normal maps once through reflected/nonuniform presentation");
        Near(arrow.A,frame.Map.MultiplyPoint3x4(new Vector3(-.11f,0,0)),"normal is anchored to selected actual face centre");
        frame.NativeObjectMirrored=true;var mirrored=DirectToolGuides.Build(frame).Segments.First(s=>s.Kind=="native face normal");
        Near((mirrored.B-mirrored.A).normalized,-(arrow.B-arrow.A).normalized,"native object mirror parity corrects world winding before display map");
        Check(frame.Model.ToString(Formatting.None)==original,"guides never change tool/indices/settings/topology JSON");
        frame.Map[0,3]=float.NaN;Check(!DirectToolGuides.Build(frame).Valid,"nonfinite map translation fails closed");
    }
    static void ExactQuadRing()
    {
        var frame=Frame("mesh.loop_cut","edge",new[]{11});frame.Acknowledged=new JObject{["cuts"]=1,["slide"]=.5};
        var result=DirectToolGuides.Build(frame);var ring=result.Segments.Where(s=>s.Kind=="quad ring preview").ToArray();
        Check(ring.Length==2&&result.Limitation=="","one seed traverses exactly two visible opposite-quad links");
        foreach(var segment in ring){Check(Mathf.Abs(segment.A.y-.085f)<.00001f&&Mathf.Abs(segment.B.y-.085f)<.00001f,"slide applies backend oriented t += slide*(1-t) on each rail");Check(Mathf.Abs(segment.A.z)<.00001f&&Mathf.Abs(segment.B.z)<.00001f,"quad cut stays on actual native face plane");}
        frame.Acknowledged=new JObject{["cuts"]=2,["slide"]=-.5};result=DirectToolGuides.Build(frame);ring=result.Segments.Where(s=>s.Kind=="quad ring preview").ToArray();Check(ring.Length==4,"multiple cuts use every exact quad link");
        var ys=ring.SelectMany(s=>new[]{s.A.y,s.B.y}).Distinct().OrderBy(v=>v).ToArray();Check(ys.Length==2&&Mathf.Abs(ys[0]-(-.11333333f))<.00001f&&Mathf.Abs(ys[1]-(-.05666666f))<.00001f,"negative slide matches native t += slide*t");
        frame.Indices=new[]{11,12};Check(DirectToolGuides.Build(frame).Limitation.Length>0,"multiple seed edges are not presented as executable loop cut");
        frame.Indices=new[]{11};frame.Model["faces"]=new JArray(new JObject{["index"]=101,["vertices"]=new JArray(10,20,40)});
        result=DirectToolGuides.Build(frame);Check(result.Limitation.Length>0&&!result.Segments.Any(s=>s.Kind=="quad ring preview"),"nonquad seed is labelled unsupported without invented ring");
    }
    static void KnifeRadiusAndReadouts()
    {
        var frame=Frame("mesh.knife","face",new[]{101});frame.Held=true;frame.KnifePath=new[]{new Vector3(-.1f,0,0),new Vector3(0,.07f,0),new Vector3(.13f,-.02f,0)};
        frame.Map=Matrix4x4.TRS(Vector3.one,Quaternion.Euler(12,23,34),new Vector3(-2,.5f,3));frame.SnapPoint=new Vector3(7,8,9);
        var result=DirectToolGuides.Build(frame);var path=result.Segments.Where(s=>s.Kind=="sampled knife path").ToArray();Check(path.Length==2,"knife guide uses only actual sampled held path");Near(path[0].A,frame.Map.MultiplyPoint3x4(frame.KnifePath[0]),"knife sample mapping once");Near(result.Points.First(p=>p.Kind=="actual snap target").Position,frame.SnapPoint.Value,"actual snap target stays in supplied display frame");
        Check(result.Label.Contains("Waiting for Blender")&&!result.Label.Contains("Blender accepted"),"pre-ACK gesture never claims native application");
        frame.KnifePath=new Vector3[129];Check(!DirectToolGuides.Build(frame).Valid,"oversize Knife gesture is not silently displayed as a valid prefix");frame.KnifePath=new[]{Vector3.zero,Vector3.right*.1f};
        frame.Tool="mesh.bevel";frame.Acknowledged=new JObject{["width_m"]=.003,["segments"]=4};result=DirectToolGuides.Build(frame);Check(result.Label.Contains("width 3 mm")&&result.Label.Contains("4 segments")&&result.Label.Contains("Blender accepted"),"only actual ACK supplies metric width/segment readout");
        frame.Tool="mesh.rotate";frame.Acknowledged=new JObject{["rotation"]=new JArray(Math.Sqrt(.5),0,0,Math.Sqrt(.5))};Check(DirectToolGuides.Build(frame).Label.Contains("shortest rotation 90°"),"ACK quaternion shortest rotation is labelled honestly without claiming signed/full angular travel");
        frame.Radius=.12f;frame.Acknowledged=null;result=DirectToolGuides.Build(frame);var radius=result.Segments.Where(s=>s.Kind=="native proportional radius").ToArray();Check(radius.Length==144,"three mapped native-radius circles");
        foreach(var line in radius){Near(frame.Map.inverse.MultiplyPoint3x4(line.A).normalized*.12f,frame.Map.inverse.MultiplyPoint3x4(line.A),"nonuniform display ellipsoid inverts to exact native radius");}
        ((JObject)frame.Model["settings"])["projected"]=true;result=DirectToolGuides.Build(frame);Check(!result.Segments.Any(s=>s.Kind=="native proportional radius")&&result.Label.Contains("native Blender view footprint"),"unknown native projected view is labelled, never fabricated as headset sphere");
        foreach(string tool in new[]{"mesh.merge","mesh.dissolve","mesh.delete"})
        {frame=Frame(tool,"vertex",new[]{10,20});((JObject)frame.Model["settings"])["variant"]="CENTER";result=DirectToolGuides.Build(frame);Check(result.Label.Contains("2 vertex selected")&&result.Label.Contains("CENTER")&&result.Segments.Count==0,"discrete intent labels exact count/variant and draws no fake continuous geometry");}
        frame=Frame("mesh.merge","vertex",new[]{40,10,20});frame.Model["selection"]=new JObject{["order_complete"]=true};((JObject)frame.Model["settings"])["variant"]="FIRST";
        result=DirectToolGuides.Build(frame);Near(result.Points.First(p=>p.Kind=="merge FIRST destination").Position,new Vector3(-.22f,.17f,0),"Merge FIRST uses captured native index order");
        ((JObject)frame.Model["settings"])["variant"]="LAST";result=DirectToolGuides.Build(frame);Near(result.Points.First(p=>p.Kind=="merge LAST destination").Position,new Vector3(0,-.17f,0),"Merge LAST uses final captured native pick, not array index");
        frame.Model["selection"]["order_complete"]=false;result=DirectToolGuides.Build(frame);Check(result.Limitation.Length>0&&!result.Points.Any(p=>p.Kind.StartsWith("merge ",StringComparison.Ordinal)),"incomplete native order never invents First/Last destination");
        ((JObject)frame.Model["settings"])["variant"]="CURSOR";result=DirectToolGuides.Build(frame);Check(!result.Points.Any(p=>p.Kind.StartsWith("merge ",StringComparison.Ordinal)),"unexported cursor never creates a fake destination");
    }
    static void RealResourcesAndAppearance()
    {
        var cameraObject=new GameObject("synthetic direct guides camera");var camera=cameraObject.AddComponent<Camera>();camera.enabled=false;camera.stereoTargetEye=StereoTargetEyeMask.None;camera.transform.position=new Vector3(0,0,-1.3f);camera.transform.LookAt(Vector3.zero);camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.035f,.045f,.065f);camera.fieldOfView=50;camera.cullingMask=1<<30;
        int materialCount=Resources.FindObjectsOfTypeAll<Material>().Count(m=>m.name.StartsWith("Native guide ",StringComparison.Ordinal));
        var guides=new DirectToolGuides();
        try
        {
            var frame=Frame("mesh.extrude","face",new[]{101});guides.Draw(frame,camera);var root=GameObject.Find("Native Blender contextual guides");Check(root!=null&&guides.Visible,"actual production root is visible");
            foreach(var line in root.GetComponentsInChildren<LineRenderer>(true)){Check(line.sharedMaterial.color.a>.99f,"actual shader material carries visible opaque guide colour");Check(line.startWidth>=.0025f&&line.startWidth<=.007f,"bounded world linewidth");}
            int initial=root.GetComponentsInChildren<LineRenderer>(true).Length;for(int i=0;i<5;i++)guides.Draw(frame,camera);Check(root.GetComponentsInChildren<LineRenderer>(true).Length==initial,"redraw reuses bounded line/dot pools");
            Check(root.GetComponentsInChildren<Collider>(true).Length==0,"read-only guides never intercept accepted controller routing");
            guides.Hide();Check(!root.activeSelf&&!guides.Visible,"mode/cancel caller can hide entire guide immediately");
            string output=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");if(!string.IsNullOrWhiteSpace(output))RenderSheet(guides,camera,output);
        }
        finally{guides.Dispose();UnityEngine.Object.DestroyImmediate(cameraObject);}
        Check(Resources.FindObjectsOfTypeAll<Material>().Count(m=>m.name.StartsWith("Native guide ",StringComparison.Ordinal))==materialCount,"dispose releases every owned guide material");
        Check(GameObject.Find("Native Blender contextual guides")==null,"dispose releases actual guide hierarchy");
    }
    static void RenderSheet(DirectToolGuides guides,Camera camera,string directory)
    {
        const int width=960,height=720;var sheet=new Texture2D(width*3,height*2,TextureFormat.RGB24,false);var pixels=new Texture2D(width,height,TextureFormat.RGB24,false);var target=new RenderTexture(width,height,24){antiAliasing=4};var previous=RenderTexture.active;
        string[] tools={"mesh.extrude","mesh.inset","mesh.bevel","mesh.loop_cut","mesh.knife","mesh.scale"};
        try
        {
            target.Create();camera.targetTexture=target;
            for(int tile=0;tile<tools.Length;tile++)
            {
                bool edge=tile==2||tile==3;var frame=Frame(tools[tile],edge?"edge":"face",new[]{edge?(tile==3?11:12):101});frame.Held=true;frame.ExtrudeNormalConstrained=true;
                if(tile==0)frame.Acknowledged=new JObject{["translation_m"]=new JArray(0,-.02,0)};
                if(tile==1)frame.Acknowledged=new JObject{["thickness_m"]=.012};if(tile==2)frame.Acknowledged=new JObject{["width_m"]=.006,["segments"]=3};if(tile==3)frame.Acknowledged=new JObject{["cuts"]=2,["slide"]=.2};
                if(tile==4){frame.KnifePath=new[]{new Vector3(-.18f,-.12f,0),new Vector3(-.04f,.09f,0),new Vector3(.17f,-.05f,0)};frame.Acknowledged=new JObject{["path_m"]=new JArray(new JArray(0,0,0),new JArray(.1,0,.1))};}
                if(tile==5){frame.Radius=.24f;frame.Map=Matrix4x4.Scale(new Vector3(1.2f,.7f,1));frame.SnapPoint=new Vector3(.17f,-.08f,0);frame.Acknowledged=new JObject{["scale"]=new JArray(1.25,1,1)};}
                guides.Draw(frame,camera);var root=GameObject.Find("Native Blender contextual guides");foreach(var child in root.GetComponentsInChildren<Transform>(true))child.gameObject.layer=30;
                Canvas.ForceUpdateCanvases();camera.Render();RenderTexture.active=target;pixels.ReadPixels(new Rect(0,0,width,height),0,0);pixels.Apply();sheet.SetPixels(tile%3*width,(1-tile/3)*height,width,height,pixels.GetPixels());
                int bright=pixels.GetPixels32().Count(p=>p.r>170||p.g>170||p.b>170);Check(bright>150,"production camera capture contains visible guide lines and labels for "+tools[tile]);
            }
            sheet.Apply();Directory.CreateDirectory(directory);File.WriteAllBytes(Path.Combine(directory,"direct-tool-guides.png"),sheet.EncodeToPNG());
        }
        finally{camera.targetTexture=null;RenderTexture.active=previous;target.Release();UnityEngine.Object.DestroyImmediate(target);UnityEngine.Object.DestroyImmediate(pixels);UnityEngine.Object.DestroyImmediate(sheet);}
    }
}
