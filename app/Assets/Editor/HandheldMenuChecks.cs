using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using SpatialModeling;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

public static class HandheldMenuChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string reason) { if(!value) throw new Exception("HANDHELD_MENU: "+reason); }
    static void Invoke(object value,string method,params object[] args) => value.GetType().GetMethod(method,Private).Invoke(value,args);
    static Ray RayTo(TablePlacement table,RectTransform target)
    {
        var curve=table.Menu.GetComponent<GlassCurvedCanvas>();
        var flat=table.Menu.InverseTransformPoint(target.position);
        var point=table.Menu.TransformPoint(curve.Bend(flat));
        return new Ray(point-table.Menu.forward*.4f,table.Menu.forward);
    }
    public static void Run()
    {
        var existing=new HashSet<GameObject>(Resources.FindObjectsOfTypeAll<GameObject>());
        var owner=new GameObject("inactive handheld menu verification");owner.SetActive(false);
        try
        {
            var camera=new GameObject("handheld camera",typeof(Camera));camera.tag="MainCamera";
            var head=new Vector3(0,1.65f,0);camera.transform.position=head;
            var arrangement=owner.AddComponent<WorkspaceArrangement>();Invoke(arrangement,"Awake");
            var table=owner.AddComponent<TablePlacement>();
            var display=new GameObject("handheld display");display.transform.SetParent(owner.transform,false);
            table.Initialize(display.transform,AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            table.SeedFromHead(head,Vector3.forward);table.Place();
            var hand=new Pose(new Vector3(-.3f,1.15f,.3f),Quaternion.identity);
            table.UpdateLeftHandMenu(hand,head,true);
            var docked=table.Menu.localScale;
            Check(Mathf.Abs(table.Menu.GetComponent<RectTransform>().rect.width*docked.x/GlassTheme.TextScale-.352f*.55f)<.00001f,
                "docked menu is enlarged to 19.36cm at standard accessibility scale");
            Check(Vector3.Dot(table.Menu.forward,(table.Menu.position-head).normalized)>.999f,"docked menu faces wearer");
            var curve=table.Menu.GetComponent<GlassCurvedCanvas>();
            Check(curve!=null&&curve.Bend(new Vector3(320,0,0)).z<-10,"visible gentle curve reaches panel edges");
            foreach(var graphic in table.Menu.GetComponentsInChildren<Graphic>(true))
                Check(graphic.GetComponent<GlassCurveMesh>()!=null,"all text and controls bend with the menu");
            var actions=table.Menu.GetComponentsInChildren<TableAction>(true);
            Check(actions.Any(a=>a.name=="Surface detection: ON"),"surface detection is directly on the handheld arrange page");
            foreach(var action in actions)
            {
                int calls=0;var original=action.Click;action.Click=()=>calls++;
                var ray=RayTo(table,action.GetComponent<RectTransform>());
                Check(table.RaycastControls(ray,out float distance)&&distance>0,"curved action is discovered: "+action.name);
                Check(table.HoverController(ray,true)&&calls==1,"curved ray invokes exactly the rendered action: "+action.name);
                action.Click=original;
            }
            var surface=actions.Single(a=>a.name=="Surface detection: ON");
            Check(table.HoverController(RayTo(table,surface.GetComponent<RectTransform>()),true)&&!arrangement.AssistEnabled,
                "surface detection dispatches real assistance toggle");
            Check(table.Menu.GetComponentsInChildren<TableAction>(true).Any(a=>a.name=="Surface detection: OFF"),"toggle visibly reports new state");
            table.PinMenu();Check(Vector3.Distance(table.Menu.localScale,docked/TablePlacement.DockedMenuFactor)<.000001f,"pin expands to unchanged full size");
            var tablePose=new Pose(display.transform.position,display.transform.rotation);
            table.Menu.SetPositionAndRotation(new Vector3(.4f,1.4f,.8f),Quaternion.Euler(60,130,25));
            var position=table.Menu.position;var scale=table.Menu.localScale;
            table.FaceMenuTowardUser(head);
            Check(Vector3.Dot(table.Menu.forward,(position-head).normalized)>.999f,"held menu faces current wearer instead of controller wrist");
            Check(Vector3.Dot(table.Menu.right,Vector3.up)<.0001f,"held menu has no wrist roll");
            Check(table.Menu.position==position&&table.Menu.localScale==scale,"facing preserves accepted aim position and scale");
            var pinnedRotation=table.Menu.rotation;
            table.UpdateLeftHandMenu(hand,head+Vector3.right,true);
            Check(Quaternion.Angle(table.Menu.rotation,pinnedRotation)<.001f,"released world menu does not keep following the head");
            Check(display.transform.position==tablePose.position&&Quaternion.Angle(display.transform.rotation,tablePose.rotation)<.001f,"menu changes preserve model placement");
            table.DockMenu();table.UpdateLeftHandMenu(hand,head,true);
            Check(Vector3.Distance(table.Menu.localScale,docked)<.000001f,"return to left hand restores enlarged docked scale without repeated multiplication");
            var page=typeof(TablePlacement).GetNestedType("MenuPage",BindingFlags.NonPublic);
            Invoke(table,"ChangeMenu",Enum.Parse(page,"Settings"));
            Check(!table.Menu.GetComponentsInChildren<TableAction>(true).Any(a=>a.name.StartsWith("Surface help")||a.name.StartsWith("Surface detection")),"surface control moved out of Settings");
            Check(!table.Menu.GetComponentsInChildren<TableAction>(true).Any(a=>a.name.Contains("Physical keyboard")||a.name.Contains("keyboard window")),"rejected physical-keyboard window has no Settings control");
            Check(typeof(TablePlacement).Assembly.GetType("SpatialModeling.KeyboardPassthrough")==null,"physical-keyboard outline/handle/window cannot be constructed in the runtime");
            Check(Resources.Load<Shader>("KeyboardPassthrough")==null,"removed physical-keyboard alpha punch shader is not retained as a resource");
            Debug.Log("HANDHELD_MENU_CHECK PASS enlarged_readable_dock matched_curve_render_and_actual_ray_dispatch every_action direct_surface_toggle upright_held_facing anchored_release model_invariance");
        }
        finally
        {
            foreach(var go in Resources.FindObjectsOfTypeAll<GameObject>().Where(go=>!existing.Contains(go)).ToArray())
                if(go!=null) UnityEngine.Object.DestroyImmediate(go);
        }
    }
}
