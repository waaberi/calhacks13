using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.OpenXR;

namespace SpatialModeling
{
    public sealed partial class WorkspaceSurfaces
    {
        // Private device references only. No poses, dimensions, boundary vertices
        // or reconstruction meshes are persisted or replayed by this cache.
        [Serializable] public sealed class RoomRecoveryIndex
        {
            public int version=1;
            public List<RoomRecoveryReference> anchors=new List<RoomRecoveryReference>();
        }
        [Serializable] public sealed class RoomRecoveryReference
        {
            public string id,room,kind;
        }
        RoomRecoveryIndex roomRecovery;
        bool roomRecoveryRead;
        string RoomRecoveryPath => Path.Combine(Application.persistentDataPath,"saved-room-references.json");

        // Keep retrying a temporarily unavailable Link service at a bounded rate.
        // This is recovery, never a request to launch system scan/setup.
        public static float RoomRetryDelay(int attempt) => Mathf.Min(60f,15f*Mathf.Max(1,attempt));

        void ReadRoomRecovery()
        {
            if(roomRecoveryRead) return;
            roomRecoveryRead=true;
            roomRecovery=new RoomRecoveryIndex();
            try
            {
                var path=RoomRecoveryPath;
                if(File.Exists(path)) roomRecovery=ValidateRoomRecovery(JsonUtility.FromJson<RoomRecoveryIndex>(File.ReadAllText(path)));
                // One-time, opt-in migration of a previous private actual-room
                // diagnostic. Only its UUID references are imported. Every pose,
                // boundary and mesh must still be obtained afresh from Meta.
                var evidence=Environment.GetEnvironmentVariable("CALHACKS_ROOM_RECOVERY_EVIDENCE");
                if(roomRecovery.anchors.Count==0 && !string.IsNullOrWhiteSpace(evidence) && File.Exists(evidence))
                {
                    roomRecovery=RecoveryReferencesFromEvidence(JsonUtility.FromJson<RoomEvidence>(File.ReadAllText(evidence)));
                    Debug.Log("WORKSPACE_ROOM_RECOVERY imported private UUID references="+roomRecovery.anchors.Count+" saved_poses_used=False");
                }
            }
            catch(Exception error) {Debug.LogWarning("WORKSPACE_ROOM_RECOVERY references unavailable "+error.GetType().Name);}
        }
        public static RoomRecoveryIndex ValidateRoomRecovery(RoomRecoveryIndex value)
        {
            var result=new RoomRecoveryIndex();var seen=new HashSet<Guid>();
            if(value==null || value.version!=1 || value.anchors==null || value.anchors.Count>4096) return result;
            foreach(var reference in value.anchors)
            {
                if(reference==null || !Guid.TryParse(reference.id,out var id) || id==Guid.Empty
                    || !Guid.TryParse(reference.room,out var room) || room==Guid.Empty || !seen.Add(id)) continue;
                result.anchors.Add(new RoomRecoveryReference {id=id.ToString(),room=room.ToString(),
                    kind=reference.kind=="Floor" || reference.kind=="Wall" || reference.kind=="Desk" ? reference.kind : null});
            }
            return result;
        }
        public static RoomRecoveryIndex RecoveryReferencesFromEvidence(RoomEvidence data)
        {
            var result=new RoomRecoveryIndex();
            if(data==null || data.anchors==null || data.anchors.Count>4096) return result;
            Guid floor=Guid.Empty;
            foreach(var anchor in data.anchors)
            {
                if(anchor==null || RecoveryKind(anchor)!="Floor") continue;
                if(floor!=Guid.Empty || !Guid.TryParse(anchor.id,out floor) || floor==Guid.Empty) return result;
            }
            if(floor==Guid.Empty) return result;
            // Historical diagnostics did not store the RoomLayout root UUID.
            // The single recorded FLOOR UUID is a recovery group identity only;
            // it never claims to be a freshly enumerated RoomLayout. Current
            // tracked floor containment remains required by room localization.
            foreach(var anchor in data.anchors)
                if(anchor!=null) result.anchors.Add(new RoomRecoveryReference {
                    id=anchor.id,room=floor.ToString(),kind=RecoveryKind(anchor)});
            return ValidateRoomRecovery(result);
        }
        static string RecoveryKind(AnchorEvidence anchor)
            => string.IsNullOrEmpty(anchor.kind)?ClassifyLabels(anchor.labels):anchor.kind;
        async Task RecoverSavedRoomAnchors(List<RoomAnchor> next,List<OVRAnchor> owned,Func<bool> current)
        {
            ReadRoomRecovery();
            if(roomRecovery.anchors.Count==0) return;
            var references=new Dictionary<Guid,RoomRecoveryReference>();
            foreach(var item in roomRecovery.anchors) references[Guid.Parse(item.id)]=item;
            // Apply known membership to semantic-only results as well.
            for(int i=0;i<next.Count;i++)
                if(references.TryGetValue(next[i].Anchor.Uuid,out var reference))
                {var item=next[i];item.Room=Guid.Parse(reference.room);item.Kind=reference.kind;next[i]=item;}
            foreach(var batch in Batches(references.Keys))
            {
                var recovered=new List<OVRAnchor>();
                var result=await OVRAnchor.FetchAnchorsAsync(recovered,new OVRAnchor.FetchOptions {Uuids=batch});
                owned.AddRange(recovered);
                if(!current()) return;
                Debug.Log("WORKSPACE_ROOM_RECOVERY UUID discovery count="+recovered.Count+" status="+result.Status);
                if((!result.Success || recovered.Count==0) && OpenXRRuntime.IsExtensionEnabled("XR_FB_spatial_entity_query"))
                {
                    recovered=new List<OVRAnchor>();
#pragma warning disable CS0618
                    bool legacy=await OVRAnchor.FetchAnchorsAsync(batch,recovered,timeout:5);
#pragma warning restore CS0618
                    owned.AddRange(recovered);
                    if(!current()) return;
                    Debug.Log("WORKSPACE_ROOM_RECOVERY UUID compatibility count="+recovered.Count+" success="+legacy);
                }
                foreach(var anchor in recovered)
                {
                    if(next.Exists(item=>item.Anchor.Uuid==anchor.Uuid) || !references.TryGetValue(anchor.Uuid,out var reference)
                        || !anchor.TryGetComponent<OVRLocatable>(out var locatable)) continue;
                    await locatable.SetEnabledAsync(true);
                    if(!current()) return;
                    if(locatable.IsEnabled) next.Add(new RoomAnchor {Anchor=anchor,Locatable=locatable,
                        Room=Guid.Parse(reference.room),Kind=reference.kind});
                }
            }
        }
        async Task WaitForRoomReplacement(List<RoomAnchor> next,Func<bool> current)
        {
            if(anchors.Count==0 || next.Count==0) return;
            double until=Time.realtimeSinceStartupAsDouble+2;
            // SetEnabledAsync can complete before the camera/OVR frame update.
            // Give localization fresh frames without clearing the current room.
            while(current() && RoomHeadReady() && Time.realtimeSinceStartupAsDouble<until)
            {
                if(RoomReplacementLocalized(next)) return;
                await Task.Delay(16);
            }
        }
        static bool CurrentRoomAnchor(RoomAnchor item)
        {
            try {return item.Locatable.TryGetSceneAnchorPose(out var pose) && pose.Position.HasValue && pose.Rotation.HasValue
                && pose.IsPositionTracked && pose.IsRotationTracked;}
            catch(Exception) {return false;}
        }
        bool RoomReplacementLocalized(List<RoomAnchor> next)
        {
            if(!RoomHeadReady() || Camera.main==null) return false;
            UpdateSceneTrackingFrame(true);
            var floors=new List<WorkspaceRoomLocalization.FloorCandidate>();
            double now=Time.realtimeSinceStartupAsDouble;
            foreach(var item in next)
            {
                if(item.Room==Guid.Empty) continue;
                try
                {
                    string kind=item.Kind;
                    if(string.IsNullOrEmpty(kind) && item.Anchor.TryGetComponent<OVRSemanticLabels>(out var semantic))
#pragma warning disable CS0618
                        kind=ClassifyLabels(semantic.Labels);
#pragma warning restore CS0618
                    if(kind!="Floor" || !item.Locatable.TryGetSceneAnchorPose(out var pose) || !pose.Position.HasValue
                        || !pose.Rotation.HasValue || !pose.IsPositionTracked || !pose.IsRotationTracked
                        || !item.Anchor.TryGetComponent<OVRBounded2D>(out var plane)
                        || !plane.TryGetBoundaryPointsCount(out int count) || count<3 || count>16384) continue;
                    using(var points=new NativeArray<Vector2>(count,Allocator.Temp))
                    {
                        if(!plane.TryGetBoundaryPoints(points)) continue;
                        floors.Add(new WorkspaceRoomLocalization.FloorCandidate {Room=item.Room,Tracked=true,SampleTime=now,
                            WorldPose=SceneToWorld(sceneTrackingWorld,new Pose(pose.Position.Value,pose.Rotation.Value)),Boundary=points.ToArray()});
                    }
                }
                catch(Exception) { /* A partial SDK component cannot replace the current room. */ }
            }
            return WorkspaceRoomLocalization.TrySelectRoom(floors,
                new Pose(Camera.main.transform.position,Camera.main.transform.rotation),true,now,out _,out _);
        }
        bool ApplyRoomLoad(List<RoomAnchor> next,List<OVRAnchor> rooms)
        {
            if(next.Count==0 || !next.Exists(item=>item.Room!=Guid.Empty))
            {
                message=anchors.Count>0 ? "Room reload empty · retaining saved anchors and retrying"
                    : "Waiting for saved Meta room data · retrying automatically";
                Debug.Log("WORKSPACE_ROOM_RECOVERY empty_result_preserved=True retained_anchors="+anchors.Count);
                return false;
            }
            if(anchors.Count>0 && !RoomReplacementLocalized(next))
            {
                message="Room reload not localized · retaining saved anchors and retrying";
                Debug.Log("WORKSPACE_ROOM_RECOVERY unlocalized_replacement_preserved=True retained_anchors="+anchors.Count);
                return false;
            }
            // A partial reply must not erase other still-tracked anchors from
            // the same saved room. Their current SDK poses are checked each frame.
            var nextRooms=new HashSet<Guid>();
            foreach(var item in next) if(item.Room!=Guid.Empty) nextRooms.Add(item.Room);
            foreach(var item in anchors)
            {
                if(!nextRooms.Contains(item.Room)) continue;
                int index=next.FindIndex(value=>value.Anchor.Uuid==item.Anchor.Uuid);
                if(index<0) next.Add(item);
                else if(CurrentRoomAnchor(item) && !CurrentRoomAnchor(next[index])) next[index]=item;
            }
            var previous=new List<RoomAnchor>(anchors);
            anchors.Clear();anchors.AddRange(next);
            foreach(var item in previous)
                if(!anchors.Exists(value=>value.Anchor.Equals(item.Anchor))) item.Anchor.Dispose();
            detected.Clear();surfaces.Clear();invalidLogged.Clear();evidenceWritten=false;
            knownRooms.Clear();localizedRoom=Guid.Empty;
            foreach(var room in rooms) knownRooms.Add(room.Uuid);
            foreach(var item in anchors) if(item.Room!=Guid.Empty) knownRooms.Add(item.Room);
            roomCount=knownRooms.Count;
            ClearScanGeometry();ReadScanGeometry();
            message="Saved room anchors loaded";
            SaveRoomRecovery();
            return true;
        }
        void SaveRoomRecovery()
        {
            var value=new RoomRecoveryIndex();
            foreach(var item in anchors)
                if(item.Room!=Guid.Empty) value.anchors.Add(new RoomRecoveryReference {
                    id=item.Anchor.Uuid.ToString(),room=item.Room.ToString(),kind=item.Kind});
            value=ValidateRoomRecovery(value);
            if(value.anchors.Count==0) return;
            roomRecovery=value;roomRecoveryRead=true;
            if(!Application.isPlaying) return;
            try
            {
                var path=RoomRecoveryPath;Directory.CreateDirectory(Path.GetDirectoryName(path));
                var temporary=path+".tmp";File.WriteAllText(temporary,JsonUtility.ToJson(value));
                if(File.Exists(path)) File.Replace(temporary,path,null); else File.Move(temporary,path);
            }
            catch(Exception error) {Debug.LogWarning("WORKSPACE_ROOM_RECOVERY references save unavailable "+error.GetType().Name);}
        }
    }
}
