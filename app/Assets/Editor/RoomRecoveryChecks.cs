using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using SpatialModeling;
using UnityEngine;

public static class RoomRecoveryChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string message) {if(!value) throw new Exception("Room recovery: "+message);}
    public static void Run()
    {
        RoomContinuityChecks.Run();
        Check(SpatialModeling.Diagnostics.RoomRawCompletionObserver.ValidateNativeLayout()
            && SpatialModeling.Diagnostics.RoomRawCompletionObserver.VerifyDecoder(),
            "raw OpenXR observer ABI, request ownership, value-copy, duplicate rejection and bounded quota");
        var floor=Guid.NewGuid();var desk=Guid.NewGuid();
        var recorded=new WorkspaceSurfaces.RoomEvidence();
        recorded.anchors.Add(new WorkspaceSurfaces.AnchorEvidence {id=floor.ToString(),kind="Floor",
            trackingPose=new Pose(new Vector3(100,200,300),Quaternion.Euler(42,19,71)),
            boundary=new[]{Vector2.zero,Vector2.right,Vector2.up}});
        recorded.anchors.Add(new WorkspaceSurfaces.AnchorEvidence {id=desk.ToString(),labels="DESK,TABLE"});
        var references=WorkspaceSurfaces.RecoveryReferencesFromEvidence(recorded);
        Check(references.anchors.Count==2 && references.anchors[0].room==floor.ToString()
            && references.anchors[1].kind=="Desk","single actual floor creates a UUID-only recovery group");
        var json=JsonUtility.ToJson(references);
        Check(!json.Contains("\"trackingPose\"") && !json.Contains("\"boundary\"") && !json.Contains("\"position\"")
            && !json.Contains("\"rotation\""),"private recovery cache cannot persist or replay old geometry/poses");
        recorded.anchors.Add(new WorkspaceSurfaces.AnchorEvidence {id=Guid.NewGuid().ToString(),kind="Floor"});
        Check(WorkspaceSurfaces.RecoveryReferencesFromEvidence(recorded).anchors.Count==0,
            "ambiguous multiroom diagnostics cannot group unrelated room anchors");
        references.anchors.Add(new WorkspaceSurfaces.RoomRecoveryReference {id="invalid",room=floor.ToString()});
        references.anchors.Add(new WorkspaceSurfaces.RoomRecoveryReference {id=desk.ToString(),room=floor.ToString()});
        references.anchors.Add(new WorkspaceSurfaces.RoomRecoveryReference {id=Guid.NewGuid().ToString(),room=Guid.Empty.ToString()});
        Check(WorkspaceSurfaces.ValidateRoomRecovery(references).anchors.Count==2,"bad/duplicate/unknown-room UUIDs never enter recovery");
        Check(WorkspaceSurfaces.RoomRetryDelay(1)==15 && WorkspaceSurfaces.RoomRetryDelay(3)==45
            && WorkspaceSurfaces.RoomRetryDelay(1000)==60,"retries continue beyond three attempts without a busy query loop");
        Check(WorkspaceSurfaces.RoomLocalizationTimeoutSeconds>1
            && WorkspaceSurfaces.RoomLocalizationReadinessSeconds>=2*WorkspaceSurfaces.RoomLocalizationTimeoutSeconds+1,
            "localization uses positive multi-second native deadlines and retains handles through two full requests plus fresh frames");
        Check(WorkspaceSurfaces.RoomLocalizationCanStart(WorkspaceSurfaces.RoomLocalizationReadinessSeconds,0)
            && WorkspaceSurfaces.RoomLocalizationCanStart(WorkspaceSurfaces.RoomLocalizationReadinessSeconds-5.1,1)
            && !WorkspaceSurfaces.RoomLocalizationCanStart(4.9,1) && !WorkspaceSurfaces.RoomLocalizationCanStart(12,2),
            "retry policy permits a second full localization window but cannot truncate it or issue more than two requests");
        var currentFloor=new WorkspaceRoomLocalization.FloorCandidate {Room=floor,Tracked=true,SampleTime=10,
            WorldPose=new Pose(new Vector3(3,0,-4),Quaternion.Euler(90,37,0)),
            Boundary=new[]{new Vector2(-2,-2),new Vector2(2,-2),new Vector2(2,0),Vector2.zero,new Vector2(0,2),new Vector2(-2,2)}};
        var inside=currentFloor.WorldPose.position+currentFloor.WorldPose.rotation*new Vector3(-1,1,-.8f);
        var outside=currentFloor.WorldPose.position+currentFloor.WorldPose.rotation*new Vector3(1,1,-.8f);
        Check(WorkspaceSurfaces.RecoveryPointWithinFloor(currentFloor,inside)
            && !WorkspaceSurfaces.RecoveryPointWithinFloor(currentFloor,outside),
            "unmatched current semantic geometry is associated through the actual concave floor and one origin conversion");

        var go=new GameObject("Room empty-reload regression");go.SetActive(false);
        var provider=go.AddComponent<WorkspaceSurfaces>();
        var anchors=(IList)typeof(WorkspaceSurfaces).GetField("anchors",Private).GetValue(provider);
        var detected=(List<WorkspaceSurfaces.Surface>)typeof(WorkspaceSurfaces).GetField("detected",Private).GetValue(provider);
        var boundaries=(Dictionary<Guid,Vector2[]>)typeof(WorkspaceSurfaces).GetField("scanBoundaries",Private).GetValue(provider);
        var rooms=(HashSet<Guid>)typeof(WorkspaceSurfaces).GetField("knownRooms",Private).GetValue(provider);
        try
        {
            // An opaque existing SDK handle is not read, disposed or rewritten by
            // an empty replacement. This exercises the real commit method.
            anchors.Add(Activator.CreateInstance(anchors.GetType().GetGenericArguments()[0]));
            var boundary=new[]{Vector2.zero,Vector2.right,Vector2.up};
            boundaries[floor]=boundary;rooms.Add(floor);
            detected.Add(new WorkspaceSurfaces.Surface {Id=desk,Name="Desk",Boundary=boundary});
            var empty=Activator.CreateInstance(anchors.GetType());
            var committed=(bool)typeof(WorkspaceSurfaces).GetMethod("ApplyRoomLoad",Private)
                .Invoke(provider,new[]{empty,new List<OVRAnchor>()});
            Check(!committed && anchors.Count==1 && detected.Count==1 && rooms.Contains(floor)
                && ReferenceEquals(boundaries[floor],boundary),"empty successful SDK reload retains live anchor/room/boundary state atomically");
            Check(provider.State.Contains("retaining saved anchors"),"empty reload reports recovery instead of claiming the saved scan was deleted");
            var unlocalized=Activator.CreateInstance(anchors.GetType());
            var unlocalizedAnchor=Activator.CreateInstance(anchors.GetType().GetGenericArguments()[0]);
            unlocalizedAnchor.GetType().GetField("Room",BindingFlags.Instance|BindingFlags.Public).SetValue(unlocalizedAnchor,floor);
            ((IList)unlocalized).Add(unlocalizedAnchor);
            committed=(bool)typeof(WorkspaceSurfaces).GetMethod("ApplyRoomLoad",Private)
                .Invoke(provider,new[]{unlocalized,new List<OVRAnchor>()});
            Check(!committed && anchors.Count==1 && detected.Count==1 && ReferenceEquals(boundaries[floor],boundary),
                "a nonempty replacement without current worn/focused floor localization also retains the prior room");
            string actual=Environment.GetEnvironmentVariable("CALHACKS_ROOM_REPLAY");
            if(!string.IsNullOrWhiteSpace(actual))
            {
                var data=JsonUtility.FromJson<WorkspaceSurfaces.RoomEvidence>(File.ReadAllText(actual));
                var actualReferences=WorkspaceSurfaces.RecoveryReferencesFromEvidence(data);
                Check(actualReferences.anchors.Count==data.anchors.Count && actualReferences.anchors.Count>0,
                    "actual private known-room capture imports every UUID without importing transforms");
            }
        }
        finally {anchors.Clear();UnityEngine.Object.DestroyImmediate(go);}
        Debug.Log("ROOM_RECOVERY_CHECKS PASS atomic_empty_reload retained_anchor_geometry UUID_only_cache actual_room_migration bounded_continuing_retry fresh_SDK_localization_required=True");
    }
}
