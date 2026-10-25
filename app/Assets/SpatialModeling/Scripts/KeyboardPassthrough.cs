using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

namespace SpatialModeling
{
    // An explicitly manual window onto the existing real compositor underlay.
    // It neither recognizes nor tracks a laptop and never reads camera pixels.
    public sealed class KeyboardPassthrough : MonoBehaviour
    {
        public static KeyboardPassthrough Current { get; private set; }
        public Transform Placement => window;
        public bool Requested { get; private set; } = true;
        public bool Visible => window!=null&&window.gameObject.activeInHierarchy;
        public string State { get; private set; } = "Waiting for real room passthrough";
        Transform window,label;
        Collider handle;
        Material revealMaterial,frameMaterial;
        Mesh revealMesh;
        bool positioned;
        double readySince=-1;
        readonly List<XRInputSubsystem> subsystems=new List<XRInputSubsystem>();
        void Awake() { Current=this; }
        void OnEnable()
        {
            Current=this;
            SubsystemManager.GetSubsystems(subsystems);
            foreach(var subsystem in subsystems) subsystem.trackingOriginUpdated+=OriginChanged;
        }
        void OnDisable()
        {
            foreach(var subsystem in subsystems) subsystem.trackingOriginUpdated-=OriginChanged;
            subsystems.Clear();readySince=-1;
            if(window!=null)window.gameObject.SetActive(false);
            if(Current==this)Current=null;
        }
        void OriginChanged(XRInputSubsystem _) => InvalidatePlacement();
        public void InvalidatePlacement()
        {
            positioned=false;readySince=-1;
            if(window!=null)window.gameObject.SetActive(false);
            State="Tracking origin changed · place keyboard window again";
            // A changed origin requires explicit placement, never stale coordinates.
            Requested=false;
        }
        public void Toggle() => SetRequested(!Requested);
        public void SetRequested(bool value)
        {
            Requested=value;
            if(!value&&window!=null)window.gameObject.SetActive(false);
            State=value?"Waiting for real room passthrough":"Keyboard window off";
        }
        public void PlaceFromHead()
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            positioned=false;Requested=true;readySince=-1;
            if(window!=null)window.gameObject.SetActive(false);
            State="Waiting for worn, focused headset · then align window to your keyboard";
        }
        public static Pose InitialPose(Pose head)
        {
            var forward=Vector3.ProjectOnPlane(head.rotation*Vector3.forward,Vector3.up);
            if(forward.sqrMagnitude<.01f)forward=Vector3.forward;
            return new Pose(head.position+forward.normalized*.42f-Vector3.up*.65f,Quaternion.LookRotation(forward,Vector3.up));
        }
        // Kept separate so checks can exercise the exact runtime availability
        // admission without pretending a desktop fixture has real passthrough.
        public void UpdateAvailability(bool passthroughActive,bool headReady,bool placementReady,Pose settledHead,double now)
        {
            if(!Requested) { if(window!=null)window.gameObject.SetActive(false);return; }
            if(!passthroughActive||!headReady||!placementReady)
            {
                readySince=-1;
                if(window!=null)window.gameObject.SetActive(false);
                State=!passthroughActive?"Real keyboard unavailable · room passthrough is off or unavailable":"Keyboard hidden · waiting for worn, focused tracking";
                return;
            }
            if(readySince<0)readySince=now;
            if(now-readySince<.5) { State="Keyboard hidden · stabilizing fresh headset session";return; }
            if(window==null)CreateWindow();
            if(window==null) { State="Keyboard window shader unavailable";return; }
            if(!positioned)
            {
                var pose=InitialPose(settledHead);window.SetPositionAndRotation(pose.position,pose.rotation);
                window.localScale=Vector3.one;positioned=true;
            }
            window.gameObject.SetActive(true);
            State="Real keyboard window · manually align with grip · not automatic tracking";
        }
        void LateUpdate()
        {
            var room=FindFirstObjectByType<WorkspacePassthrough>();
            var scene=GetComponent<HostScene>()??FindFirstObjectByType<HostScene>();
            UpdateAvailability(room!=null&&room.Active,WorkspaceSurfaces.RoomHeadReady(),scene!=null&&scene.DisplayPlacementReady,
                scene!=null?scene.PlacementHeadPose:default,Time.realtimeSinceStartupAsDouble);
            if(label!=null&&Visible&&Camera.main!=null)
            {
                var forward=label.position-Camera.main.transform.position;
                if(forward.sqrMagnitude>.0001f)label.rotation=Quaternion.LookRotation(forward,Vector3.up);
            }
        }
        public bool IsPlacement(Transform value) => window!=null&&value==window;
        public bool RaycastHandle(Ray ray,out float distance)
        {
            distance=4;
            if(!Visible||handle==null||!handle.Raycast(ray,out var hit,4))return false;
            distance=hit.distance;return true;
        }
        void CreateWindow()
        {
            var shader=Resources.Load<Shader>("KeyboardPassthrough");
            if(shader==null)return;
            revealMaterial=new Material(shader);revealMaterial.SetColor("_Color",Color.clear);revealMaterial.renderQueue=4990;
            frameMaterial=new Material(shader);frameMaterial.SetColor("_Color",new Color(.18f,.9f,1,1));frameMaterial.renderQueue=4991;
            window=new GameObject("Real keyboard passthrough — manual alignment").transform;
            window.gameObject.SetActive(false);
            var surface=new GameObject("Real room alpha window",typeof(MeshFilter),typeof(MeshRenderer));surface.transform.SetParent(window,false);
            revealMesh=new Mesh { name="Keyboard manual 60x24cm window" };
            revealMesh.vertices=new[]{new Vector3(-.3f,0,-.12f),new Vector3(-.3f,0,.12f),new Vector3(.3f,0,.12f),new Vector3(.3f,0,-.12f)};
            revealMesh.triangles=new[]{0,1,2,0,2,3};revealMesh.RecalculateNormals();revealMesh.RecalculateBounds();
            surface.GetComponent<MeshFilter>().sharedMesh=revealMesh;surface.GetComponent<MeshRenderer>().sharedMaterial=revealMaterial;
            var frame=new GameObject("Visible manual window boundary",typeof(LineRenderer));frame.transform.SetParent(window,false);
            var line=frame.GetComponent<LineRenderer>();line.useWorldSpace=false;line.loop=true;line.positionCount=4;
            line.SetPositions(revealMesh.vertices);line.startWidth=line.endWidth=.004f;line.sharedMaterial=frameMaterial;
            var grip=GameObject.CreatePrimitive(PrimitiveType.Sphere);grip.name="Grip to align keyboard window";grip.transform.SetParent(window,false);
            grip.transform.localPosition=new Vector3(0,.015f,-.18f);grip.transform.localScale=Vector3.one*.05f;
            grip.GetComponent<Renderer>().sharedMaterial=frameMaterial;handle=grip.GetComponent<Collider>();
            label=new GameObject("Manual physical keyboard label",typeof(TextMesh)).transform;label.SetParent(window,false);
            label.localPosition=new Vector3(0,.035f,-.255f);
            var text=label.GetComponent<TextMesh>();text.text="REAL KEYBOARD · MANUAL WINDOW\nGrip cyan handle to align · two grips resize";
            text.fontSize=40;text.characterSize=.003f;text.anchor=TextAnchor.MiddleCenter;text.alignment=TextAlignment.Center;text.color=Color.white;
            Debug.Log("KEYBOARD_PASSTHROUGH window_created existing_real_underlay_only manual_alignment=true camera_pixels_read=false");
        }
        static void Release(Object value)
        {
            if(value==null)return;
            if(Application.isPlaying)Destroy(value);else DestroyImmediate(value);
        }
        void OnDestroy()
        {
            if(Current==this)Current=null;
            if(window!=null)Release(window.gameObject);
            Release(revealMesh);Release(revealMaterial);Release(frameMaterial);
        }
    }
}
