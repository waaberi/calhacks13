using System;
using System.Collections.Generic;
using SpatialModeling;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

public static class GlassEventRaycastChecks
{
    static void Check(bool value,string reason){if(!value)throw new Exception("GLASS_EVENT_RAYCAST: "+reason);}
    public static void Run()
    {
        var cameraObject=new GameObject("glass EventSystem regression camera",typeof(Camera));
        var camera=cameraObject.GetComponent<Camera>();camera.transform.position=Vector3.zero;
        var target=new RenderTexture(640,480,24);camera.targetTexture=target;target.Create();
        var events=new GameObject("glass EventSystem regression",typeof(EventSystem));var system=events.GetComponent<EventSystem>();
        var root=new GameObject("glass registered canvas",typeof(RectTransform),typeof(Canvas),typeof(GlassCurvedCanvas),typeof(GlassGraphicRaycaster));
        var raycaster=root.GetComponent<GlassGraphicRaycaster>();
        var lifecycle=System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic;
        typeof(BaseRaycaster).GetMethod("OnEnable",lifecycle).Invoke(raycaster,null); // Editor fixture; real Player enables this automatically.
        try
        {
            root.transform.SetPositionAndRotation(new Vector3(0,0,2),Quaternion.identity);root.transform.localScale=Vector3.one*.001f;
            var canvas=root.GetComponent<Canvas>();canvas.renderMode=RenderMode.WorldSpace;canvas.worldCamera=camera;
            root.GetComponent<RectTransform>().sizeDelta=new Vector2(640,480);
            int clicked=0;var button=GlassTheme.Action(root.transform,"Actual curved action",Vector2.zero,new Vector2(300,80),()=>clicked++);
            root.GetComponent<GlassCurvedCanvas>().ApplyToChildren();Canvas.ForceUpdateCanvases();camera.Render();
            var registered=GraphicRegistry.GetGraphicsForCanvas(canvas);
            Check(registered.Count>0,"real uGUI registry contains canvas graphics");
            List<RaycastResult> Hit(Vector3 local)
            {
                var point=root.transform.TransformPoint(root.GetComponent<GlassCurvedCanvas>().Bend(local));
                var data=new PointerEventData(system){position=camera.WorldToScreenPoint(point),button=PointerEventData.InputButton.Left};
                var results=new List<RaycastResult>();system.RaycastAll(data,results);return results;
            }
            Debug.Log("GLASS_EVENT_FIXTURE registry="+registered.Count+" raycasters="+RaycasterManager.GetRaycasters().Contains(raycaster)+" depth="+button.GetComponent<Image>().depth+" cull="+button.GetComponent<Image>().canvasRenderer.cull);
            var hits=Hit(Vector3.zero);Check(hits.Exists(h=>h.gameObject==button.gameObject),"actual EventSystem traverses IndexedSet and hits curved button without exceptions");
            Check(!Hit(new Vector3(149,39,0)).Exists(h=>h.gameObject==button.gameObject),"transparent rounded corner cannot capture desktop input");
            var group=button.gameObject.AddComponent<CanvasGroup>();group.blocksRaycasts=false;
            Check(!Hit(Vector3.zero).Exists(h=>h.gameObject==button.gameObject),"CanvasGroup still blocks registered graphic");
            group.blocksRaycasts=true;button.gameObject.SetActive(false);
            Check(!Hit(Vector3.zero).Exists(h=>h.gameObject==button.gameObject),"inactive graphics do not receive events");
            button.gameObject.SetActive(true);Canvas.ForceUpdateCanvases();camera.Render();
            Check(Hit(Vector3.zero).Exists(h=>h.gameObject==button.gameObject),"reenabled graphics rejoin actual registry");
            ExecuteEvents.Execute(button.gameObject,new PointerEventData(system){button=PointerEventData.InputButton.Left},ExecuteEvents.pointerClickHandler);
            Check(clicked==1,"real Button click callback retained");
            Debug.Log("GLASS_EVENT_RAYCAST_CHECK PASS actual_EventSystem GraphicRegistry_IndexedSet center corner CanvasGroup inactive reenabled click no_native_input");
        }
        finally
        {
            typeof(BaseRaycaster).GetMethod("OnDisable",lifecycle).Invoke(raycaster,null);
            camera.targetTexture=null;target.Release();UnityEngine.Object.DestroyImmediate(target);
            UnityEngine.Object.DestroyImmediate(root);UnityEngine.Object.DestroyImmediate(events);UnityEngine.Object.DestroyImmediate(cameraObject);
        }
    }
}
