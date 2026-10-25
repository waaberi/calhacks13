using System;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEditor;
using UnityEngine;

// Edit-time checks only: no Player, XR initialization, socket, native host or capture.
public static class PhysicalScaleChecks
{
    static void Check(bool value, string why) { if (!value) throw new Exception("Physical scale: " + why); }
    static void Near(Vector3 a, Vector3 b, string why)
        => Check(Vector3.Distance(a,b)<.00002f, why + $" expected={b:F6} actual={a:F6}");
    static void Invoke(object target, string name)
        => target.GetType().GetMethod(name, BindingFlags.Instance|BindingFlags.NonPublic).Invoke(target,null);

    static void CheckWorldGeometry(HostScene scene, JArray oracle, float inspectionScale)
    {
        foreach (var expected in oracle)
        {
            var view=scene.ObjectViews.Single(v=>v.name==(string)expected["name"]);
            var mesh=view.GetComponent<MeshFilter>().sharedMesh;
            Check(mesh!=null && mesh.vertexCount>0,"actual decoded mesh exists");
            var actualPoints=mesh.vertices.Select(view.transform.TransformPoint).ToArray();
            // Independent oracle is Blender's evaluated world geometry in metres,
            // not the sender's decomposed transform or the Unity placement scale.
            var expectedPoints=((JArray)expected["world_vertices_metres"]).Select(v=>
                scene.Placement.position+scene.Placement.rotation*
                (new Vector3((float)v[0],(float)v[2],(float)v[1])*inspectionScale)).ToArray();
            var actual=new Bounds(actualPoints[0],Vector3.zero);
            var wanted=new Bounds(expectedPoints[0],Vector3.zero);
            foreach(var point in actualPoints) actual.Encapsulate(point);
            foreach(var point in expectedPoints) wanted.Encapsulate(point);
            Near(actual.size,wanted.size,"rendered world dimensions equal Blender metre dimensions");
            Near(actual.center,wanted.center,"world-space parents/locations convert once");
        }
    }

    public static void Run()
    {
        var fixture=JObject.Parse(File.ReadAllText(Path.Combine(Application.dataPath,"../../tests/fixtures/physical-scale.json")));
        foreach(var item in fixture["cases"])
        {
            var container=new GameObject("Physical-scale checks");
            container.SetActive(false);
            HostScene scene=null;
            try
            {
                scene=container.AddComponent<HostScene>();
                typeof(HostScene).GetField("objectMaterial",BindingFlags.Instance|BindingFlags.NonPublic)
                    .SetValue(scene,AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
                Invoke(scene,"Awake");
                var table=scene.Table;
                Near(scene.Placement.lossyScale,Vector3.one,"new HostScene is physically 1:1");
                var payload=(JObject)item["payload"];
                string unchanged=payload.ToString();
                scene.Handle(HostLink.DecodeScene(payload,true));
                table.SeedFromHead(new Vector3(1,1.65f,-2),Quaternion.Euler(0,37,0)*Vector3.forward);
                table.Place();
                CheckWorldGeometry(scene,(JArray)item["expected"],1f);
                Check(table.IsActualSize && table.ScaleLabel=="Actual size · 1:1","truthful default size label");
                var pose=new Pose(scene.Placement.position,scene.Placement.rotation);
                table.Adjust(0,0,1,0,Vector3.zero,Vector3.forward);
                Check(!table.IsActualSize && table.ScaleLabel.Contains("2×"),"explicit magnification labelled 2x");
                scene.Handle(HostLink.DecodeScene(payload,true));
                Near(scene.Placement.lossyScale,Vector3.one*2,"same-document reconnect preserves chosen magnification");
                CheckWorldGeometry(scene,(JArray)item["expected"],2f);
                // Test the actual compact-menu callback and shared collider routing.
                var arrangement=container.AddComponent<WorkspaceArrangement>();
                Invoke(arrangement,"Awake");
                Invoke(table,"CreatePanel");
                table.UpdateLeftHandMenu(new Pose(new Vector3(-.3f,1.1f,0),Quaternion.identity),new Vector3(0,1.6f,-1),true);
                var button=table.Menu.GetComponentsInChildren<TableAction>(true).Single(a=>a.name=="Actual size");
                Physics.SyncTransforms();
                var ray=new Ray(button.transform.position-button.transform.forward*.3f,button.transform.forward);
                Check(table.HoverController(ray,true),"Actual size invoked through real menu collider");
                Near(scene.Placement.lossyScale,Vector3.one,"Actual size removes all inspection magnification");
                Near(scene.Placement.position,pose.position,"Actual size preserves workspace position");
                Check(Quaternion.Angle(scene.Placement.rotation,pose.rotation)<.001f,"Actual size preserves workspace heading");
                CheckWorldGeometry(scene,(JArray)item["expected"],1f);
                scene.Placement.localScale=Vector3.one*.25f;
                table.RememberDisplayScale();
                Check(!table.IsActualSize && table.ScaleLabel.Contains("0.25×"),"two-hand scale is recorded relative to metres");
                table.ResetView();
                Near(scene.Placement.lossyScale,Vector3.one,"Reset View returns physical size");
                table.Adjust(0,0,1,0,Vector3.zero,Vector3.forward);
                var next=(JObject)payload.DeepClone(); next["document"]["open_epoch"]="3".PadLeft(32,'3');
                scene.Handle(HostLink.DecodeScene(next,true));
                Near(scene.Placement.lossyScale,Vector3.one,"fresh file epoch cannot inherit inspection magnification");
                table.Adjust(0,0,1,0,Vector3.zero,Vector3.forward);
                next["document"]["id"]="4".PadLeft(32,'4');
                scene.Handle(HostLink.DecodeScene(next,true));
                Near(scene.Placement.lossyScale,Vector3.one,"different document starts at physical size");
                Check(payload.ToString()==unchanged,"viewer actions never rewrite native source data");
            }
            finally
            {
                // The harness deliberately never activates HostScene (no socket).
                // Unity need not call OnDestroy for never-active components, so
                // release their separately-created roots/menu/materials explicitly.
                if(scene!=null)
                {
                    if(scene.Table!=null) Invoke(scene.Table,"OnDestroy");
                    Invoke(scene,"OnDestroy");
                }
                UnityEngine.Object.DestroyImmediate(container);
            }
        }
        Debug.Log("PHYSICAL_SCALE_CHECKS PASS real Blender metre/mm/cm exports, 20mm and metre geometry, evaluated modifiers/parent scales, rendered world dimensions, labelled magnification/actual-menu action/reset/reconnect/new document");
    }
}
