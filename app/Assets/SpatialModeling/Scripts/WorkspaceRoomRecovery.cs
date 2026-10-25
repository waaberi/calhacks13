using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.OpenXR;
using SpatialModeling.Diagnostics;

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
        [Serializable] public sealed class VerifiedRoomCheckpoint
        {
            public int version=1;
            public string room,floor,verification,verified_at_utc;
            public List<string> anchors=new List<string>();
        }
        VerifiedRoomCheckpoint verifiedRoomCheckpoint;
        bool verifiedCheckpointRead,verifiedCheckpointDurable;
        Guid verifiedRoomIdentity,verifiedFloorIdentity;
        bool roomRecoveryRead;
        int roomRecoveryDiagnosticLoads;
        RoomRawCompletionObserver rawRoomCompletion;
        // The installed OpenXR shim converts SDK timeout zero to zero ns.
        // Always supply a real positive localization window. Keep the overall
        // parallel batch bounded, and never start a retry it cannot finish.
        public const double RoomLocalizationTimeoutSeconds=5;
        public const double RoomLocalizationReadinessSeconds=12;
        public static bool RoomLocalizationCanStart(double remainingSeconds,int requests)
            => requests<2 && remainingSeconds>=RoomLocalizationTimeoutSeconds;
        string RoomRecoveryPath => Path.Combine(Application.persistentDataPath,"saved-room-references.json");
        string VerifiedRoomPath => Path.Combine(Application.persistentDataPath,"verified-room-checkpoint.json");

        // Keep retrying a temporarily unavailable Link service at a bounded rate.
        // This is recovery, never a request to launch system scan/setup.
        public static float RoomRetryDelay(int attempt) => Mathf.Min(60f,15f*Mathf.Max(1,attempt));

        void ReadRoomRecovery()
        {
            if(roomRecoveryRead) return;
            roomRecoveryRead=true;
            roomRecovery=new RoomRecoveryIndex();
            ReadVerifiedRoomCheckpoint();
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
                    PersistRoomRecoveryIndex(roomRecovery);
                }
            }
            catch(Exception error) {Debug.LogWarning("WORKSPACE_ROOM_RECOVERY references unavailable "+error.GetType().Name);}
            if(verifiedRoomCheckpoint!=null)
            {
                var retained=new RoomRecoveryIndex();
                foreach(var id in verifiedRoomCheckpoint.anchors)retained.anchors.Add(new RoomRecoveryReference{
                    id=id,room=verifiedRoomCheckpoint.room,kind=id==verifiedRoomCheckpoint.floor?"Floor":null});
                roomRecovery=MergeRoomRecovery(roomRecovery,retained);
            }
        }
        public static VerifiedRoomCheckpoint ValidateVerifiedRoom(VerifiedRoomCheckpoint value)
        {
            if(value==null||value.version!=1||value.verification!="fresh_tracked_floor_contains_head"
                ||!Guid.TryParse(value.room,out var room)||room==Guid.Empty||!Guid.TryParse(value.floor,out var floor)||floor==Guid.Empty
                ||!DateTimeOffset.TryParse(value.verified_at_utc,out _)||value.anchors==null||value.anchors.Count==0||value.anchors.Count>4096)return null;
            var result=new VerifiedRoomCheckpoint{room=room.ToString(),floor=floor.ToString(),verification=value.verification,verified_at_utc=value.verified_at_utc};
            var seen=new HashSet<Guid>();foreach(var id in value.anchors)
            {if(!Guid.TryParse(id,out var anchor)||anchor==Guid.Empty||!seen.Add(anchor))return null;result.anchors.Add(anchor.ToString());}
            return seen.Contains(floor)?result:null;
        }
        public static RoomRecoveryIndex MergeRoomRecovery(RoomRecoveryIndex previous,RoomRecoveryIndex incoming)
        {
            previous=ValidateRoomRecovery(previous);incoming=ValidateRoomRecovery(incoming);
            var result=ValidateRoomRecovery(previous);var byId=new Dictionary<string,RoomRecoveryReference>();
            foreach(var row in result.anchors)byId[row.id]=row;
            foreach(var row in incoming.anchors)
            {
                if(byId.TryGetValue(row.id,out var existing)){existing.room=row.room;if(row.kind!=null)existing.kind=row.kind;}
                else {result.anchors.Add(row);byId[row.id]=row;}
            }
            return result.anchors.Count>4096?previous:result;
        }
        public static VerifiedRoomCheckpoint ReadVerifiedRoomFile(string path)
        {try{return File.Exists(path)?ValidateVerifiedRoom(JsonUtility.FromJson<VerifiedRoomCheckpoint>(File.ReadAllText(path))):null;}catch(Exception){return null;}}
        public static bool PersistVerifiedRoomFile(string path,VerifiedRoomCheckpoint value)
        {
            value=ValidateVerifiedRoom(value);if(value==null)return false;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));var temporary=path+".tmp";File.WriteAllText(temporary,JsonUtility.ToJson(value));
                if(File.Exists(path))File.Replace(temporary,path,path+".previous");else File.Move(temporary,path);return true;
            }
            catch(Exception){return false;}
        }
        void ReadVerifiedRoomCheckpoint()
        {
            if(verifiedCheckpointRead)return;verifiedCheckpointRead=true;
            var paths=new[]{VerifiedRoomPath,VerifiedRoomPath+".previous",Environment.GetEnvironmentVariable("CALHACKS_VERIFIED_ROOM_CHECKPOINT")};
            foreach(var path in paths)
            {
                if(string.IsNullOrWhiteSpace(path))continue;
                try
                {
                    if(!File.Exists(path))continue;
                    var value=ReadVerifiedRoomFile(path);if(value==null)continue;
                    verifiedRoomCheckpoint=value;verifiedRoomIdentity=Guid.Parse(value.room);verifiedFloorIdentity=Guid.Parse(value.floor);
                    verifiedCheckpointDurable=path==VerifiedRoomPath;
                    Debug.Log("WORKSPACE_ROOM_CONTINUITY checkpoint_loaded=True references="+value.anchors.Count+" current_tracking_required=True");return;
                }
                catch(Exception error){Debug.LogWarning("WORKSPACE_ROOM_CONTINUITY checkpoint_read_failed="+error.GetType().Name+" prior_preserved=True");}
            }
        }
        bool SelectCurrentRoom(IReadOnlyList<WorkspaceRoomLocalization.FloorCandidate> floors,Pose head,bool ready,double now,out Guid room,out string reason)
        {
            ReadVerifiedRoomCheckpoint();
            return WorkspaceRoomLocalization.TrySelectRoomWithContinuity(floors,head,ready,now,verifiedRoomIdentity,verifiedFloorIdentity,out room,out reason);
        }
        void RememberVerifiedRoom(Guid room,IReadOnlyList<WorkspaceRoomLocalization.FloorCandidate> floors,Pose head,double now)
        {
            WorkspaceRoomLocalization.FloorCandidate selected=default;
            foreach(var floor in floors)if(floor.Room==room&&floor.Anchor!=Guid.Empty
                &&WorkspaceRoomLocalization.ContainsHead(floor,head.position,now,WorkspaceRoomLocalization.DefaultLimits)){selected=floor;break;}
            if(selected.Anchor==Guid.Empty)return;
            if(verifiedRoomIdentity==room&&verifiedFloorIdentity==selected.Anchor&&verifiedCheckpointDurable)return;
            var value=new VerifiedRoomCheckpoint{room=room.ToString(),floor=selected.Anchor.ToString(),verification="fresh_tracked_floor_contains_head",verified_at_utc=DateTimeOffset.UtcNow.ToString("O")};
            if(verifiedRoomCheckpoint!=null&&verifiedRoomIdentity==room&&verifiedFloorIdentity==selected.Anchor)value.anchors.AddRange(verifiedRoomCheckpoint.anchors);
            foreach(var anchor in anchors)if(anchor.Room==room&&!value.anchors.Contains(anchor.Anchor.Uuid.ToString()))value.anchors.Add(anchor.Anchor.Uuid.ToString());
            value=ValidateVerifiedRoom(value);if(value==null)return;
            verifiedRoomCheckpoint=value;verifiedRoomIdentity=room;verifiedFloorIdentity=selected.Anchor;verifiedCheckpointDurable=false;
            if(!Application.isPlaying)return;
            try
            {
                verifiedCheckpointDurable=PersistVerifiedRoomFile(VerifiedRoomPath,value);
                if(!verifiedCheckpointDurable){Debug.LogWarning("WORKSPACE_ROOM_CONTINUITY checkpoint_write_failed=True legacy_references_preserved=True retry_pending=True");return;}
                Debug.Log("WORKSPACE_ROOM_CONTINUITY fresh_checkpoint_saved=True references="+value.anchors.Count+" poses_saved=False");
                SaveRoomRecovery();
            }
            catch(Exception error){Debug.LogWarning("WORKSPACE_ROOM_CONTINUITY checkpoint_write_failed="+error.GetType().Name+" legacy_references_preserved=True");}
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
                bool diagnostic=roomRecoveryDiagnosticLoads++<2;
                var preparations=new List<Task<RoomAnchor?>>();
                int index=0;
                if(diagnostic)
                {
                    OVRManager.SpaceSetComponentStatusComplete+=RoomEnableCompleteDiagnostic;
                    bool subscribed=RoomRawCompletionObserver.TryBegin(RoomRawEnableCompleteDiagnostic,out rawRoomCompletion,maximum:22);
                    Debug.Log("WORKSPACE_ROOM_RECOVERY raw_openxr_observer="+subscribed+" maximum_events=22 own_requests_only=True");
                }
                try
                {
                foreach(var anchor in recovered)
                {
                    bool duplicate=next.Exists(item=>item.Anchor.Uuid==anchor.Uuid);
                    bool matched=references.TryGetValue(anchor.Uuid,out var reference);
                    if(diagnostic) Debug.Log("WORKSPACE_ROOM_RECOVERY anchor="+index+" uuid_match="+matched+" duplicate="+duplicate);
                    if(!duplicate) preparations.Add(PrepareRecoveredRoomAnchor(anchor,reference,current,diagnostic,index));
                    index++;
                }
                var prepared=await Task.WhenAll(preparations);
                if(!current()) return;
                foreach(var item in prepared) if(item.HasValue) next.Add(item.Value);
                AssociateRecoveredSceneElements(next);
                Debug.Log("WORKSPACE_ROOM_RECOVERY prepared="+next.Count+" matched_references="+
                    next.FindAll(item=>references.ContainsKey(item.Anchor.Uuid)).Count);
                }
                finally
                {
                    if(diagnostic)
                    {OVRManager.SpaceSetComponentStatusComplete-=RoomEnableCompleteDiagnostic;DisposeRoomRawCompletion();}
                }
            }
        }
        async Task<RoomAnchor?> PrepareRecoveredRoomAnchor(OVRAnchor anchor,RoomRecoveryReference reference,
            Func<bool> current,bool diagnostic,int index)
        {
            double until=Time.realtimeSinceStartupAsDouble+RoomLocalizationReadinessSeconds;
            OVRLocatable locatable=default;
            OVRTask<bool> enable=default;
            bool component=false,enablePending=false,lastEnableResult=false;
            int requests=0,samples=0;
            try
            {
                if(diagnostic)
                {
                    var supported=new List<OVRPlugin.SpaceComponentType>();
                    bool enumerated=anchor.GetSupportedComponents(supported);
                    Debug.Log("WORKSPACE_ROOM_RECOVERY anchor="+index+" supported_read="+enumerated+" components="+string.Join(",",supported)+
                        " "+RecoveredAnchorNativeStatus(anchor));
                }
                while(current() && Time.realtimeSinceStartupAsDouble<until)
                {
                    samples++;
                    component=anchor.TryGetComponent(out locatable);
                    if(component && locatable.IsEnabled)
                    {
                        string kind=reference?.kind;
                        if(string.IsNullOrEmpty(kind) && anchor.TryGetComponent<OVRSemanticLabels>(out var semantic))
#pragma warning disable CS0618
                            kind=ClassifyLabels(semantic.Labels);
#pragma warning restore CS0618
                        var item=new RoomAnchor {Anchor=anchor,Locatable=locatable,
                            Room=reference!=null?Guid.Parse(reference.room):Guid.Empty,Kind=kind};
                        if(diagnostic) Debug.Log("WORKSPACE_ROOM_RECOVERY anchor="+index+" locatable=True enabled=True tracked="+
                            CurrentRoomAnchor(item)+" samples="+samples+" enable_requests="+requests+" enable_result="+lastEnableResult+" kind="+kind);
                        return item;
                    }
                    if(enablePending && enable.IsCompleted)
                    {lastEnableResult=enable.GetResult();enablePending=false;}
                    if(component && !enablePending && RoomLocalizationCanStart(until-Time.realtimeSinceStartupAsDouble,requests))
                    {enable=diagnostic?BeginRoomEnableDiagnostic(anchor,locatable,index):locatable.SetEnabledAsync(true,timeout:RoomLocalizationTimeoutSeconds);
                        enablePending=true;requests++;}
                    await Task.Delay(16);
                }
                Debug.LogWarning("WORKSPACE_ROOM_RECOVERY anchor="+index+" readiness_timeout locatable="+component+
                    " enabled="+(component&&locatable.IsEnabled)+" enable_requests="+requests+" enable_pending="+enablePending+
                    " enable_result="+lastEnableResult+" samples="+samples+(diagnostic?" "+RecoveredAnchorNativeStatus(anchor):""));
                return null;
            }
            finally {if(enablePending) enable.Dispose();}
        }
        OVRTask<bool> BeginRoomEnableDiagnostic(OVRAnchor anchor,OVRLocatable locatable,int index)
        {
            try
            {
            // The SDK's public wrapper reduces the immediate native Result to a
            // bool. Use its identical existing shim/task path for this bounded
            // diagnostic so rejection and later completion remain distinguishable.
            var handleProperty=typeof(OVRAnchor).GetProperty("Handle",BindingFlags.Instance|BindingFlags.NonPublic);
            var shim=typeof(OVRPlugin).GetNestedType("Shim",BindingFlags.NonPublic);
            var set=shim?.GetMethod("ovrp_SetSpaceComponentStatus",BindingFlags.Static|BindingFlags.Public);
            MethodInfo fromRequest=null;
            foreach(var method in typeof(OVRTask).GetMethods(BindingFlags.Static|BindingFlags.NonPublic))
                if(method.Name=="FromRequest" && method.IsGenericMethodDefinition && method.GetParameters().Length==1
                    && method.GetParameters()[0].ParameterType==typeof(ulong)) {fromRequest=method.MakeGenericMethod(typeof(bool));break;}
            if(handleProperty==null || set==null || fromRequest==null) return locatable.SetEnabledAsync(true,timeout:RoomLocalizationTimeoutSeconds);
            ulong handle=(ulong)handleProperty.GetValue(anchor);
            if(OVRPlugin.GetSpaceComponentStatus(handle,OVRPlugin.SpaceComponentType.Locatable,out bool enabled,out bool pending)
                && (enabled || pending)) return locatable.SetEnabledAsync(true,timeout:RoomLocalizationTimeoutSeconds);
            object[] arguments={handle,OVRPlugin.SpaceComponentType.Locatable,OVRPlugin.Bool.True,RoomLocalizationTimeoutSeconds,0UL};
            var result=(OVRPlugin.Result)set.Invoke(null,arguments);
            ulong request=(ulong)arguments[4];
            if((int)result>=0) rawRoomCompletion?.TrackRequest(request);
            Debug.Log("WORKSPACE_ROOM_RECOVERY anchor="+index+" enable_native_result="+result+" code="+(int)result+
                " request_nonzero="+(request!=0)+" timeout_seconds="+RoomLocalizationTimeoutSeconds);
            return (int)result<0 ? OVRTask.FromResult(false):(OVRTask<bool>)fromRequest.Invoke(null,new object[]{request});
            }
            catch(Exception error)
            {
                Debug.LogWarning("WORKSPACE_ROOM_RECOVERY native_enable_diagnostic_unavailable="+error.GetType().Name);
                return locatable.SetEnabledAsync(true,timeout:RoomLocalizationTimeoutSeconds);
            }
        }
        void DisposeRoomRawCompletion()
        {rawRoomCompletion?.Dispose();rawRoomCompletion=null;}
        static void RoomRawEnableCompleteDiagnostic(RoomRawCompletionObserver.Sample sample)
        {
            Debug.Log("WORKSPACE_ROOM_RECOVERY raw_openxr_completion_code="+sample.Result+
                " component="+sample.Component+" requested_enabled="+sample.Enabled+" own_request=True");
        }
        static int roomEnableDiagnosticEvents;
        static void RoomEnableCompleteDiagnostic(ulong request,bool success,OVRSpace space,Guid uuid,
            OVRPlugin.SpaceComponentType component,bool enabled)
        {
            if(component!=OVRPlugin.SpaceComponentType.Locatable || roomEnableDiagnosticEvents++>=44) return;
            try
            {
                // This event fires while OVRManager still holds the same parsed
                // buffer. Observe it without polling/consuming another XR event.
                var field=typeof(OVRManager).GetField("eventDataBuffer",BindingFlags.Static|BindingFlags.NonPublic);
                var buffer=(OVRPlugin.EventDataBuffer)field.GetValue(null);
                if(buffer.EventType!=OVRPlugin.EventType.SpaceSetComponentStatusComplete || buffer.EventData.Length<12) return;
                int code=BitConverter.ToInt32(buffer.EventData,8);
                Debug.Log("WORKSPACE_ROOM_RECOVERY enable_completion_result="+(OVRPlugin.Result)code+" code="+code+
                    " success="+success+" enabled="+enabled);
            }
            catch(Exception error) {Debug.LogWarning("WORKSPACE_ROOM_RECOVERY completion_diagnostic_unavailable="+error.GetType().Name);}
        }
        static string RecoveredAnchorNativeStatus(OVRAnchor anchor)
        {
            try
            {
                // Diagnostic access to the SDK's existing runtime handle only;
                // never synthesize a handle or component to bypass SDK readiness.
                var property=typeof(OVRAnchor).GetProperty("Handle",BindingFlags.Instance|BindingFlags.NonPublic);
                if(property==null) return "handle_read=unavailable";
                ulong handle=(ulong)property.GetValue(anchor);
                bool uuidRead=OVRPlugin.GetSpaceUuid(handle,out var uuid);
                var method=typeof(OVRPlugin).GetMethod("GetSpaceComponentStatusInternal",BindingFlags.Static|BindingFlags.NonPublic);
                if(method==null) return "handle_nonzero="+(handle!=0)+" native_uuid_read="+uuidRead;
                object[] arguments={handle,OVRPlugin.SpaceComponentType.Locatable,false,false};
                var result=method.Invoke(null,arguments);
                return "handle_nonzero="+(handle!=0)+" native_uuid_read="+uuidRead+" native_uuid_matches_wrapper="+
                    (uuidRead&&uuid==anchor.Uuid)+" locatable_status="+result+" enabled="+arguments[2]+" pending="+arguments[3];
            }
            catch(Exception error) {return "native_status_unavailable="+error.GetType().Name;}
        }
        // Some Link compatibility responses return current scene elements rather
        // than the requested historical UUIDs. Never assign their membership by
        // result order. Associate only fresh classified geometry that lies within
        // the actual unique FLOOR polygon currently containing the wearer.
        void AssociateRecoveredSceneElements(List<RoomAnchor> next)
        {
            if(!RoomHeadReady() || Camera.main==null) return;
            UpdateSceneTrackingFrame(true);
            double now=Time.realtimeSinceStartupAsDouble;
            var floors=new List<WorkspaceRoomLocalization.FloorCandidate>();
            foreach(var item in next)
            {
                if(item.Kind!="Floor" || !CurrentRoomAnchor(item)) continue;
                try
                {
                    if(!item.Locatable.TryGetSceneAnchorPose(out var pose) || !item.Anchor.TryGetComponent<OVRBounded2D>(out var plane)
                        || !plane.TryGetBoundaryPointsCount(out int count) || count<3 || count>16384) continue;
                    using(var points=new NativeArray<Vector2>(count,Allocator.Temp))
                        if(plane.TryGetBoundaryPoints(points)) floors.Add(new WorkspaceRoomLocalization.FloorCandidate {
                            Room=item.Room!=Guid.Empty?item.Room:item.Anchor.Uuid,Anchor=item.Anchor.Uuid,Tracked=true,SampleTime=now,
                            WorldPose=SceneToWorld(sceneTrackingWorld,new Pose(pose.Position.Value,pose.Rotation.Value)),Boundary=points.ToArray()});
                }
                catch(Exception) { }
            }
            if(!SelectCurrentRoom(floors,new Pose(Camera.main.transform.position,Camera.main.transform.rotation),
                true,now,out var currentRoom,out _)) return;
            var selected=floors.Find(item=>item.Room==currentRoom);
            int associated=0;
            for(int i=0;i<next.Count;i++)
            {
                var item=next[i];
                if(item.Room!=Guid.Empty || string.IsNullOrEmpty(item.Kind) || !CurrentRoomAnchor(item)) continue;
                try
                {
                    if(!item.Locatable.TryGetSceneAnchorPose(out var pose)) continue;
                    var world=SceneToWorld(sceneTrackingWorld,new Pose(pose.Position.Value,pose.Rotation.Value));
                    var center=world.position;
                    if(item.Anchor.TryGetComponent<OVRBounded2D>(out var plane))
                        center+=world.rotation*new Vector3(plane.BoundingBox.center.x,plane.BoundingBox.center.y,0);
                    else if(item.Anchor.TryGetComponent<OVRBounded3D>(out var volume)) center+=world.rotation*volume.BoundingBox.center;
                    if(!RecoveryPointWithinFloor(selected,center)) continue;
                    item.Room=currentRoom;next[i]=item;associated++;
                }
                catch(Exception) { }
            }
            if(associated>0) Debug.Log("WORKSPACE_ROOM_RECOVERY fresh_floor_associated="+associated+" membership_source=current_SDK_geometry");
        }
        public static bool RecoveryPointWithinFloor(WorkspaceRoomLocalization.FloorCandidate floor,Vector3 center)
        {
            var local=Quaternion.Inverse(floor.WorldPose.rotation)*(center-floor.WorldPose.position);
            return WorkspaceRoomLocalization.InsideActualBoundary(floor.Boundary,new Vector2(local.x,local.y),.05f);
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
                        floors.Add(new WorkspaceRoomLocalization.FloorCandidate {Room=item.Room,Anchor=item.Anchor.Uuid,Tracked=true,SampleTime=now,
                            WorldPose=SceneToWorld(sceneTrackingWorld,new Pose(pose.Position.Value,pose.Rotation.Value)),Boundary=points.ToArray()});
                    }
                }
                catch(Exception) { /* A partial SDK component cannot replace the current room. */ }
            }
            return SelectCurrentRoom(floors,
                new Pose(Camera.main.transform.position,Camera.main.transform.rotation),true,now,out _,out _);
        }
        bool ApplyRoomLoad(List<RoomAnchor> next,List<OVRAnchor> rooms)
            =>ApplyRoomLoadForGeneration(next,rooms,generation);
        bool ApplyRoomLoadForGeneration(List<RoomAnchor> next,List<OVRAnchor> rooms,int expectedGeneration)
        {
            if(disposed||!AutomaticEnabled||expectedGeneration!=generation)return false;
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
            // Keep previous room identities and handles even when another room
            // is discovered. Fresh eligibility still chooses what can be shown.
            next=new List<RoomAnchor>(next);
            foreach(var item in anchors)
            {
                int index=next.FindIndex(value=>value.Anchor.Uuid==item.Anchor.Uuid);
                if(index<0) next.Add(item);
                else if(CurrentRoomAnchor(item) && !CurrentRoomAnchor(next[index])) next[index]=item;
            }
            return CommitRoomAnchorSet(next,rooms,expectedGeneration,stage=>ReadScanGeometry(next,stage));
        }
        void ReleaseRoomGeometryStage(RoomGeometryStage stage)
        {
            foreach(var mesh in stage.Meshes)if(!scanMeshes.Contains(mesh)){DestroyObject(mesh.Root);DestroyObject(mesh.Mesh);}
            bool materialOwned=stage.Material==scanMaterial;
            foreach(var mesh in scanMeshes)if(mesh.Root!=null&&mesh.Root.GetComponent<MeshRenderer>()?.sharedMaterial==stage.Material)materialOwned=true;
            if(stage.Material!=null&&!materialOwned)DestroyObject(stage.Material);
        }
        bool CommitRoomAnchorSet(List<RoomAnchor> next,List<OVRAnchor> rooms,int expectedGeneration,Action<RoomGeometryStage> readGeometry)
        {
            var previous=new List<RoomAnchor>(anchors);
            var priorRooms=new HashSet<Guid>(knownRooms);var priorBoundaries=new Dictionary<Guid,Vector2[]>(scanBoundaries);
            var priorMeshes=new List<ScanMesh>(scanMeshes);var priorMaterial=scanMaterial;
            var stage=new RoomGeometryStage();
            try
            {
                readGeometry(stage);
                if(disposed||!AutomaticEnabled||expectedGeneration!=generation)
                {ReleaseRoomGeometryStage(stage);Debug.Log("WORKSPACE_ROOM_RECOVERY staged_generation_discarded=True newer_owner_preserved=True");return false;}
            }
            catch(Exception error)
            {
                ReleaseRoomGeometryStage(stage);
                if(expectedGeneration==generation)message="Room replacement incomplete · retaining the previous saved room";
                Debug.LogWarning("WORKSPACE_ROOM_RECOVERY staged_load_rolled_back=True reason="+error.GetType().Name);return false;
            }
            // Publishing is synchronous and allocation-free with respect to SDK
            // state. No old resources are released before the complete stage and
            // generation checks above have passed.
            anchors.Clear();anchors.AddRange(next);
            scanBoundaries.Clear();foreach(var entry in stage.Boundaries)scanBoundaries[entry.Key]=entry.Value;
            foreach(var entry in priorBoundaries)if(!scanBoundaries.ContainsKey(entry.Key)&&anchors.Exists(a=>a.Anchor.Uuid==entry.Key))scanBoundaries[entry.Key]=entry.Value;
            scanMeshes.Clear();scanMeshes.AddRange(stage.Meshes);scanMaterial=stage.Material;
            foreach(var mesh in priorMeshes)
                if(!scanMeshes.Exists(value=>value.Anchor.Anchor.Uuid==mesh.Anchor.Anchor.Uuid)&&anchors.Exists(a=>a.Anchor.Uuid==mesh.Anchor.Anchor.Uuid))
                {if(scanMaterial==null)scanMaterial=priorMaterial;mesh.Root.GetComponent<MeshRenderer>().sharedMaterial=scanMaterial;scanMeshes.Add(mesh);}
            knownRooms.Clear();knownRooms.UnionWith(priorRooms);
            foreach(var room in rooms)knownRooms.Add(room.Uuid);
            foreach(var item in anchors)if(item.Room!=Guid.Empty)knownRooms.Add(item.Room);
            roomCount=knownRooms.Count;invalidLogged.Clear();evidenceWritten=false;
            foreach(var mesh in priorMeshes)if(!scanMeshes.Contains(mesh)){DestroyObject(mesh.Root);DestroyObject(mesh.Mesh);}
            if(priorMaterial!=null&&priorMaterial!=scanMaterial)DestroyObject(priorMaterial);
            foreach(var item in previous)if(!anchors.Exists(value=>value.Anchor.Equals(item.Anchor)))
                try{item.Anchor.Dispose();}catch(Exception){Debug.LogWarning("WORKSPACE_ROOM_RECOVERY retired_handle_release_deferred=True");}
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
            ReadRoomRecovery();value=MergeRoomRecovery(roomRecovery,value);
            if(value.anchors.Count==0) return;
            if(verifiedRoomCheckpoint!=null&&!verifiedCheckpointDurable)return;
            roomRecovery=value;roomRecoveryRead=true;
            PersistRoomRecoveryIndex(value);
        }
        void PersistRoomRecoveryIndex(RoomRecoveryIndex value)
        {
            value=ValidateRoomRecovery(value);
            if(value.anchors.Count==0) return;
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
