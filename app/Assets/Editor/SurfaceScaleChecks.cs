using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using SpatialModeling;
using UnityEngine;

public static class SurfaceScaleChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool ok,string reason){if(!ok)throw new Exception("SURFACE_SCALE: "+reason);}
    static void Near(Vector3 actual,Vector3 expected,string reason)=>Check(Vector3.Distance(actual,expected)<.00003f,reason);
    static WorkspaceSurfaces.Surface Desk(Vector3 point,Vector3 normal)=>new WorkspaceSurfaces.Surface{
        Name="Desk",Id=Guid.NewGuid(),Pose=new Pose(point,Quaternion.LookRotation(normal,Mathf.Abs(normal.z)<.9f?Vector3.forward:Vector3.up)),Size=new Vector2(4,4)};
    static Vector3[] Box(Vector3 center,Vector3 size)=>Enumerable.Range(0,8).Select(i=>center+Vector3.Scale(size*.5f,new Vector3((i&1)==0?-1:1,(i&2)==0?-1:1,(i&4)==0?-1:1))).ToArray();
    public static void SetBox(WorkspaceObjectView view,Vector3 center,Vector3 size)
    {
        var mesh=view.GetComponent<MeshFilter>().sharedMesh;mesh.Clear();mesh.vertices=Box(center,size);
        mesh.triangles=new[]{0,3,1,0,2,3,4,5,7,4,7,6,0,1,5,0,5,4,2,6,7,2,7,3,0,4,6,0,6,2,1,3,7,1,7,5};mesh.RecalculateBounds();
        var collider=view.GetComponent<MeshCollider>();if(collider!=null){collider.sharedMesh=null;collider.sharedMesh=mesh;}
    }
    public static void Run()
    {
        Admission();AffineNativePivot();ArrangementScaling();
        Debug.Log("SURFACE_SCALE_CHECK PASS actual_support_finite_plane/no_nearest_snap/frozen_native_pivot/reflected_nonuniform/axis_scale/arrangement_shrink_enlarge/free_bypass; physical acceptance pending");
    }
    static void Admission()
    {
        var points=Box(new Vector3(0,.153f,0),new Vector3(.2f,.3f,.2f));var desk=Desk(Vector3.zero,Vector3.up);
        Check(WorkspaceArrangement.TryScaleContact(points,new[]{desk},out var chosen,out var contact)&&chosen.Id==desk.Id,"actual bottom resting on current finite desk is admitted");
        Near(contact,new Vector3(0,.003f,0),"existing3mm clearance is preserved without pulling geometry to the plane");
        Check(!WorkspaceArrangement.TryScaleContact(points.Select(p=>p+Vector3.up*.02f).ToArray(),new[]{desk},out _,out _),"floating object is not attached to a merely nearby desk");
        Check(!WorkspaceArrangement.TryScaleContact(points.Select(p=>p+Vector3.right*5).ToArray(),new[]{desk},out _,out _),"infinite extension outside detected finite desk never creates contact");
        var small=desk;small.Size=Vector2.one*.05f;
        Check(!WorkspaceArrangement.TryScaleContact(points,new[]{small},out _,out _),"an in-desk centroid cannot invent support when every actual supporting vertex lies outside the finite footprint");
        var mutable=desk;mutable.Boundary=new[]{new Vector2(-2,-2),new Vector2(2,-2),new Vector2(2,2),new Vector2(-2,2)};
        var frozen=WorkspaceArrangement.FreezeScaleSurface(mutable);
        Check(WorkspaceArrangement.SameScaleSurface(frozen,mutable),"unchanged native boundary retains frozen contact");
        mutable.Boundary[0]+=Vector2.right*.02f;
        Check(!WorkspaceArrangement.SameScaleSurface(frozen,mutable),"in-place boundary-only updates cannot mutate or match a frozen support snapshot");
        var wall=Desk(Vector3.zero,Vector3.right);wall.Name="Wall";
        Check(!WorkspaceArrangement.TryScaleContact(Box(new Vector3(.1f,.15f,0),new Vector3(.2f,.3f,.2f)),new[]{desk,wall},out _,out _),"two intersecting equally valid support planes do not invent attachment ownership");
    }
    static void AffineNativePivot()
    {
        foreach(var scale in new[]{Vector3.one,new Vector3(-2,.4f,1.7f)})
        {
            var map=Matrix4x4.TRS(new Vector3(2,.8f,-1),Quaternion.Euler(17,48,-12),scale);
            var normal=map.inverse.transpose.MultiplyVector(Vector3.up).normalized;
            var plane=Desk(map.MultiplyPoint3x4(Vector3.zero),normal);
            var native=Box(new Vector3(0,.15f,0),new Vector3(.2f,.3f,.2f));
            var display=native.Select(p=>map.MultiplyPoint3x4(p)).ToArray();
            Check(WorkspaceArrangement.TryScaleContact(display,new[]{plane},out _,out var contact),"affine/reflected presented object retains real support");
            Vector3 pivot=map.inverse.MultiplyPoint3x4(contact);Near(pivot,Vector3.zero,"display contact becomes exact native world pivot through inverse map once");
            foreach(float factor in new[]{2f,.5f})
            {
                var transformed=native.Select(p=>pivot+Vector3.Scale(p-pivot,new Vector3(1,factor,1))).Select(p=>map.MultiplyPoint3x4(p)).ToArray();
                Near(map.MultiplyPoint3x4(pivot),contact,"axis-scale keeps contact point fixed for enlargement and reduction");
                Check(Mathf.Abs(transformed.Min(p=>Vector3.Dot(p-plane.Pose.position,normal)))<.00003f,"actual scaled bottom remains on its mapped desk plane");
            }
        }
    }
    static void ArrangementScaling()
    {
        var existing=new HashSet<GameObject>(Resources.FindObjectsOfTypeAll<GameObject>());Mesh mesh=null;
        var owner=new GameObject("inactive support-scale fixture");owner.SetActive(false);
        try
        {
            var arrangement=owner.AddComponent<WorkspaceArrangement>();typeof(WorkspaceArrangement).GetMethod("Awake",Private).Invoke(arrangement,null);
            var surfaces=(List<WorkspaceSurfaces.Surface>)typeof(WorkspaceSurfaces).GetField("surfaces",Private).GetValue(arrangement.Surfaces);surfaces.Add(Desk(Vector3.zero,Vector3.up));
            var target=new GameObject("resting arrangement model",typeof(MeshFilter));target.transform.SetParent(owner.transform,false);
            mesh=new Mesh();mesh.vertices=Box(Vector3.zero,Vector3.one);mesh.RecalculateBounds();target.GetComponent<MeshFilter>().sharedMesh=mesh;
            target.transform.position=new Vector3(0,.503f,0);var prior=new Pose(target.transform.position,target.transform.rotation);
            target.transform.localScale=Vector3.one*2;
            var enlarged=arrangement.Apply(target.transform,prior,prior,false,false,Vector3.one);target.transform.SetPositionAndRotation(enlarged.position,enlarged.rotation);
            Near(target.transform.TransformPoint(Vector3.down*.5f),new Vector3(0,.003f,0),"two-hand enlargement grows away from its established support");
            prior=enlarged;target.transform.localScale=Vector3.one*.5f;
            var reduced=arrangement.Apply(target.transform,prior,prior,false,false,Vector3.one*2);target.transform.SetPositionAndRotation(reduced.position,reduced.rotation);
            Near(target.transform.TransformPoint(Vector3.down*.5f),new Vector3(0,.003f,0),"two-hand reduction keeps the same support point instead of floating upward");
            prior=reduced;target.transform.localScale=Vector3.one*.25f;
            var free=arrangement.Apply(target.transform,prior,prior,false,true,Vector3.one*.5f);
            Near(free.position,prior.position,"existing explicit free-placement bypass releases contact scaling");
            owner.transform.localScale=new Vector3(2,1,.6f);target.transform.localRotation=Quaternion.Euler(0,37,0);
            Check(!WorkspaceArrangement.ScalePoseRepresentable(target.transform),"a rotated child under a nonuniform parent has shear that Pose/lossyScale cannot represent");
            prior=new Pose(target.transform.position,target.transform.rotation);var oldScale=target.transform.lossyScale;target.transform.localScale*=.8f;
            arrangement.Apply(target.transform,prior,prior,false,false,oldScale);
            var contacts=(System.Collections.IDictionary)typeof(WorkspaceArrangement).GetField("scaleSupports",Private).GetValue(arrangement);
            Check(contacts.Count==0,"arrangement scale conservatively skips fixed-contact anchoring when parent shear would corrupt its affine frame");
        }
        finally
        {
            foreach(var go in Resources.FindObjectsOfTypeAll<GameObject>().Where(go=>!existing.Contains(go)).ToArray())if(go!=null)UnityEngine.Object.DestroyImmediate(go);
            if(mesh!=null)UnityEngine.Object.DestroyImmediate(mesh);
        }
    }
}
