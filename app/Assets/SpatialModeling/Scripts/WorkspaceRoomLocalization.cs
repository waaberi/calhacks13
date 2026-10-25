using System;
using System.Collections.Generic;
using UnityEngine;

namespace SpatialModeling
{
    // Eligibility for using a saved room, not a claim that its physical fit passed.
    // The caller supplies fresh poses in one world frame and a worn/focused/tracked
    // headReady signal. Receipt of saved data or a singleton room is insufficient.
    public static class WorkspaceRoomLocalization
    {
        public struct FloorCandidate
        {
            public Guid Room;
            public Guid Anchor;
            public Pose WorldPose;
            // Actual Boundary2D vertices in the floor anchor's XY plane. No bounds fallback.
            public Vector2[] Boundary;
            public bool Tracked;
            // Same monotonic clock as now; stamp only a successful current pose read.
            public double SampleTime;
            // Optional measured floor-to-ceiling distance in metres, not a guessed height.
            public float? CeilingHeight;
        }

        public struct Limits
        {
            public float MinHeadHeight, MaxHeadHeight, MaxFloorTiltDegrees, EdgeTolerance;
            public double MaxPoseAge, FutureTolerance;
        }

        public static Limits DefaultLimits => new Limits
        {
            MinHeadHeight=.1f, MaxHeadHeight=2.75f, MaxFloorTiltDegrees=5,
            EdgeTolerance=.002f, MaxPoseAge=.25, FutureTolerance=.02
        };

        public static bool TrySelectRoom(IReadOnlyList<FloorCandidate> floors, Pose headWorld,
            bool headReady, double now, out Guid room, out string reason)
            => TrySelectRoom(floors,headWorld,headReady,now,DefaultLimits,out room,out reason);

        public static bool TrySelectRoom(IReadOnlyList<FloorCandidate> floors, Pose headWorld,
            bool headReady, double now, Limits limits, out Guid room, out string reason)
        {
            room=Guid.Empty;
            reason="Waiting for worn, focused headset tracking";
            if(!headReady || !Finite(headWorld) || !Finite(now)) return false;
            reason="Room localization limits invalid";
            if(!Valid(limits)) return false;
            reason="No saved room contains the headset";
            if(floors==null) return false;
            Guid selected=Guid.Empty;
            foreach(var floor in floors)
            {
                if(!ContainsHead(floor,headWorld.position,now,limits)) continue;
                if(selected!=Guid.Empty && selected!=floor.Room)
                { reason="Saved room match is ambiguous"; return false; }
                selected=floor.Room;
            }
            if(selected==Guid.Empty) return false;
            room=selected;
            reason="Headset is inside the saved room boundary";
            return true;
        }

        public static bool ContainsHead(FloorCandidate floor, Vector3 headWorld, double now, Limits limits)
        {
            if(floor.Room==Guid.Empty || !floor.Tracked || !Finite(floor.WorldPose)
                || !Finite(headWorld) || !Finite(now) || !Finite(floor.SampleTime) || !Valid(limits)) return false;
            double age=now-floor.SampleTime;
            if(age < -limits.FutureTolerance || age > limits.MaxPoseAge) return false;
            var rotation=floor.WorldPose.rotation.normalized;
            var normal=rotation*Vector3.forward;
            float vertical=Vector3.Dot(normal,Vector3.up);
            if(Mathf.Abs(vertical)<Mathf.Cos(limits.MaxFloorTiltDegrees*Mathf.Deg2Rad)) return false;
            if(vertical<0) normal=-normal;
            var delta=headWorld-floor.WorldPose.position;
            float height=Vector3.Dot(delta,normal);
            if(!Finite(height) || height<limits.MinHeadHeight || height>limits.MaxHeadHeight) return false;
            if(floor.CeilingHeight.HasValue)
            {
                float ceiling=floor.CeilingHeight.Value;
                if(!Finite(ceiling) || ceiling<=limits.MinHeadHeight || height>ceiling) return false;
            }
            var local=Quaternion.Inverse(rotation)*delta;
            return InsideActualBoundary(floor.Boundary,new Vector2(local.x,local.y),limits.EdgeTolerance);
        }
        // Continuity is allowed only for an independently verified room/floor
        // identity and a new successful containment test of that exact floor.
        // A persisted identity never substitutes for a current tracked pose.
        public static bool TrySelectRoomWithContinuity(IReadOnlyList<FloorCandidate> floors,Pose headWorld,
            bool headReady,double now,Guid verifiedRoom,Guid verifiedFloor,out Guid room,out string reason)
        {
            if(TrySelectRoom(floors,headWorld,headReady,now,out room,out reason))return true;
            if(reason!="Saved room match is ambiguous"||verifiedRoom==Guid.Empty||verifiedFloor==Guid.Empty)return false;
            foreach(var floor in floors)
                if(floor.Room==verifiedRoom&&floor.Anchor==verifiedFloor&&ContainsHead(floor,headWorld.position,now,DefaultLimits))
                {room=verifiedRoom;reason="Previously verified saved room contains the headset · overlapping room retained separately";return true;}
            return false;
        }

