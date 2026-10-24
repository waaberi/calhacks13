using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using Meta.XR.MRUtilityKit;
using UnityEngine;
using UnityEngine.XR;

namespace SpatialModeling
{
    public sealed partial class WorkspaceSurfaces
    {
        bool referenceAuditStarted;
        [Serializable] public sealed class ReferenceAudit
        {
            public string loadResult, trackingOrigin;
            public bool originalCameraPreserved, proxyCamerasDisabled, worldLockActive;
            public Pose cameraWorld, unityHead, pluginHead, sdkHead, originWorld, proxyTrackingWorld;
            public Pose trackingTransform, rawTrackingTransform, floorRelative, stageRelative;
            public Matrix4x4 leftView, rightView, projection;
            public List<ReferenceAnchor> anchors=new List<ReferenceAnchor>();
            public List<ReferenceMesh> meshes=new List<ReferenceMesh>();
        }
        [Serializable] public sealed class ReferenceAnchor
        {
            public string id, labels;
            public bool coreTracked, mrukFound;
            public Pose coreTracking, coreWorld, officialSdkWorld, mrukWorld, mrukMappedWorld;
            public float sdkPositionDelta, sdkAngleDelta, mrukPositionDelta, mrukAngleDelta;
        }
        [Serializable] public sealed class ReferenceMesh
        {
            public string id, coreHash, mrukHash;
            public int coreTriangles, mrukTriangles;
            public bool expandedTrianglesIdentical;
        }
        void StartReferenceAuditOnce()
        {
            if(referenceAuditStarted || anchors.Count==0 || Camera.main==null) return;
            var path=Environment.GetEnvironmentVariable("CALHACKS_ROOM_REFERENCE_AUDIT");
            referenceAuditStarted=true;
            if(string.IsNullOrEmpty(path)) return;
            // Diagnostic only. Do not present the physically failed overlay as a new fix.
            ShowDetected=false;RefreshVisuals();
            StartCoroutine(ReferenceAuditRoutine(path));
        }
        IEnumerator ReferenceAuditRoutine(string path)
        {
            var original=Camera.main;
            OVRCameraRig proxy=null;MRUK service=null;
            try
            {
                if(OVRCameraRig.Instance!=null || MRUK.Instance!=null)
                    throw new InvalidOperationException("Reference audit requires no existing SDK rig/service");
                // SDK207 explicitly supports another main rendering camera with this flag.
                // Only this independent reference rig's tracking space can be world-locked.
                var rigObject=new GameObject("Room audit SDK reference poses");rigObject.SetActive(false);
                proxy=rigObject.AddComponent<OVRCameraRig>();proxy.disableEyeAnchorCameras=true;
                rigObject.SetActive(true);
                foreach(var camera in proxy.GetComponentsInChildren<Camera>(true))
                {camera.enabled=false;camera.tag="Untagged";}
                var dataObject=new GameObject("Room audit MRUK data only");dataObject.SetActive(false);
                service=dataObject.AddComponent<MRUK>();service.EnableWorldLock=true;
                service.SceneSettings=new MRUK.MRUKSettings {LoadSceneOnStartup=false,DataSource=MRUK.SceneDataSource.Device};
                dataObject.SetActive(true);
            }
            catch(Exception error) {Debug.LogWarning("ROOM_REFERENCE_AUDIT setup_failed="+error.GetType().Name+" "+error.Message);}
            if(proxy==null || service==null) yield break;
            var load=service.LoadSceneFromDevice(requestSceneCaptureIfNoDataFound:false);
            float until=Time.realtimeSinceStartup+30;
            while(!load.IsCompleted && Time.realtimeSinceStartup<until) yield return null;
            if(!load.IsCompleted || load.IsFaulted || load.IsCanceled)
            {Debug.LogWarning("ROOM_REFERENCE_AUDIT load_failed_or_timeout");yield break;}
            // Take a bounded set of spatial-reference samples. This is not a frame-rate test.
            for(int sample=0;sample<4;sample++)
            {
                yield return new WaitForEndOfFrame();
                try
                {
                    var audit=CaptureReferenceAudit(original,proxy,service,load.Result.ToString());
                    var target=sample==0?path:Path.Combine(Path.GetDirectoryName(path),Path.GetFileNameWithoutExtension(path)+"-"+sample+".json");
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    File.WriteAllText(target,JsonUtility.ToJson(audit,true));
                    Debug.Log("ROOM_REFERENCE_AUDIT captured sample="+sample+" anchors="+audit.anchors.Count+
                        " camera_preserved="+audit.originalCameraPreserved+" proxy_cameras_disabled="+audit.proxyCamerasDisabled+
                        " sdk_max_m="+audit.anchors.Max(a=>a.sdkPositionDelta)+" mruk_max_m="+audit.anchors.Max(a=>a.mrukPositionDelta));
                }
                catch(Exception error) {Debug.LogWarning("ROOM_REFERENCE_AUDIT capture_failed="+error.GetType().Name+" "+error.Message);yield break;}
                yield return new WaitForSeconds(.5f);
            }
        }
        ReferenceAudit CaptureReferenceAudit(Camera original,OVRCameraRig proxy,MRUK service,string loadResult)
        {
            var result=new ReferenceAudit {loadResult=loadResult,trackingOrigin=OVRPlugin.GetTrackingOriginType().ToString(),
                originalCameraPreserved=Camera.main==original && original.enabled,
                proxyCamerasDisabled=proxy.GetComponentsInChildren<Camera>(true).All(c=>!c.enabled),
                worldLockActive=service.IsWorldLockActive,cameraWorld=PoseOf(original.transform),
                originWorld=Origin!=null?PoseOf(Origin):Pose.identity,proxyTrackingWorld=PoseOf(proxy.trackingSpace),
                leftView=original.GetStereoViewMatrix(Camera.StereoscopicEye.Left),
                rightView=original.GetStereoViewMatrix(Camera.StereoscopicEye.Right),projection=original.projectionMatrix};
            if(!result.originalCameraPreserved || !result.proxyCamerasDisabled)
                throw new InvalidOperationException("Reference-only camera invariant failed");
            var head=InputDevices.GetDeviceAtXRNode(XRNode.Head);
            head.TryGetFeatureValue(CommonUsages.devicePosition,out Vector3 position);
            head.TryGetFeatureValue(CommonUsages.deviceRotation,out Quaternion rotation);
            result.unityHead=new Pose(position,rotation);
            result.pluginHead=UnityPose(OVRPlugin.GetNodePose(OVRPlugin.Node.Head,OVRPlugin.Step.Render));
            OVRNodeStateProperties.GetNodeStatePropertyVector3(XRNode.Head,NodeStatePropertyType.Position,OVRPlugin.Node.Head,OVRPlugin.Step.Render,out position);
            OVRNodeStateProperties.GetNodeStatePropertyQuaternion(XRNode.Head,NodeStatePropertyType.Orientation,OVRPlugin.Node.Head,OVRPlugin.Step.Render,out rotation);
            result.sdkHead=new Pose(position,rotation);
            result.trackingTransform=UnityPose(OVRPlugin.GetCurrentTrackingTransformPose());
            result.rawTrackingTransform=UnityPose(OVRPlugin.GetTrackingTransformRawPose());
            result.floorRelative=UnityPose(OVRPlugin.GetTrackingTransformRelativePose(OVRPlugin.TrackingOrigin.FloorLevel));
            result.stageRelative=UnityPose(OVRPlugin.GetTrackingTransformRelativePose(OVRPlugin.TrackingOrigin.Stage));
            var reference=service.Rooms.SelectMany(r=>r.Anchors).GroupBy(a=>a.Anchor.Uuid).ToDictionary(g=>g.Key,g=>g.First());
            foreach(var item in anchors)
            {
                if(!item.Locatable.TryGetSceneAnchorPose(out var pose) || !pose.Position.HasValue || !pose.Rotation.HasValue) continue;
                var entry=new ReferenceAnchor {id=item.Anchor.Uuid.ToString(),coreTracked=pose.IsPositionTracked&&pose.IsRotationTracked,
                    coreTracking=new Pose(pose.Position.Value,pose.Rotation.Value)};
                entry.coreWorld=WorkspaceInteraction.ToWorldPose(Origin,entry.coreTracking);
                var official=new OVRPose {position=entry.coreTracking.position,orientation=entry.coreTracking.rotation}.ToWorldSpacePose(original);
                entry.officialSdkWorld=new Pose(official.position,official.orientation);
                entry.sdkPositionDelta=Vector3.Distance(entry.coreWorld.position,entry.officialSdkWorld.position);
                entry.sdkAngleDelta=Quaternion.Angle(entry.coreWorld.rotation,entry.officialSdkWorld.rotation);
                if(reference.TryGetValue(item.Anchor.Uuid,out var mruk))
                {
                    entry.mrukFound=true;entry.labels=mruk.Label.ToString();entry.mrukWorld=PoseOf(mruk.transform);
                    var local=new Pose(proxy.trackingSpace.InverseTransformPoint(mruk.transform.position),Quaternion.Inverse(proxy.trackingSpace.rotation)*mruk.transform.rotation);
                    entry.mrukMappedWorld=WorkspaceInteraction.ToWorldPose(Origin,local);
                    entry.mrukPositionDelta=Vector3.Distance(entry.coreWorld.position,entry.mrukMappedWorld.position);
                    entry.mrukAngleDelta=Quaternion.Angle(entry.coreWorld.rotation,entry.mrukMappedWorld.rotation);
                    var core=scanMeshes.Find(m=>m.Anchor.Anchor.Uuid==item.Anchor.Uuid);
                    if(core!=null && mruk.Mesh!=null)
                    {
                        var mesh=new ReferenceMesh {id=entry.id,coreTriangles=core.Mesh.triangles.Length/3,mrukTriangles=mruk.Mesh.triangles.Length/3,
                            coreHash=ExpandedMeshHash(core.Mesh),mrukHash=ExpandedMeshHash(mruk.Mesh)};
                        mesh.expandedTrianglesIdentical=mesh.coreHash==mesh.mrukHash;result.meshes.Add(mesh);
                    }
                }
                result.anchors.Add(entry);
            }
            return result;
        }
        static Pose PoseOf(Transform value)=>new Pose(value.position,value.rotation);
        static Pose UnityPose(OVRPlugin.Posef value) {var pose=value.ToOVRPose();return new Pose(pose.position,pose.orientation);}
        static string ExpandedMeshHash(Mesh mesh)
        {
            var points=mesh.vertices;var indices=mesh.triangles;
            using(var bytes=new MemoryStream())
            {
                using(var writer=new BinaryWriter(bytes,System.Text.Encoding.UTF8,true))
                    foreach(var i in indices) {writer.Write(points[i].x);writer.Write(points[i].y);writer.Write(points[i].z);}
                using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(bytes.ToArray())).Replace("-","");
            }
        }
    }
}
