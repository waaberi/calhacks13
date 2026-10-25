using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace SpatialModeling
{
    // Inspection placement is local to this viewer. It never becomes a host command.
    public sealed class WorkspaceObjectView : MonoBehaviour
    {
        public string ObjectId { get; set; }
        public string NativeParentId { get; set; }
        public long Generation { get; set; }
        public Vector3 NativePosition { get; private set; }
        public Quaternion NativeRotation { get; private set; } = Quaternion.identity;
        public Vector3 NativeScale { get; private set; } = Vector3.one;
        public Vector3 PositionOffset { get; private set; }
        public Quaternion RotationOffset { get; private set; } = Quaternion.identity;
        public Vector3 ScaleOffset { get; private set; } = Vector3.one;
        public string LivePresentationId { get; private set; }
        public bool LivePresentationConflict { get; private set; }
        public long LivePresentationSequence { get; private set; } = -1;
        public int LivePresentationRebases { get; private set; }
        public Matrix4x4 NativeToDisplayMatrix => transform.localToWorldMatrix
            * Matrix4x4.TRS(NativePosition,NativeRotation,NativeScale).inverse;
        readonly List<GameObject> inspectionFrames = new List<GameObject>();
        Transform originalParent;
        string liveActor, livePhase;
        bool frameApproved;

        public sealed class ArrangementState
        {
            internal Transform Parent;
            internal Vector3 Position,Scale;
            internal Quaternion Rotation;
            internal readonly List<(Vector3 position,Quaternion rotation,Vector3 scale)> Frames = new List<(Vector3,Quaternion,Vector3)>();
        }

        public void SetNativePose(Vector3 position, Quaternion rotation, Vector3 scale)
        {
            if(!string.IsNullOrEmpty(LivePresentationId)&&!frameApproved)LivePresentationConflict=true;
            frameApproved=false;
            NativePosition = position;
            NativeRotation = rotation;
            NativeScale=scale;
            ApplyArrangement();
        }

        public void RememberArrangement()
        {
            PositionOffset = transform.localPosition - NativePosition;
            RotationOffset = transform.localRotation * Quaternion.Inverse(NativeRotation);
            ScaleOffset=Ratio(transform.localScale,NativeScale);
        }

        public void RestoreArrangement(Vector3 position, Quaternion rotation)
        {
            PositionOffset = position;
            RotationOffset = rotation;
            ApplyArrangement();
        }

        public void ResetArrangement()
        {
            ClearInspectionFrames();PositionOffset=Vector3.zero;RotationOffset=Quaternion.identity;ScaleOffset=Vector3.one;
            ApplyArrangement();
        }

        // A hierarchy is the exact product V0 * inverse(nativeTRS0). It retains
        // affine/sheared display mappings without lossyScale decomposition or
        // modifying native vertices, normals, topology or collider buffers.
        public void BeginLivePresentation(string editId,string actorId)
        {
            if(string.IsNullOrEmpty(editId)||LivePresentationId==editId)return;
            if(originalParent==null)originalParent=transform.parent;
            bool identityOffsets=PositionOffset.sqrMagnitude<1e-14f&&Quaternion.Angle(RotationOffset,Quaternion.identity)<.0001f
                &&(ScaleOffset-Vector3.one).sqrMagnitude<1e-12f;
            if(inspectionFrames.Count==0||!identityOffsets)
            {
                Transform parent=transform.parent;
                parent=Frame(parent,"Frozen inspection baseline",transform.localPosition,transform.localRotation,transform.localScale);
                parent=Frame(parent,"Native inverse scale",Vector3.zero,Quaternion.identity,Ratio(Vector3.one,NativeScale));
                parent=Frame(parent,"Native inverse rotation",Vector3.zero,Quaternion.Inverse(NativeRotation),Vector3.one);
                parent=Frame(parent,"Native inverse translation",-NativePosition,Quaternion.identity,Vector3.one);
                transform.SetParent(parent,false);
            }
            PositionOffset=Vector3.zero;RotationOffset=Quaternion.identity;ScaleOffset=Vector3.one;ApplyArrangement();
            LivePresentationId=editId;liveActor=actorId??"";LivePresentationSequence=-1;livePhase="";
            frameApproved=false;LivePresentationConflict=false;
        }
        Transform Frame(Transform parent,string name,Vector3 position,Quaternion rotation,Vector3 scale)
        {
            var obj=new GameObject(name);obj.transform.SetParent(parent,false);
            obj.transform.localPosition=position;obj.transform.localRotation=rotation;obj.transform.localScale=scale;
            inspectionFrames.Add(obj);return obj.transform;
        }
        public bool AcceptLiveEcho(JObject tag,string actorId)
        {
            if(string.IsNullOrEmpty(LivePresentationId))return false;
            if(tag==null||(string)tag["id"]!=LivePresentationId||(string)tag["actor_id"]!=liveActor||actorId!=liveActor)
            {LivePresentationConflict=true;return false;}
            long sequence=(long?)tag["sequence"]??-1;string phase=(string)tag["phase"]??"";
            bool terminal=phase=="committed"||phase=="cancelled"||phase=="conflict";
            if(sequence<LivePresentationSequence||(sequence==LivePresentationSequence&&(!terminal||phase==livePhase)))return false;
            LivePresentationSequence=sequence;livePhase=phase;frameApproved=true;return true;
        }
        public void EndLivePresentation(string editId,bool committed)
        {
            if(LivePresentationId!=editId)return;
            // The hierarchy already renders M0 * the final native pose. Rebase
            // once; delayed duplicate receipts cannot apply another correction.
            RememberArrangement();LivePresentationRebases++;
            LivePresentationId=null;liveActor=null;frameApproved=false;LivePresentationConflict=false;
        }
        public ArrangementState CaptureArrangementState()
        {
            var state=new ArrangementState { Parent=originalParent!=null?originalParent:transform.parent,
                Position=PositionOffset,Rotation=RotationOffset,Scale=ScaleOffset };
            foreach(var frame in inspectionFrames)if(frame!=null)
                state.Frames.Add((frame.transform.localPosition,frame.transform.localRotation,frame.transform.localScale));
            return state;
        }
        public void RestoreArrangementState(ArrangementState state)
        {
            if(state==null)return;ClearInspectionFrames();originalParent=state.Parent;transform.SetParent(state.Parent,false);
            Transform parent=state.Parent;
            foreach(var frame in state.Frames)parent=Frame(parent,"Restored inspection frame",frame.position,frame.rotation,frame.scale);
            transform.SetParent(parent,false);PositionOffset=state.Position;RotationOffset=state.Rotation;ScaleOffset=state.Scale;ApplyArrangement();
        }
        void ClearInspectionFrames()
        {
            if(inspectionFrames.Count==0)return;
            transform.SetParent(originalParent,false);
            for(int i=inspectionFrames.Count-1;i>=0;i--)if(inspectionFrames[i]!=null)
            { if(Application.isPlaying)Destroy(inspectionFrames[i]);else DestroyImmediate(inspectionFrames[i]); }
            inspectionFrames.Clear();LivePresentationId=null;LivePresentationConflict=false;frameApproved=false;
        }
        void OnDestroy()
        {
            // Detach before releasing the containers; renderer/collider lifetime
            // stays with this object and the existing HostScene owner.
            if(inspectionFrames.Count>0)transform.SetParent(null,false);
            for(int i=inspectionFrames.Count-1;i>=0;i--)if(inspectionFrames[i]!=null)
            { if(Application.isPlaying)Destroy(inspectionFrames[i]);else DestroyImmediate(inspectionFrames[i]); }
            inspectionFrames.Clear();
        }
        static Vector3 Ratio(Vector3 a,Vector3 b)=>new Vector3(Mathf.Abs(b.x)>1e-12f?a.x/b.x:1,
            Mathf.Abs(b.y)>1e-12f?a.y/b.y:1,Mathf.Abs(b.z)>1e-12f?a.z/b.z:1);

        void ApplyArrangement()
        {
            transform.localPosition = NativePosition + PositionOffset;
            transform.localRotation = RotationOffset * NativeRotation;
            transform.localScale=Vector3.Scale(NativeScale,ScaleOffset);
        }
    }
}