        // An unassigned mesh can only inherit a unique known room AFTER that room
        // has passed the same current headset/floor gate used for semantic surfaces.
        public static bool BelongsToRoom(Guid sourceRoom, Guid localizedRoom, Guid soleKnownRoom)
            => localizedRoom!=Guid.Empty && (sourceRoom==localizedRoom
                || (sourceRoom==Guid.Empty && soleKnownRoom==localizedRoom));

        public static bool InsideActualBoundary(Vector2[] boundary, Vector2 point, float edgeTolerance=.002f)
        {
            if(boundary==null || boundary.Length<3 || boundary.Length>16384
                || !Finite(point) || !Finite(edgeTolerance) || edgeTolerance<0) return false;
            double twiceArea=0;
            for(int i=0,j=boundary.Length-1;i<boundary.Length;j=i++)
            {
                if(!Finite(boundary[i])) return false;
                twiceArea+=(double)boundary[j].x*boundary[i].y-(double)boundary[i].x*boundary[j].y;
            }
            if(Math.Abs(twiceArea)<.0001) return false;
            bool inside=false;
            double toleranceSquared=(double)edgeTolerance*edgeTolerance;
            for(int i=0,j=boundary.Length-1;i<boundary.Length;j=i++)
            {
                var a=boundary[j];var b=boundary[i];var segment=b-a;
                double lengthSquared=(double)segment.x*segment.x+(double)segment.y*segment.y;
                double t=lengthSquared>0?Math.Max(0,Math.Min(1,
                    ((double)(point.x-a.x)*segment.x+(double)(point.y-a.y)*segment.y)/lengthSquared)):0;
                double dx=a.x+t*segment.x-point.x,dy=a.y+t*segment.y-point.y;
                if(dx*dx+dy*dy<=toleranceSquared) return true;
                if((a.y>point.y)!=(b.y>point.y)
                    && point.x<(double)(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x) inside=!inside;
            }
            return inside;
        }

        static bool Valid(Limits limits)
            => Finite(limits.MinHeadHeight) && Finite(limits.MaxHeadHeight)
                && limits.MinHeadHeight>0 && limits.MaxHeadHeight>limits.MinHeadHeight
                && Finite(limits.MaxFloorTiltDegrees) && limits.MaxFloorTiltDegrees>=0 && limits.MaxFloorTiltDegrees<45
                && Finite(limits.EdgeTolerance) && limits.EdgeTolerance>=0 && limits.EdgeTolerance<=.02f
                && Finite(limits.MaxPoseAge) && limits.MaxPoseAge>0
                && Finite(limits.FutureTolerance) && limits.FutureTolerance>=0 && limits.FutureTolerance<=.1;
        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
        static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
        static bool Finite(Vector2 value) => Finite(value.x) && Finite(value.y);
        static bool Finite(Vector3 value) => Finite(value.x) && Finite(value.y) && Finite(value.z);
        static bool Finite(Pose value)
        {
            var q=value.rotation;
            float norm=q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w;
            return Finite(value.position) && Finite(q.x) && Finite(q.y) && Finite(q.z) && Finite(q.w)
                && Finite(norm) && norm>.25f && norm<4;
        }
    }
}
