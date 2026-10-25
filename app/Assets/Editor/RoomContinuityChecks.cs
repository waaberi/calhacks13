using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using SpatialModeling;
using UnityEngine;

public static class RoomContinuityChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static Action<object> stageAction;
    static void Stage<T>(T stage)=>stageAction(stage);
    static object Get(object value,string name)=>value.GetType().GetField(name,Private|BindingFlags.Public).GetValue(value);
    static void Set(object value,string name,object field)=>value.GetType().GetField(name,Private|BindingFlags.Public).SetValue(value,field);
    static void Check(bool ok,string why){if(!ok)throw new Exception("ROOM_CONTINUITY: "+why);}
    public static void Run()
    {
        CurrentContainment();CheckpointStorage();TransactionalStaging();
        Debug.Log("ROOM_CONTINUITY_CHECK PASS exact_verified_floor/current_containment/cold_start_upgrade/overlap_no_guess/stale_removed_identity/strict_checkpoint/atomic_storage/staged_failure/newer_geometry_owner; physical_fit=UNVERIFIED");
    }
    static WorkspaceRoomLocalization.FloorCandidate Floor(Guid room,Guid anchor)=>new WorkspaceRoomLocalization.FloorCandidate{
        Room=room,Anchor=anchor,Tracked=true,SampleTime=10,WorldPose=new Pose(Vector3.zero,Quaternion.Euler(90,0,0)),
        Boundary=new[]{new Vector2(-2,-2),new Vector2(2,-2),new Vector2(2,2),new Vector2(-2,2)}};
    static void CurrentContainment()
    {
        var a=Guid.NewGuid();var b=Guid.NewGuid();var fa=Guid.NewGuid();var fb=Guid.NewGuid();var first=Floor(a,fa);var second=Floor(b,fb);
        var head=new Pose(Vector3.up,Quaternion.identity);
        Check(!WorkspaceRoomLocalization.TrySelectRoom(new[]{first,second},head,true,10,out _,out _),"unverified overlap remains refused");
        Check(WorkspaceRoomLocalization.TrySelectRoomWithContinuity(new[]{second,first},head,true,10,a,fa,out var room,out _)&&room==a,"cold restart/build upgrade retains exact verified identity only after fresh containment");
        Check(!WorkspaceRoomLocalization.TrySelectRoomWithContinuity(new[]{second,first},head,true,10,a,Guid.NewGuid(),out _,out _),"different floor UUID cannot inherit an old verified room identity");
        Check(!WorkspaceRoomLocalization.TrySelectRoomWithContinuity(new[]{first,second},head,false,10,a,fa,out _,out _),"checkpoint cannot bypass headset readiness");
        Check(!WorkspaceRoomLocalization.TrySelectRoomWithContinuity(new[]{first,second},head,true,11,a,fa,out _,out _),"checkpoint cannot revive stale floor poses");
        first.Tracked=false;
        Check(WorkspaceRoomLocalization.TrySelectRoomWithContinuity(new[]{first,second},head,true,10,a,fa,out room,out _)&&room==b,"untracked prior floor cannot override a uniquely valid different room");
        first=Floor(a,fa);first.WorldPose.position=Vector3.right*20;
        Check(WorkspaceRoomLocalization.TrySelectRoomWithContinuity(new[]{first,second},head,true,10,a,fa,out room,out _)&&room==b,"moved prior floor must pass current actual boundary");
        Check(WorkspaceRoomLocalization.TrySelectRoomWithContinuity(new[]{second},head,true,10,a,fa,out room,out _)&&room==b,"removed prior identity is never synthesized from persisted metadata");
    }
    static WorkspaceSurfaces.VerifiedRoomCheckpoint Checkpoint(Guid room,Guid floor)=>new WorkspaceSurfaces.VerifiedRoomCheckpoint{
        room=room.ToString(),floor=floor.ToString(),verification="fresh_tracked_floor_contains_head",verified_at_utc="2026-10-25T05:29:57Z",anchors=new List<string>{floor.ToString(),Guid.NewGuid().ToString()}};
    static void CheckpointStorage()
    {
        string directory=Path.Combine(Path.GetTempPath(),"calhacks-room-checkpoint-test-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);
        try
        {
            string path=Path.Combine(directory,"verified.json");var original=Checkpoint(Guid.NewGuid(),Guid.NewGuid());
            Check(WorkspaceSurfaces.PersistVerifiedRoomFile(path,original),"complete verified metadata writes atomically in an isolated test directory");
            var roundtrip=WorkspaceSurfaces.ReadVerifiedRoomFile(path);Check(roundtrip!=null&&roundtrip.room==original.room,"verified identity survives restart/version-compatible deserialization");
            var malformed=JsonUtility.FromJson<WorkspaceSurfaces.VerifiedRoomCheckpoint>(JsonUtility.ToJson(original));malformed.anchors.Add("invalid");
            string before=File.ReadAllText(path);Check(!WorkspaceSurfaces.PersistVerifiedRoomFile(path,malformed)&&File.ReadAllText(path)==before,"partial malformed seed is refused whole without overwriting a proven checkpoint");
            malformed=Checkpoint(Guid.NewGuid(),Guid.NewGuid());malformed.anchors.RemoveAt(0);Check(WorkspaceSurfaces.ValidateVerifiedRoom(malformed)==null,"missing proven floor fails closed");
            var replacement=Checkpoint(Guid.NewGuid(),Guid.NewGuid());
            Check(WorkspaceSurfaces.PersistVerifiedRoomFile(path,replacement)&&WorkspaceSurfaces.ReadVerifiedRoomFile(path+".previous").room==original.room,"replacing verified identity retains the prior durable checkpoint");
            File.WriteAllText(path,"{incomplete");Check(WorkspaceSurfaces.ReadVerifiedRoomFile(path)==null&&WorkspaceSurfaces.ReadVerifiedRoomFile(path+".previous")!=null,"incomplete read does not erase the durable previous checkpoint");
            string blocked=Path.Combine(directory,"directory-target");Directory.CreateDirectory(blocked);
            Check(!WorkspaceSurfaces.PersistVerifiedRoomFile(blocked,replacement)&&Directory.Exists(blocked),"failed atomic write does not claim durable success");
            var refs=new WorkspaceSurfaces.RoomRecoveryIndex();refs.anchors.Add(new WorkspaceSurfaces.RoomRecoveryReference{id=original.floor,room=original.room,kind="Floor"});
            var incoming=new WorkspaceSurfaces.RoomRecoveryIndex();incoming.anchors.Add(new WorkspaceSurfaces.RoomRecoveryReference{id=replacement.floor,room=replacement.room,kind="Floor"});
            Check(WorkspaceSurfaces.MergeRoomRecovery(refs,incoming).anchors.Count==2,"discovery of a different room never truncates prior UUID recovery data");
            string serialized=JsonUtility.ToJson(original);Check(!serialized.Contains("position")&&!serialized.Contains("rotation")&&!serialized.Contains("boundary"),"verified checkpoint persists identities/evidence metadata only");
        }
        finally
        {
            string root=Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
            Check(Path.GetFullPath(directory).StartsWith(root,StringComparison.OrdinalIgnoreCase),"temporary cleanup remains within the explicit test directory");Directory.Delete(directory,true);
        }
    }
    static void TransactionalStaging()
    {
        var owner=new GameObject("inactive room stage fixture");owner.SetActive(false);var provider=owner.AddComponent<WorkspaceSurfaces>();
        var anchors=(IList)Get(provider,"anchors");var anchorType=anchors.GetType().GetGenericArguments()[0];anchors.Add(Activator.CreateInstance(anchorType));
        var boundaries=(Dictionary<Guid,Vector2[]>)Get(provider,"scanBoundaries");var floor=Guid.NewGuid();var boundary=new[]{Vector2.zero,Vector2.right,Vector2.up};boundaries[floor]=boundary;
        var surfaces=(List<WorkspaceSurfaces.Surface>)Get(provider,"surfaces");surfaces.Add(new WorkspaceSurfaces.Surface{Id=floor,Name="Desk",Boundary=boundary});
        var meshes=(IList)Get(provider,"scanMeshes");var meshType=meshes.GetType().GetGenericArguments()[0];
        var stagedType=typeof(WorkspaceSurfaces).GetNestedType("RoomGeometryStage",BindingFlags.NonPublic);
        var callback=typeof(RoomContinuityChecks).GetMethod("Stage",BindingFlags.Static|BindingFlags.NonPublic).MakeGenericMethod(stagedType).CreateDelegate(typeof(Action<>).MakeGenericType(stagedType));
        var empty=Activator.CreateInstance(anchors.GetType());var commit=typeof(WorkspaceSurfaces).GetMethod("CommitRoomAnchorSet",Private);
        var oldRoot=new GameObject("prior room mesh",typeof(MeshRenderer));var oldMaterial=new Material(Shader.Find("UI/Default"));oldRoot.GetComponent<MeshRenderer>().sharedMaterial=oldMaterial;
        var priorMesh=Activator.CreateInstance(meshType,true);Set(priorMesh,"Root",oldRoot);Set(priorMesh,"Mesh",new Mesh());meshes.Add(priorMesh);Set(provider,"scanMaterial",oldMaterial);
        GameObject stagedRoot=null,newOwnerRoot=null;Material stagedMaterial=null,newOwnerMaterial=null;Mesh stagedMesh=null,newOwnerMesh=null;
        try
        {
            stageAction=stage=>{stagedRoot=new GameObject("failed staged mesh",typeof(MeshRenderer));stagedMaterial=new Material(Shader.Find("UI/Default"));stagedMesh=new Mesh();var row=Activator.CreateInstance(meshType,true);Set(row,"Root",stagedRoot);Set(row,"Mesh",stagedMesh);((IList)Get(stage,"Meshes")).Add(row);Set(stage,"Material",stagedMaterial);throw new IOException("isolated staging failure");};
            Check(!(bool)commit.Invoke(provider,new object[]{empty,new List<OVRAnchor>(),0,callback}),"actual loader rolls back incomplete geometry stage");
            Check(anchors.Count==1&&surfaces.Count==1&&ReferenceEquals(boundaries[floor],boundary)&&oldRoot!=null&&oldMaterial!=null&&meshes.Count==1,"failed stage retains current anchors/planes/boundaries/mesh/material");
            Check(stagedRoot==null&&stagedMaterial==null,"failed transaction releases only its own temporary geometry");
            stageAction=stage=>{
                stagedRoot=new GameObject("superseded stage",typeof(MeshRenderer));stagedMaterial=new Material(Shader.Find("UI/Default"));stagedMesh=new Mesh();var row=Activator.CreateInstance(meshType,true);Set(row,"Root",stagedRoot);Set(row,"Mesh",stagedMesh);((IList)Get(stage,"Meshes")).Add(row);Set(stage,"Material",stagedMaterial);
                Set(provider,"generation",1);anchors.Clear();meshes.Clear();
                newOwnerRoot=new GameObject("new generation room mesh",typeof(MeshRenderer));newOwnerMaterial=new Material(Shader.Find("UI/Default"));newOwnerRoot.GetComponent<MeshRenderer>().sharedMaterial=newOwnerMaterial;newOwnerMesh=new Mesh();var current=Activator.CreateInstance(meshType,true);Set(current,"Root",newOwnerRoot);Set(current,"Mesh",newOwnerMesh);meshes.Add(current);Set(provider,"scanMaterial",newOwnerMaterial);
            };
            Check(!(bool)commit.Invoke(provider,new object[]{empty,new List<OVRAnchor>(),0,callback}),"superseded stage cannot publish into another generation");
            Check(newOwnerRoot!=null&&newOwnerMaterial!=null&&ReferenceEquals(Get(provider,"scanMaterial"),newOwnerMaterial)&&meshes.Count==1,"newer owner's actual room roots/material survive superseded cleanup");
            Check(stagedRoot==null&&stagedMaterial==null&&anchors.Count==0,"old stage resources are released without resurrecting prior anchor ownership");
        }
        finally
        {
            stageAction=null;anchors.Clear();meshes.Clear();Set(provider,"scanMaterial",null);UnityEngine.Object.DestroyImmediate(owner);
            foreach(var obj in new UnityEngine.Object[]{oldRoot,oldMaterial,(UnityEngine.Object)Get(priorMesh,"Mesh"),stagedRoot,stagedMaterial,stagedMesh,newOwnerRoot,newOwnerMaterial,newOwnerMesh})if(obj!=null)UnityEngine.Object.DestroyImmediate(obj);
        }
    }
}
