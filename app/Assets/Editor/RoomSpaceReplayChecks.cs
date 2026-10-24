using System;
using System.Collections.Generic;
using System.IO;
using SpatialModeling;
using UnityEngine;

// The oracle is xrLocateSpace(anchor, actual Unity AppSpace), captured independently
// of OVRPlugin.TryLocateSpace's requested origin. Private room data stays local.
public static class RoomSpaceReplayChecks
{
    const float PositionTolerance = .001f;
    const float AngleTolerance = .05f;
    [Serializable] sealed class Capture
    {
        public string error;
        public List<Sample> samples;
    }
    [Serializable] sealed class Sample
    {
        public string appSpace, ovrAppSpace, trackingOrigin;
        public bool xrActive, headTracked, metaPresent, vrFocused;
        public Pose sceneTrackingWorld, currentAppSpaceWorld, floorToCurrent;
        public List<Anchor> anchors;
    }
    [Serializable] sealed class Anchor
    {
        public string id;
        public bool wrapperSceneLocated, wrapperScenePositionTracked, wrapperSceneRotationTracked;
        public Pose wrapperScene;
        public NativePose directAppSpace;
    }
    [Serializable] sealed class NativePose
    {
        public string origin, result;
        public bool positionValid, rotationValid, positionTracked, rotationTracked;
        public Pose sceneUnity;
    }
    static void Check(bool value, string message)
    { if (!value) throw new Exception("Room space replay: " + message); }
    static Pose Inverse(Pose pose)
    {
        var inverse = Quaternion.Inverse(pose.rotation);
        return new Pose(inverse * -pose.position, inverse);
    }
    static Matrix4x4 Matrix(Pose pose) => Matrix4x4.TRS(pose.position, pose.rotation, Vector3.one);
    static Pose IndependentWorldPose(Pose currentToWorld, Pose directInCurrent)
        => new Pose(Matrix(currentToWorld).MultiplyPoint3x4(directInCurrent.position),
            currentToWorld.rotation * directInCurrent.rotation);
    static float AngularDifference(Quaternion a, Quaternion b)
    {
        // Normalize the dot in double precision: float quaternion norm error must
        // not consume a sub-tenth-degree tolerance in recorded native evidence.
        double dot = (double)a.x*b.x + (double)a.y*b.y + (double)a.z*b.z + (double)a.w*b.w;
        double aa = (double)a.x*a.x + (double)a.y*a.y + (double)a.z*a.z + (double)a.w*a.w;
        double bb = (double)b.x*b.x + (double)b.y*b.y + (double)b.z*b.z + (double)b.w*b.w;
        if (aa <= 0 || bb <= 0) return float.PositiveInfinity;
        return (float)(Math.Acos(Math.Min(1, Math.Abs(dot)/Math.Sqrt(aa*bb))) * 360 / Math.PI);
    }
    static bool Fits(Pose actual, Pose expected)
        => Vector3.Distance(actual.position, expected.position) <= PositionTolerance
            && AngularDifference(actual.rotation, expected.rotation) <= AngleTolerance;

