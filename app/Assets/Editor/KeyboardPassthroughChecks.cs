using System;
using System.Collections.Generic;
using System.Linq;
using SpatialModeling;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering.Universal;

public static class KeyboardPassthroughChecks
{
    static void Check(bool value,string reason) { if(!value)throw new Exception("KEYBOARD_PASSTHROUGH: "+reason); }
    public static void Run()
    {
        var existing=new HashSet<GameObject>(Resources.FindObjectsOfTypeAll<GameObject>());
        var owner=new GameObject("inactive manual keyboard fixture");owner.SetActive(false);
        RenderTexture target=null;Texture2D pixels=null;Material opaque=null;
        var previous=RenderTexture.active;
        try
        {
            var keyboard=owner.AddComponent<KeyboardPassthrough>();
            var head=new Pose(new Vector3(1,1.65f,2),Quaternion.Euler(0,47,0));
            keyboard.UpdateAvailability(false,true,true,head,0);
            Check(!keyboard.Visible&&keyboard.Placement==null&&keyboard.State.Contains("unavailable"),"unsupported passthrough creates no fake or black window");
            keyboard.UpdateAvailability(true,true,true,head,1);
            Check(!keyboard.Visible,"fresh readiness does not immediately expose camera underlay");
            keyboard.UpdateAvailability(true,true,true,head,1.6);
            Check(keyboard.Visible,"existing real underlay plus fresh readiness displays manual window");
            var initial=KeyboardPassthrough.InitialPose(head);
            Check(Vector3.Distance(keyboard.Placement.position,initial.position)<.0001f,"initial window uses shared settled head space once");
            Check(Mathf.Abs(keyboard.Placement.up.y-1)<.0001f,"initial manual keyboard window is horizontal");
            var grip=keyboard.Placement.Find("Grip to align keyboard window");
            Physics.SyncTransforms();
            Check(keyboard.RaycastHandle(new Ray(grip.position+Vector3.up*.4f,Vector3.down),out var distance)&&distance>0,"actual handle collider permits accepted aim-grab integration");
            Check(!keyboard.RaycastHandle(new Ray(keyboard.Placement.position+Vector3.up*.4f,Vector3.down),out _),"clear window itself does not steal native input");
            keyboard.Placement.position+=Vector3.right*.12f;
            var arranged=keyboard.Placement.position;
            keyboard.UpdateAvailability(true,true,true,new Pose(head.position+Vector3.right,Quaternion.identity),2);
            Check(keyboard.Placement.position==arranged,"placed window stays stationary through head movement");
            keyboard.UpdateAvailability(true,false,true,head,3);Check(!keyboard.Visible,"session loss hides real-room window and handle");
            keyboard.UpdateAvailability(true,true,true,head,4);Check(!keyboard.Visible,"remount waits for new readiness interval");
            keyboard.UpdateAvailability(true,true,true,head,4.6);Check(keyboard.Visible&&keyboard.Placement.position==arranged,"fresh session restores same world placement");
            keyboard.SetRequested(false);Check(!keyboard.Visible,"OFF hides window immediately");
            keyboard.SetRequested(true);keyboard.UpdateAvailability(true,true,true,head,5);
            Check(keyboard.Visible&&keyboard.Placement.position==arranged,"ordinary toggle preserves manual alignment");

            // Render the actual alpha-writing shader through URP over opaque
            // foreground geometry. Zero RGBA must survive in the final target.
            keyboard.Placement.SetPositionAndRotation(Vector3.zero,Quaternion.identity);
            foreach(var transform in keyboard.Placement.GetComponentsInChildren<Transform>(true))transform.gameObject.layer=31;
            var blocker=GameObject.CreatePrimitive(PrimitiveType.Cube);blocker.layer=31;
            blocker.transform.position=new Vector3(0,.25f,0);blocker.transform.localScale=new Vector3(.85f,.2f,.7f);
            opaque=new Material(AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            blocker.GetComponent<Renderer>().sharedMaterial=opaque;
            var cameraObject=new GameObject("keyboard alpha camera",typeof(Camera));var camera=cameraObject.GetComponent<Camera>();
            camera.enabled=false;camera.cullingMask=1<<31;camera.orthographic=true;camera.orthographicSize=.45f;
            camera.transform.SetPositionAndRotation(Vector3.up,Quaternion.Euler(90,0,0));
            camera.nearClipPlane=.01f;camera.farClipPlane=4;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.7f,.1f,.1f,1);camera.allowHDR=false;
            camera.GetUniversalAdditionalCameraData().renderPostProcessing=false;
            target=new RenderTexture(128,128,24,RenderTextureFormat.ARGB32);target.Create();camera.targetTexture=target;
            camera.Render();RenderTexture.active=target;
            pixels=new Texture2D(128,128,TextureFormat.RGBA32,false);pixels.ReadPixels(new Rect(0,0,128,128),0,0);pixels.Apply();
            var middle=pixels.GetPixel(64,64);var outside=pixels.GetPixel(4,4);
            Check(middle.a<.01f&&middle.r<.01f&&middle.g<.01f&&middle.b<.01f,"actual keyboard shader punches zero RGBA through opaque foreground");
            Check(outside.a>.99f,"alpha punch is bounded to physical keyboard window");
            keyboard.InvalidatePlacement();
            Check(!keyboard.Requested&&!keyboard.Visible,"origin reset requires explicit re-placement rather than stale physical coordinates");
            keyboard.PlaceFromHead();keyboard.UpdateAvailability(true,true,true,head,8);keyboard.UpdateAvailability(true,true,true,head,8.6);
            Check(keyboard.Visible&&Vector3.Distance(keyboard.Placement.position,initial.position)<.0001f,"explicit replacement seeds fresh settled pose after origin reset");
            Debug.Log("KEYBOARD_PASSTHROUGH_CHECK PASS actual_gpu_zero_rgba_over_opaque bounded_window active_real_underlay_gate manual_handle stationary_alignment readiness_loss origin_reset_explicit_replacement no_camera_pixel_access");
        }
        finally
        {
            RenderTexture.active=previous;
            foreach(var go in Resources.FindObjectsOfTypeAll<GameObject>().Where(go=>!existing.Contains(go)).ToArray())if(go!=null)UnityEngine.Object.DestroyImmediate(go);
            if(target!=null){target.Release();UnityEngine.Object.DestroyImmediate(target);}
            if(pixels!=null)UnityEngine.Object.DestroyImmediate(pixels);
            if(opaque!=null)UnityEngine.Object.DestroyImmediate(opaque);
        }
    }
}
