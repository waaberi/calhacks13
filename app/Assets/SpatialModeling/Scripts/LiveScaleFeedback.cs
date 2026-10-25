using System;
using System.Globalization;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Read-only world-space feedback from an acknowledged native live update.
    public sealed class LiveScaleFeedback : IDisposable
    {
        GameObject root;
        Text text;
        public bool Visible { get; private set; }
        public string Label { get; private set; }="";
        public Vector3 Factors { get; private set; }=Vector3.one;
        public bool Acknowledged { get; private set; }
        public void Begin(){Visible=true;Acknowledged=false;Factors=Vector3.one;Label="Scale ×1.00 · Waiting for Blender";}
        public void Accept(JObject parameters)
        {
            if(!Visible||!(parameters?["scale"] is JArray scale)||scale.Count!=3)return;
            for(int i=0;i<3;i++){double value=(double)scale[i];if(double.IsNaN(value)||double.IsInfinity(value))return;}
            Factors=new Vector3((float)scale[0],(float)scale[1],(float)scale[2]);Acknowledged=true;Label="Scale "+Format(Factors);
        }
        public void ShowDisplayScale(Vector3 factors)
        {Visible=true;Acknowledged=true;Factors=factors;Label="Display scale "+Format(factors).Replace("Blender applied","VR view only");}
        static string Factor(float value)=>value.ToString("0.00####",CultureInfo.InvariantCulture);
        public static string Format(Vector3 factors)
        {
            bool uniform=Mathf.Abs(factors.x-factors.y)<.000001f&&Mathf.Abs(factors.x-factors.z)<.000001f;
            string direction;
            if(factors.x<0||factors.y<0||factors.z<0)direction="mirrored";
            else if(factors.x>1.000001f||factors.y>1.000001f||factors.z>1.000001f)
                direction=factors.x<.999999f||factors.y<.999999f||factors.z<.999999f?"axis scale":"larger";
            else direction=factors.x<.999999f||factors.y<.999999f||factors.z<.999999f?"smaller":"original size";
            return (uniform?"×"+Factor(factors.x):"X ×"+Factor(factors.x)+"   Y ×"+Factor(factors.y)+"   Z ×"+Factor(factors.z))
                +"\n"+direction+" · Blender applied";
        }
        public void Draw(Vector3 contact,Camera camera)
        {
            if(!Visible)return;Ensure();root.SetActive(true);text.text=Label;
            Vector3 up=camera!=null?camera.transform.up:Vector3.up;
            Vector3 right=camera!=null?camera.transform.right:Vector3.right;
            root.transform.position=contact+up*.10f+right*.10f;
            if(camera!=null)root.transform.rotation=Quaternion.LookRotation(root.transform.position-camera.transform.position,camera.transform.up);
            float distance=camera!=null?Vector3.Distance(camera.transform.position,contact):1;
            root.transform.localScale=Vector3.one*Mathf.Clamp(distance*.0007f,.0007f,.0018f);
        }
        void Ensure()
        {
            if(root!=null)return;
            root=new GameObject("Live native scale multiplier",typeof(RectTransform),typeof(Canvas));
            var canvas=root.GetComponent<Canvas>();canvas.renderMode=RenderMode.WorldSpace;canvas.overrideSorting=true;canvas.sortingOrder=350;
            root.GetComponent<RectTransform>().sizeDelta=new Vector2(660,100);
            var content=new GameObject("Acknowledged scale",typeof(RectTransform),typeof(Text));content.transform.SetParent(root.transform,false);
            var rect=content.GetComponent<RectTransform>();rect.anchorMin=Vector2.zero;rect.anchorMax=Vector2.one;rect.offsetMin=rect.offsetMax=Vector2.zero;
            text=content.GetComponent<Text>();text.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");text.fontSize=32;text.fontStyle=FontStyle.Bold;
            text.alignment=TextAnchor.MiddleCenter;text.color=Color.white;text.raycastTarget=false;text.horizontalOverflow=HorizontalWrapMode.Overflow;
            content.AddComponent<Outline>().effectColor=new Color(0,0,0,.95f);
        }
        public void Hide(){Visible=false;Acknowledged=false;Factors=Vector3.one;Label="";if(root!=null)root.SetActive(false);}
        public void Dispose(){Hide();if(root!=null){if(Application.isPlaying)UnityEngine.Object.Destroy(root);else UnityEngine.Object.DestroyImmediate(root);}root=null;}
    }
}
