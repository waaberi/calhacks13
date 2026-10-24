using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Meta.XR;
using UnityEngine;
using UnityEngine.XR;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features;

namespace SpatialModeling
{
    public sealed partial class WorkspaceSurfaces
    {
        // Opt-in local evidence only. This reads existing spaces; it never creates,
        // recenters, changes tracking origin, enables MRUK or changes a transform.
        bool roomSpaceProbeConfigured, roomSpaceProbeFinished;
        string roomSpaceProbePath;
        float roomSpaceProbeNext;
        readonly RoomSpaceProbeEvidence roomSpaceProbe = new RoomSpaceProbeEvidence();
        OpenXRNativeFuncs.xrLocateSpace roomSpaceProbeLocate;

        [Serializable] sealed class RoomSpaceProbeEvidence
        {
            public string purpose = "Compare existing scene anchors against the actual Unity AppSpace";
            public string error;
            public List<RoomSpaceProbeSample> samples = new List<RoomSpaceProbeSample>();
        }
        [Serializable] sealed class RoomSpaceProbeSample
        {
            public float realtime;
            public string utc, appSpace, ovrAppSpace, instance, predictedDisplayTime, trackingOrigin;
            public bool xrActive, headTracked, inputPresenceKnown, inputPresent, metaPresent, vrFocused;
            public bool allowRecentering;
            public Pose cameraWorld, unityHead, metaHead, sceneTrackingWorld, rawTrackingTransform;
            public Pose eyeToCurrent, floorToCurrent, stageToCurrent;
            public bool worldLockOffsetAvailable, worldLockOffsetActive;
            public Pose worldLockOffsetRaw, worldLockOffsetUnity;
            public string worldLockOffsetError;
            public List<RoomSpaceProbeAnchor> anchors = new List<RoomSpaceProbeAnchor>();
        }
        [Serializable] sealed class RoomSpaceProbeAnchor
        {
            public string id, kind, handle;
            public bool wrapperSceneLocated, wrapperScenePositionTracked, wrapperSceneRotationTracked;
            public Pose wrapperScene;
            public List<RoomSpaceProbePose> origins = new List<RoomSpaceProbePose>();
            public RoomSpaceProbePose directAppSpace;
            public bool wrapperDirectComparable;
            public float wrapperDirectMetres, wrapperDirectDegrees;
        }
        [Serializable] sealed class RoomSpaceProbePose
        {
            public string origin, result, flags;
            public bool positionValid, rotationValid, positionTracked, rotationTracked;
            public Pose rawOpenXr, sceneUnity;
        }

        // Access the existing loader's function-pointer chain. No instance of this
        // class is created or registered as an OpenXR feature.
        sealed class ExistingOpenXREntryPoint : OpenXRFeature
        {
            public static IntPtr GetExistingProcAddress() => xrGetInstanceProcAddr;
        }

