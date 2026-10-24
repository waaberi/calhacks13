using System;
using System.Collections;
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
        string state="Starting Meta room setup";
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
            var panel=new GameObject("Room setup instructions",typeof(RectTransform),typeof(Canvas),typeof(Image));
            panel.transform.SetParent(eye,false);panel.transform.localPosition=new Vector3(0,0,1.2f);
            panel.transform.localScale=Vector3.one*.001f;
            panel.GetComponent<Canvas>().renderMode=RenderMode.WorldSpace;
            panel.GetComponent<RectTransform>().sizeDelta=new Vector2(950,230);
            panel.GetComponent<Image>().color=new Color(.01f,.025f,.04f,.94f);
            var text=new GameObject("Instructions",typeof(RectTransform),typeof(Text));text.transform.SetParent(panel.transform,false);
            text.GetComponent<RectTransform>().sizeDelta=new Vector2(910,215);
            instructions=text.GetComponent<Text>();instructions.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            instructions.fontSize=28;instructions.alignment=TextAnchor.MiddleCenter;instructions.color=Color.white;
        }
        public async void LoadSaved()
        {
            if(busy || room==null) return;busy=true;state="Loading saved Meta room…";
            try
            {
                var result=await room.LoadSceneFromDevice(requestSceneCaptureIfNoDataFound:false);
                if(this==null) return;
                geometry.DestroyMesh();
                bool detailed=room.Rooms.Exists(r=>r.GlobalMeshAnchor!=null);
                geometry.Labels=detailed ? MRUKAnchor.SceneLabels.GLOBAL_MESH
                    : MRUKAnchor.SceneLabels.FLOOR|MRUKAnchor.SceneLabels.WALL_FACE|MRUKAnchor.SceneLabels.TABLE;
                geometry.MeshMaterial.SetFloat("_VertexBarycentric",detailed?1:0);
                geometry.MeshMaterial.SetFloat("_WireAmount",detailed?1:0);
                geometry.CreateMesh();
                state=result==MRUK.LoadDeviceResult.Success
                    ? (detailed?"Saved Meta reconstruction mesh":"Meta semantic planes/bounds · no detailed mesh supplied")+"\nInspect its fit in passthrough"
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
