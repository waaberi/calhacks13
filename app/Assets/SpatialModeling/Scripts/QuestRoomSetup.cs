using System;
using System.Collections;
using System.Collections.Generic;
using Meta.XR.MRUtilityKit;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityEngine.XR;

namespace SpatialModeling
{
    // A separate APK/scene: it never starts HostScene, Blender capture or native editing.
    public sealed class QuestRoomSetup : MonoBehaviour
    {
        MRUK room;
        EffectMesh geometry;
        Text instructions;
        bool busy, lastLoad, lastScan, lastExit;
        bool loadSucceeded, displayedDetailed;
        MRUKRoom displayedRoom;
        string state="Starting Meta room setup";
        void OnEnable()
        {
            OVRManager.HMDUnmounted+=HideRoomGeometry;
            OVRManager.VrFocusLost+=HideRoomGeometry;
        }
        void OnDisable()
        {
            OVRManager.HMDUnmounted-=HideRoomGeometry;
            OVRManager.VrFocusLost-=HideRoomGeometry;
            HideRoomGeometry();
        }
        void OnApplicationPause(bool paused) {if(paused) HideRoomGeometry();}
        void HideRoomGeometry() {if(geometry!=null) geometry.HideMesh=true;}
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void StartCompanion()
        {
            if(SceneManager.GetActiveScene().name=="QuestRoomSetup")
                new GameObject("Meta Room Setup companion").AddComponent<QuestRoomSetup>();
        }
        IEnumerator Start()
        {
            var rigObject=new GameObject("Meta camera rig");
            var manager=rigObject.AddComponent<OVRManager>();
            manager.trackingOriginType=OVRManager.TrackingOrigin.FloorLevel;
            manager.isInsightPassthroughEnabled=true;
            var rig=rigObject.AddComponent<OVRCameraRig>();
            var camera=rig.centerEyeAnchor.GetComponent<Camera>();
            camera.tag="MainCamera";camera.clearFlags=CameraClearFlags.SolidColor;
            camera.backgroundColor=Color.clear;camera.allowHDR=false;camera.nearClipPlane=.05f;
            new GameObject("Meta passthrough").AddComponent<OVRPassthroughLayer>();
            var roomObject=new GameObject("Meta MRUK saved room");roomObject.SetActive(false);
            room=roomObject.AddComponent<MRUK>();
            room.SceneSettings=new MRUK.MRUKSettings {LoadSceneOnStartup=false,DataSource=MRUK.SceneDataSource.Device};
            room.EnableWorldLock=true;roomObject.SetActive(true);
            geometry=gameObject.AddComponent<EffectMesh>();
            geometry.SpawnOnStart=MRUK.RoomFilter.None;
            geometry.Labels=MRUKAnchor.SceneLabels.FLOOR|MRUKAnchor.SceneLabels.WALL_FACE|MRUKAnchor.SceneLabels.TABLE|MRUKAnchor.SceneLabels.GLOBAL_MESH;
            geometry.Colliders=false;geometry.CastShadow=false;
            geometry.HideMesh=true;
            geometry.MeshMaterial=new Material(Resources.Load<Shader>("WorkspaceRoomScan"));
            geometry.BarycentricCoordinatesEnabled=true;
            CreateInstructions(rig.centerEyeAnchor);
            float until=Time.realtimeSinceStartup+15;
            while(!OVRPlugin.initialized && Time.realtimeSinceStartup<until) yield return null;
#if UNITY_ANDROID && !UNITY_EDITOR
            if(!UnityEngine.Android.Permission.HasUserAuthorizedPermission(OVRPermissionsRequester.ScenePermission))
            {
                state="Allow spatial data access to load your saved room";
                UnityEngine.Android.Permission.RequestUserPermission(OVRPermissionsRequester.ScenePermission);
                until=Time.realtimeSinceStartup+45;
                while(!UnityEngine.Android.Permission.HasUserAuthorizedPermission(OVRPermissionsRequester.ScenePermission)
                    && Time.realtimeSinceStartup<until) yield return null;
            }
#endif
            LoadSaved();
        }
        void CreateInstructions(Transform eye)
        {
            var panel=new GameObject("Room setup instructions",typeof(RectTransform),typeof(Canvas),typeof(RoundedGlassImage));
            panel.transform.SetParent(eye,false);panel.transform.localPosition=new Vector3(0,0,1.2f);
            panel.transform.localScale=Vector3.one*.001f;
            panel.GetComponent<Canvas>().renderMode=RenderMode.WorldSpace;
            panel.GetComponent<RectTransform>().sizeDelta=new Vector2(950,230);
            GlassTheme.StylePanel(panel.GetComponent<Image>());panel.AddComponent<GlassRoot>();
            var text=new GameObject("Instructions",typeof(RectTransform),typeof(Text));text.transform.SetParent(panel.transform,false);
            text.GetComponent<RectTransform>().sizeDelta=new Vector2(910,215);
            instructions=text.GetComponent<Text>();instructions.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            instructions.fontSize=28;instructions.alignment=TextAnchor.MiddleCenter;instructions.color=Color.white;
            GlassTheme.StyleText(instructions);
        }
        public async void LoadSaved()
        {
            if(busy || room==null) return;busy=true;state="Loading saved Meta room…";
            loadSucceeded=false;HideRoomGeometry();geometry.DestroyMesh();displayedRoom=null;
            try
            {
                var result=await room.LoadSceneFromDevice(requestSceneCaptureIfNoDataFound:false,removeMissingRooms:true);
                if(this==null) return;
                loadSucceeded=result==MRUK.LoadDeviceResult.Success;
                state=loadSucceeded
                    ? "Saved room received · checking this location"
                    : "Saved room unavailable: "+result+" · X opens Meta setup";
                Debug.Log("QUEST_ROOM_SETUP load="+result+" rooms="+room.Rooms.Count+" physical_fit=UNVERIFIED");
            }
            catch(Exception error) {state="Room load failed: "+error.GetType().Name;Debug.LogException(error);}
            finally {busy=false;}
        }
        public async void Scan()
        {
            if(busy) return;
#if UNITY_ANDROID && !UNITY_EDITOR
            busy=true;state="Meta Space Setup is open · finish or cancel on the headset";
            loadSucceeded=false;HideRoomGeometry();geometry.DestroyMesh();displayedRoom=null;
            try
            {
                bool returned=await OVRScene.RequestSpaceSetup();
                if(this==null) return;
                // Meta reports success even on cancellation. Reload; do not declare scan success.
                Debug.Log("QUEST_ROOM_SETUP system_returned="+returned+" capture_success=NOT_INFERRED");
            }
            catch(Exception error) {state="Space Setup failed: "+error.GetType().Name;Debug.LogException(error);}
            finally {busy=false;}
            LoadSaved();
#else
            state="Space Setup requires the on-headset APK; Link cannot run it";
#endif
        }
        static bool AnchorTracked(MRUKAnchor anchor)
        {
            return anchor!=null && anchor.Anchor.TryGetComponent<OVRLocatable>(out var locatable)
                && locatable.TryGetSceneAnchorPose(out var pose) && pose.Position.HasValue && pose.Rotation.HasValue
                && pose.IsPositionTracked && pose.IsRotationTracked;
        }
        static bool HeadReady()
        {
            var head=InputDevices.GetDeviceAtXRNode(XRNode.Head);
            bool tracked=head.TryGetFeatureValue(CommonUsages.isTracked,out bool tracking)&&tracking;
            bool known=head.TryGetFeatureValue(CommonUsages.userPresence,out bool present);
            bool meta=OVRPlugin.initialized;
            bool worn=(known||meta)&&(!known||present)&&(!meta||OVRPlugin.userPresent);
            return Camera.main!=null && head.TryGetFeatureValue(CommonUsages.devicePosition,out Vector3 _)
                && head.TryGetFeatureValue(CommonUsages.deviceRotation,out Quaternion _)
                && HostScene.HeadsetAllowsPlacement(XRSettings.isDeviceActive,tracked,known||meta,worn,
                    meta&&OVRPlugin.hasVrFocus);
        }
        bool TrySelectCurrentRoom(out MRUKRoom selected,out string reason)
        {
            selected=null;reason="Waiting for worn, focused headset tracking";
            if(!HeadReady()) return false;
            reason="Saved room is not localized here · A reloads · X opens Meta setup";
            if(!room.IsWorldLockActive) return false;
            var eye=Camera.main.transform;
            var floors=new List<WorkspaceRoomLocalization.FloorCandidate>();
            double now=Time.realtimeSinceStartupAsDouble;
            // GetCurrentRoom can return the last/first room even when outside all
            // rooms. Require actual containment and one unique current room instead.
            foreach(var candidate in room.Rooms)
            {
                if(candidate==null || !candidate.IsLocal || candidate.Anchor.Uuid==Guid.Empty
                    || !candidate.IsPositionInRoom(eye.position,true)) continue;
                foreach(var floor in candidate.FloorAnchors)
                {
                    if(!AnchorTracked(floor)) continue;
                    var normal=floor.transform.forward;
                    if(normal.y<0) normal=-normal;
                    float? ceilingHeight=null;
                    foreach(var ceiling in candidate.CeilingAnchors)
                    {
                        if(!AnchorTracked(ceiling)) continue;
                        float height=Vector3.Dot(ceiling.transform.position-floor.transform.position,normal);
                        if(height>0 && (!ceilingHeight.HasValue || height<ceilingHeight.Value)) ceilingHeight=height;
                    }
                    floors.Add(new WorkspaceRoomLocalization.FloorCandidate {
                        Room=candidate.Anchor.Uuid,WorldPose=new Pose(floor.transform.position,floor.transform.rotation),
                        Boundary=floor.PlaneBoundary2D?.ToArray(),Tracked=true,SampleTime=now,CeilingHeight=ceilingHeight });
                }
            }
            if(!WorkspaceRoomLocalization.TrySelectRoom(floors,new Pose(eye.position,eye.rotation),true,now,
                out Guid current,out reason)) return false;
            selected=room.Rooms.Find(r=>r!=null && r.Anchor.Uuid==current);
            return selected!=null;
        }
        void LateUpdate()
        {
            if(busy || !loadSucceeded || room==null || geometry==null) {HideRoomGeometry();return;}
            try
            {
                if(!TrySelectCurrentRoom(out var selected,out string reason))
                {HideRoomGeometry();state=reason;return;}
                bool detailed=selected.GlobalMeshAnchor!=null;
                if(detailed && !AnchorTracked(selected.GlobalMeshAnchor))
                {HideRoomGeometry();state="Room mesh is not localized · A reloads";return;}
                if(displayedRoom!=selected || displayedDetailed!=detailed)
                {
                    HideRoomGeometry();geometry.DestroyMesh();
                    geometry.Labels=detailed ? MRUKAnchor.SceneLabels.GLOBAL_MESH
                        : MRUKAnchor.SceneLabels.FLOOR|MRUKAnchor.SceneLabels.WALL_FACE|MRUKAnchor.SceneLabels.TABLE;
                    geometry.MeshMaterial.SetFloat("_VertexBarycentric",detailed?1:0);
                    geometry.MeshMaterial.SetFloat("_WireAmount",detailed?1:0);
                    geometry.CreateMesh(selected);
                    displayedRoom=selected;displayedDetailed=detailed;
                    Debug.Log("QUEST_ROOM_SETUP current_room_selected=True detailed="+detailed+" physical_fit=UNVERIFIED");
                }
                geometry.HideMesh=false;
                state=(detailed?"Saved Meta reconstruction mesh":"Meta semantic planes/bounds · no detailed mesh supplied")
                    +"\nInspect its fit in passthrough";
            }
            catch(Exception error)
            {
                loadSucceeded=false;HideRoomGeometry();
                state="Room verification failed: "+error.GetType().Name+" · A reloads";
                Debug.LogWarning("QUEST_ROOM_SETUP localization unavailable "+error.GetType().Name);
            }
        }
        void Update()
        {
            if(instructions!=null) instructions.text="ROOM SETUP · Meta system scene\n"+state+
                "\nA: load saved room    X: scan / update    Y: finish\nAfter finishing, reconnect Link and Load saved room in the PC app";
            var left=InputDevices.GetDeviceAtXRNode(XRNode.LeftHand);var right=InputDevices.GetDeviceAtXRNode(XRNode.RightHand);
            right.TryGetFeatureValue(CommonUsages.primaryButton,out bool load);
            left.TryGetFeatureValue(CommonUsages.primaryButton,out bool scan);
            left.TryGetFeatureValue(CommonUsages.secondaryButton,out bool exit);
            if(load && !lastLoad) LoadSaved();if(scan && !lastScan) Scan();if(exit && !lastExit && !busy) Application.Quit();
            lastLoad=load;lastScan=scan;lastExit=exit;
        }
    }
}