        public void ProbeRoomSpacesOnce()
        {
            if (roomSpaceProbeFinished) return;
            if (!roomSpaceProbeConfigured)
            {
                roomSpaceProbeConfigured = true;
                roomSpaceProbePath = Environment.GetEnvironmentVariable("CALHACKS_ROOM_SPACE_PROBE");
                if (string.IsNullOrWhiteSpace(roomSpaceProbePath))
                { roomSpaceProbeFinished = true; return; }
            }
            if (Time.realtimeSinceStartup < roomSpaceProbeNext || loading || anchors.Count == 0) return;
            try
            {
                var camera = Camera.main;
                var head = InputDevices.GetDeviceAtXRNode(XRNode.Head);
                bool tracked = head.TryGetFeatureValue(CommonUsages.isTracked, out bool value) && value;
                bool presenceKnown = head.TryGetFeatureValue(CommonUsages.userPresence, out bool present);
                if (camera == null || !XRSettings.isDeviceActive || !OVRPlugin.initialized || !tracked
                    || !OVRPlugin.userPresent || !OVRPlugin.hasVrFocus || (presenceKnown && !present)) return;
                if (!MetaXRFeature.TryGet(out var feature) || (ulong)feature.AppSpace == 0) return;

                if (roomSpaceProbeLocate == null)
                {
                    var pointer = ExistingOpenXREntryPoint.GetExistingProcAddress();
                    if (pointer == IntPtr.Zero) throw new InvalidOperationException("OpenXR loader entry point unavailable");
                    var getProc = Marshal.GetDelegateForFunctionPointer<OpenXRNativeFuncs.xrGetInstanceProcAddr>(pointer);
                    var bound = OpenXRNativeFuncs.GetInstanceDelegate(getProc, feature.Instance, "xrLocateSpace", out roomSpaceProbeLocate);
                    if (!bound.IsSuccess() || roomSpaceProbeLocate == null)
                        throw new InvalidOperationException("xrLocateSpace unavailable: " + bound);
                }

                var time = XrTime.PredictedDisplayTime;
                head.TryGetFeatureValue(CommonUsages.devicePosition, out Vector3 position);
                head.TryGetFeatureValue(CommonUsages.deviceRotation, out Quaternion rotation);
                var sample = new RoomSpaceProbeSample
                {
                    realtime = Time.realtimeSinceStartup,
                    utc = DateTime.UtcNow.ToString("o"),
                    appSpace = ((ulong)feature.AppSpace).ToString(), instance = ((ulong)feature.Instance).ToString(),
                    predictedDisplayTime = time.Value.ToString(), trackingOrigin = OVRPlugin.GetTrackingOriginType().ToString(),
                    xrActive = XRSettings.isDeviceActive, headTracked = tracked,
                    inputPresenceKnown = presenceKnown, inputPresent = present,
                    metaPresent = OVRPlugin.userPresent, vrFocused = OVRPlugin.hasVrFocus,
                    allowRecentering = OpenXRSettings.AllowRecentering,
                    cameraWorld = new Pose(camera.transform.position, camera.transform.rotation),
                    unityHead = new Pose(position, rotation),
                    metaHead = ProbePose(OVRPlugin.GetNodePose(OVRPlugin.Node.Head, OVRPlugin.Step.Render)),
                    sceneTrackingWorld = sceneTrackingWorld,
                    rawTrackingTransform = ProbePose(OVRPlugin.GetTrackingTransformRawPose()),
                    eyeToCurrent = ProbePose(OVRPlugin.GetTrackingTransformRelativePose(OVRPlugin.TrackingOrigin.EyeLevel)),
                    floorToCurrent = ProbePose(OVRPlugin.GetTrackingTransformRelativePose(OVRPlugin.TrackingOrigin.FloorLevel)),
                    stageToCurrent = ProbePose(OVRPlugin.GetTrackingTransformRelativePose(OVRPlugin.TrackingOrigin.Stage))
                };
                // OVRPlugin's internal getter is the existing handle passed to MRUK;
                // reading it lets evidence detect disagreement with Unity's feature.
                var appSpaceGetter = typeof(OVRPlugin).GetMethod("GetAppSpace", BindingFlags.Static | BindingFlags.NonPublic);
                sample.ovrAppSpace = appSpaceGetter?.Invoke(null, null)?.ToString();
                ProbeExistingWorldLockOffset(sample);

                int count = Math.Min(anchors.Count, 64);
                for (int i = 0; i < count; i++)
                {
                    var item = anchors[i];
                    // Core exposes poses publicly but keeps the existing XrSpace
                    // handle internal. Reflection reads that handle; it creates none.
                    var handleProperty = typeof(OVRAnchor).GetProperty("Handle", BindingFlags.Instance | BindingFlags.NonPublic);
                    if (handleProperty == null) throw new MissingMemberException("OVRAnchor.Handle");
                    ulong anchorHandle = (ulong)handleProperty.GetValue(item.Anchor);
                    var entry = new RoomSpaceProbeAnchor
                    { id = item.Anchor.Uuid.ToString(), kind = item.Kind, handle = anchorHandle.ToString() };
                    entry.wrapperSceneLocated = item.Locatable.TryGetSceneAnchorPose(out var scene)
                        && scene.Position.HasValue && scene.Rotation.HasValue;
                    if (entry.wrapperSceneLocated)
                    {
                        entry.wrapperScene = new Pose(scene.Position.Value, scene.Rotation.Value);
                        entry.wrapperScenePositionTracked = scene.IsPositionTracked;
                        entry.wrapperSceneRotationTracked = scene.IsRotationTracked;
                    }
                    foreach (var origin in new[] { OVRPlugin.TrackingOrigin.EyeLevel,
                        OVRPlugin.TrackingOrigin.FloorLevel, OVRPlugin.TrackingOrigin.Stage })
                    {
                        bool located = OVRPlugin.TryLocateSpace(anchorHandle, origin, out var raw, out var flags);
                        entry.origins.Add(new RoomSpaceProbePose
                        {
                            origin = origin.ToString(), result = located.ToString(), flags = flags.ToString(),
                            positionValid = flags.IsPositionValid(), rotationValid = flags.IsOrientationValid(),
                            positionTracked = flags.IsPositionTracked(), rotationTracked = flags.IsOrientationTracked(),
                            rawOpenXr = ProbeRawPose(raw), sceneUnity = ProbeScenePose(raw)
                        });
                    }

                    var location = new XrSpaceLocation { Type = XrSpaceLocation.StructureType };
                    var result = roomSpaceProbeLocate((XrSpace)anchorHandle, feature.AppSpace, time, ref location);
                    var rawPose = new OVRPlugin.Posef
                    {
                        Position = new OVRPlugin.Vector3f { x = location.Pose.Position.X, y = location.Pose.Position.Y, z = location.Pose.Position.Z },
                        Orientation = new OVRPlugin.Quatf { x = location.Pose.Orientation.X, y = location.Pose.Orientation.Y,
                            z = location.Pose.Orientation.Z, w = location.Pose.Orientation.W }
                    };
                    // XrSpaceLocationFlags are OpenXR's low four VALID/TRACKED bits.
                    ulong bits = (ulong)location.LocationFlags;
                    entry.directAppSpace = new RoomSpaceProbePose
                    {
                        origin = "UnityAppSpace", result = result.ToString(), flags = location.LocationFlags.ToString(),
                        rotationValid = (bits & 1) != 0, positionValid = (bits & 2) != 0,
                        rotationTracked = (bits & 4) != 0, positionTracked = (bits & 8) != 0,
                        rawOpenXr = ProbeRawPose(rawPose), sceneUnity = ProbeScenePose(rawPose)
                    };
                    entry.wrapperDirectComparable = result.IsSuccess() && entry.wrapperSceneLocated
                        && entry.directAppSpace.positionValid && entry.directAppSpace.rotationValid;
                    if (entry.wrapperDirectComparable)
                    {
                        entry.wrapperDirectMetres = Vector3.Distance(entry.wrapperScene.position, entry.directAppSpace.sceneUnity.position);
                        entry.wrapperDirectDegrees = Quaternion.Angle(entry.wrapperScene.rotation, entry.directAppSpace.sceneUnity.rotation);
                    }
                    sample.anchors.Add(entry);
                }
                roomSpaceProbe.samples.Add(sample);
                roomSpaceProbeNext = Time.realtimeSinceStartup + .5f;
                if (roomSpaceProbe.samples.Count >= 3) FinishRoomSpaceProbe();
            }
            catch (Exception error)
            {
                roomSpaceProbe.error = error.GetType().Name + ": " + error.Message;
                FinishRoomSpaceProbe();
            }
        }