    public static void Run()
    {
        var path = Environment.GetEnvironmentVariable("CALHACKS_ROOM_SPACE_REPLAY");
        if (string.IsNullOrWhiteSpace(path))
        {
            Debug.Log("ROOM_SPACE_REPLAY_CHECKS skipped: no private native-AppSpace capture supplied");
            return;
        }
        Check(File.Exists(path), "native AppSpace capture must be readable");
        var capture = JsonUtility.FromJson<Capture>(File.ReadAllText(path));
        Check(capture != null && string.IsNullOrEmpty(capture.error), "native probe completed without an error");
        Check(capture.samples != null && capture.samples.Count == 3, "all three independent native samples are required");

        var boundaries = new Dictionary<Guid, WorkspaceSurfaces.AnchorEvidence>();
        var roomPath = Environment.GetEnvironmentVariable("CALHACKS_ROOM_REPLAY");
        bool checkBoundaries = !string.IsNullOrWhiteSpace(roomPath);
        if (checkBoundaries)
        {
            Check(File.Exists(roomPath), "recorded boundary capture must be readable");
            var room = JsonUtility.FromJson<WorkspaceSurfaces.RoomEvidence>(File.ReadAllText(roomPath));
            Check(room != null && room.anchors != null, "boundary capture has anchors");
            foreach (var anchor in room.anchors)
            {
                Check(Guid.TryParse(anchor.id, out var id), "boundary anchor has a valid UUID");
                Check(!boundaries.ContainsKey(id), "boundary anchor UUID is unique");
                boundaries.Add(id, anchor);
            }
        }

        int nativeCases = 0, worldCases = 0, boundaryPoints = 0, boundaryMatches = 0;
        int omittedRejected = 0, inverseRejected = 0, doubledRejected = 0;
        float maxPosition = 0, maxAngle = 0, maxBoundary = 0;
        foreach (var sample in capture.samples)
        {
            Check(sample.xrActive && sample.headTracked && sample.metaPresent && sample.vrFocused,
                "native sample was taken while XR was active, tracked, worn and VR-focused");
            Check(!string.IsNullOrEmpty(sample.appSpace) && sample.appSpace != "0"
                && sample.appSpace == sample.ovrAppSpace, "native and Unity AppSpace handles agree");
            Check(sample.trackingOrigin == "FloorLevel", "recorded regression exercises the FloorLevel/AppSpace mismatch");
            Check(sample.anchors != null && sample.anchors.Count == 11, "all eleven recorded anchors are retained");
            var ids = new HashSet<Guid>();
            foreach (var anchor in sample.anchors)
            {
                Check(Guid.TryParse(anchor.id, out var id) && ids.Add(id), "sample anchor UUIDs are valid and unique");
                Check(anchor.wrapperSceneLocated && anchor.wrapperScenePositionTracked && anchor.wrapperSceneRotationTracked,
                    "wrapper scene pose is located and tracked");
                var direct = anchor.directAppSpace;
                Check(direct != null && direct.origin == "UnityAppSpace" && direct.result == "Success"
                    && direct.positionValid && direct.rotationValid && direct.positionTracked && direct.rotationTracked,
                    "independent direct AppSpace pose succeeded with all four valid/tracked flags");
                nativeCases++;

                // Actual captured camera mapping, then an arbitrary translated,
                // rotated world frame. Expected poses come from the independent
                // native AppSpace oracle, not from the wrapper pose or relative getter.
                var capturedCurrent=Quaternion.Dot(sample.currentAppSpaceWorld.rotation,sample.currentAppSpaceWorld.rotation)>.5f
                    ? sample.currentAppSpaceWorld : sample.sceneTrackingWorld;
                var worldFrames = new[] { capturedCurrent,
                    new Pose(new Vector3(3.4f, 1.1f, -2.7f), Quaternion.Euler(17, 113, -8)) };
                foreach (var currentToWorld in worldFrames)
                {
                    var frame = WorkspaceSurfaces.ComposeRoomTrackingFrame(currentToWorld, sample.floorToCurrent);
                    var actual = WorkspaceSurfaces.SceneToWorld(frame, anchor.wrapperScene);
                    var expected = IndependentWorldPose(currentToWorld, direct.sceneUnity);
                    float positionError = Vector3.Distance(actual.position, expected.position);
                    float angleError = AngularDifference(actual.rotation, expected.rotation);
                    maxPosition = Mathf.Max(maxPosition, positionError); maxAngle = Mathf.Max(maxAngle, angleError);
                    Check(Fits(actual, expected), "production frame conversion matches the independent native AppSpace pose");
                    worldCases++;

                    // Negative controls prove this capture detects the original
                    // omission and either common direction/count regression.
                    var omitted = WorkspaceSurfaces.SceneToWorld(currentToWorld, anchor.wrapperScene);
                    var invertedFrame = WorkspaceSurfaces.ComposeRoomTrackingFrame(currentToWorld, Inverse(sample.floorToCurrent));
                    var inverted = WorkspaceSurfaces.SceneToWorld(invertedFrame, anchor.wrapperScene);
                    var doubledFrame = WorkspaceSurfaces.ComposeRoomTrackingFrame(frame, sample.floorToCurrent);
                    var doubled = WorkspaceSurfaces.SceneToWorld(doubledFrame, anchor.wrapperScene);
                    if (!Fits(omitted, expected)) omittedRejected++;
                    if (!Fits(inverted, expected)) inverseRejected++;
                    if (!Fits(doubled, expected)) doubledRejected++;

                    if (!checkBoundaries) continue;
                    Check(boundaries.TryGetValue(id, out var geometry), "boundary and native captures match by anchor UUID");
                    boundaryMatches++;
                    if (geometry.boundary == null) continue;
                    var independent = Matrix(currentToWorld) * Matrix(direct.sceneUnity);
                    foreach (var corner in geometry.boundary)
                    {
                        var local = new Vector3(corner.x, corner.y, 0);
                        var actualCorner = actual.position + actual.rotation * local;
                        var expectedCorner = independent.MultiplyPoint3x4(local);
                        float error = Vector3.Distance(actualCorner, expectedCorner);
                        maxBoundary = Mathf.Max(maxBoundary, error); boundaryPoints++;
                        Check(error <= PositionTolerance, "actual boundary point follows the same corrected native AppSpace pose");
                    }
                }
            }
        }
        Check(nativeCases == 33 && worldCases == 66, "all 33 tracked native anchor cases pass in both world frames");
        Check(omittedRejected == worldCases && inverseRejected == worldCases && doubledRejected == worldCases,
            "omitted, inverted and doubled conversions are rejected in every case");
        if (checkBoundaries)
            Check(boundaryMatches == worldCases && boundaryPoints > 0, "UUID-matched actual boundary points were exercised");
        Debug.Log("ROOM_SPACE_REPLAY_CHECKS PASS native_anchor_cases=" + nativeCases + " world_cases=" + worldCases
            + " boundary_points=" + boundaryPoints + " max_position_m=" + maxPosition + " max_angle_deg=" + maxAngle
            + " max_boundary_m=" + maxBoundary + " omitted_rejected=" + omittedRejected
            + " inverse_rejected=" + inverseRejected + " doubled_rejected=" + doubledRejected + " physical_fit=UNVERIFIED");
    }
}
