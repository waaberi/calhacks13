using System;
using SpatialModeling;
using UnityEngine;

public static class RoomSetupChecks
{
    static void Check(bool value,string message) {if(!value) throw new Exception("Room setup: "+message);}
    public static void Run()
    {
        RoomLocalizationChecks.Run();
        RoomSpaceReplayChecks.Run();
        // SDK tracking space can differ from the camera's parent after recenter.
        // A room point two metres forward in that space must appear two metres
        // right in a world whose tracking reference has a 90-degree yaw.
        var frame=new Pose(new Vector3(3,1,-5),Quaternion.Euler(0,90,0));
        var roomPose=WorkspaceSurfaces.SceneToWorld(frame,new Pose(new Vector3(0,0,2),Quaternion.identity));
        Check(Vector3.Distance(roomPose.position,new Vector3(5,1,-5))<.0001f,"room uses SDK tracking translation/yaw once");
        Check(Vector3.Distance(roomPose.rotation*Vector3.forward,Vector3.right)<.0001f,"room heading follows SDK frame once");
        var cameraPose=WorkspaceSurfaces.SceneToWorld(frame,new Pose(new Vector3(1,1,0),Quaternion.Euler(0,180,0)));
        Check(Vector3.Distance(cameraPose.position,new Vector3(3,2,-6))<.0001f,"head and room share the SDK frame");
        // An L-shaped floor must not fill the missing corner with a rectangular grid
        // or apply contact to an area that the actual polygon excludes.
        var floor=new WorkspaceSurfaces.Surface {Name="Floor",Pose=Pose.identity,Size=new Vector2(4,4),
            Boundary=new[]{new Vector2(-2,-2),new Vector2(2,-2),new Vector2(2,0),Vector2.zero,new Vector2(0,2),new Vector2(-2,2)}};
        Check(WorkspaceSurfaces.ContainsPoint(floor,new Vector2(-1,1)),"real floor interior");
        Check(!WorkspaceSurfaces.ContainsPoint(floor,Vector2.one),"concave notch must remain empty");
        var edge=WorkspaceSurfaces.ClosestOnBoundary(floor,Vector2.one);
        Check((edge-new Vector2(1,0)).sqrMagnitude<1e-6f || (edge-new Vector2(0,1)).sqrMagnitude<1e-6f,"attachment uses actual edge");
        var rotated=floor;rotated.Pose=new Pose(new Vector3(3,1,-5),Quaternion.Euler(90,43,0));
        // Use an unambiguous closest edge; (1,1) is equidistant from both notch edges.
        var query=rotated.Pose.position+rotated.Pose.rotation*new Vector3(1.2f,.6f,1);
        var closest=WorkspaceSurfaces.ClosestPoint(rotated,query);
        Check(Vector3.Distance(closest,rotated.Pose.position+rotated.Pose.rotation*new Vector3(1.2f,0,0))<.0001f,"polygon and origin transformed exactly once");
        var points=new[]{new Vector3(1,2,3),new Vector3(2,3,4),new Vector3(3,4,5)};
        var mesh=WorkspaceSurfaces.MakeScanMesh(points,new[]{2,0,1});
        try
        {
            Check(mesh.vertexCount==3 && mesh.vertices[0]==points[2] && mesh.vertices[1]==points[0],"renderer retains SDK vertices and winding");
            Check(mesh.uv2[0]==new Vector2(1,0) && mesh.uv2[2]==Vector2.zero,"actual mesh wire coordinates");
        }
        finally { UnityEngine.Object.DestroyImmediate(mesh); }
        bool refused=false;try {WorkspaceSurfaces.MakeScanMesh(points,new[]{0,1,9});} catch(ArgumentException) {refused=true;}
        Check(refused,"invalid geometry cannot enter rendering");
        var go=new GameObject("Room setup workflow checks");
        try
        {
            var setup=go.AddComponent<WorkspaceRoomSetup>();setup.Open();
            Check(setup.IsOpen && !setup.ShowingHandoff,"saved-room path is primary");
            setup.Scan();Check(setup.ShowingHandoff && setup.Heading.Contains("Leave Link"),"PC cannot pretend to launch capture");
            setup.Close();Check(!setup.IsOpen,"return to accepted arrangement");
        }
        finally {UnityEngine.Object.DestroyImmediate(go);}
        Debug.Log("ROOM_SETUP_CHECKS PASS polygon_concavity origin mesh_identity invalid_geometry supported_platform_handoff physical_fit=UNVERIFIED");
    }
}