        static Pose ProbeRawPose(OVRPlugin.Posef raw) => new Pose(
            new Vector3(raw.Position.x, raw.Position.y, raw.Position.z),
            new Quaternion(raw.Orientation.x, raw.Orientation.y, raw.Orientation.z, raw.Orientation.w));
        static Pose ProbePose(OVRPlugin.Posef raw)
        { var converted = raw.ToOVRPose(); return new Pose(converted.position, converted.orientation); }
        static Pose ProbeScenePose(OVRPlugin.Posef raw) => new Pose(
            new Vector3(raw.Position.x, raw.Position.y, -raw.Position.z),
            new Quaternion(-raw.Orientation.z, raw.Orientation.w, -raw.Orientation.x, raw.Orientation.y));

        static void ProbeExistingWorldLockOffset(RoomSpaceProbeSample sample)
        {
            try
            {
                var native = typeof(Meta.XR.MRUtilityKit.MRUK).Assembly.GetType("Meta.XR.MRUtilityKit.MRUKNativeFuncs");
                var field = native?.GetField("GetWorldLockOffset", BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
                var getter = field?.GetValue(null) as Delegate;
                sample.worldLockOffsetAvailable = getter != null;
                if (getter == null) return;
                object[] args = { Pose.identity };
                sample.worldLockOffsetActive = (bool)getter.DynamicInvoke(args);
                sample.worldLockOffsetRaw = (Pose)args[0];
                var p = sample.worldLockOffsetRaw;
                // MRUK.Update uses FlipZ for this offset, without scene-anchor Y180.
                sample.worldLockOffsetUnity = new Pose(new Vector3(p.position.x, p.position.y, -p.position.z),
                    new Quaternion(-p.rotation.x, -p.rotation.y, p.rotation.z, p.rotation.w));
            }
            catch (Exception error) { sample.worldLockOffsetError = error.GetType().Name + ": " + error.Message; }
        }
        void FinishRoomSpaceProbe()
        {
            roomSpaceProbeFinished = true; // No retry after any export or native failure.
            try
            {
                var fullPath = Path.GetFullPath(roomSpaceProbePath);
                Directory.CreateDirectory(Path.GetDirectoryName(fullPath));
                File.WriteAllText(fullPath, JsonUtility.ToJson(roomSpaceProbe, true));
                Debug.Log("WORKSPACE_ROOM_SPACE_PROBE samples=" + roomSpaceProbe.samples.Count
                    + " error=" + (roomSpaceProbe.error ?? "none") + " created_spaces=0 changed_tracking=False");
            }
            catch (Exception error) { Debug.LogWarning("WORKSPACE_ROOM_SPACE_PROBE export failed " + error.GetType().Name); }
        }
    }
}
