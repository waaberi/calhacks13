using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Informational only: no raycaster, collider, input binding or native writer.
    public sealed class ToolAvailabilityPopup : IDisposable
    {
        public const string UnsupportedTitle = "This feature isn't available yet in 3D";
        public const string BlockedTitle = "This edit isn't available in the current selection";
        const string Guidance = "Use the Blender 2D view to continue. This attempt will not be committed. If a live preview started, wait for Blender to finish cancelling it.";
        const float Width = 800, MaximumHeight = 560, Padding = 28, WorldScale = .00085f;
        readonly List<string> pages = new List<string>();
        GameObject root;
        Text text;
        Pose anchor;
        string signature = "";
        int page;
        float lastShown, pageUntil;
        bool disposed;
        public bool Visible { get; private set; }
        public bool Unsupported { get; private set; }
        public string Title { get; private set; } = "";
        public string ToolName { get; private set; } = "";
        public string Reason { get; private set; } = "";
        public string DisplayedText => text != null ? text.text : "";
        public string DisplayedReason => pages.Count>0 ? pages[page] : "";
        public int ShowCount { get; private set; }
        public int PageCount => pages.Count;
        public int CurrentPage => page;
        public float NextPageAt => pageUntil;
        public Pose WorldPose => root != null ? new Pose(root.transform.position,root.transform.rotation) : anchor;
        public Vector2 PanelSize => root != null ? root.GetComponent<RectTransform>().rect.size : Vector2.zero;
        public float MeasuredTextHeight => text != null ? Measure(text.text) : 0;
        public bool TextFits => root != null && MeasuredTextHeight <= PanelSize.y-2*Padding+.5f;
        public GameObject VisualRoot => root;
        public bool IsDisposed => disposed;
        public ToolAvailabilityPopup(Transform owner) { }

        public static string FriendlyToolName(string nativeTool)
        {
            if(string.IsNullOrWhiteSpace(nativeTool))return "Blender tool";
            int dot=nativeTool.LastIndexOf('.');
            return CultureInfo.InvariantCulture.TextInfo.ToTitleCase(nativeTool.Substring(dot+1).Replace('_',' ').Trim());
        }
        static string Clean(string value)
            => Regex.Replace(Regex.Replace(value??"",@"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"," "),@"[ \t]+"," ").Trim();
        string Content(string reason,bool pageHint=false)
            => Title+"\n\n"+ToolName+"\n"+reason+"\n\n"+Guidance
                +(pageHint?"\nPage 999/999 · continues automatically":"");
        float Measure(string value)
        {
            var settings=text.GetGenerationSettings(new Vector2(Width-2*Padding,0));
            settings.verticalOverflow=VerticalWrapMode.Overflow;
            return text.cachedTextGeneratorForLayout.GetPreferredHeight(value,settings)/text.pixelsPerUnit;
        }
        bool Fits(string reason,bool hint) => Measure(Content(reason,hint)) <= MaximumHeight-2*Padding;

        public bool Show(bool unsupported,string nativeTool,string reason,Camera camera,float now)
        {
            if(disposed||camera==null)return false;
            string cleanReason=Clean(reason);
            if(cleanReason.Length==0)cleanReason="Choose the required native tool, mode and selection in Blender before trying again.";
            string next=(unsupported?"unsupported|":"blocked|")+nativeTool+"|"+cleanReason;
            if(Visible&&signature==next&&now-lastShown<1.25f)return false;
            Ensure();Unsupported=unsupported;Title=unsupported?UnsupportedTitle:BlockedTitle;
            ToolName=FriendlyToolName(nativeTool);Reason=cleanReason;signature=next;lastShown=now;ShowCount++;
            text.fontSize=Mathf.RoundToInt(28*GlassTheme.TextScale);
            while(text.fontSize>20&&!Fits(Reason,false))text.fontSize--;
            pages.Clear();
            if(Fits(Reason,false))pages.Add(Reason);
            else
            {
                string current="";
                foreach(Match match in Regex.Matches(Reason,@"\S+\s*"))
                {
                    string remaining=match.Value;
                    if(current.Length>0&&!Fits(current+remaining,true)){pages.Add(current.Trim());current="";}
                    while(!Fits(remaining,true))
                    {
                        int low=1,high=remaining.Length;
                        while(low<high){int middle=(low+high+1)/2;if(Fits(remaining.Substring(0,middle),true))low=middle;else high=middle-1;}
                        pages.Add(remaining.Substring(0,low));remaining=remaining.Substring(low);
                    }
                    current+=remaining;
                }
                if(current.Length>0)pages.Add(current.Trim());
            }
            anchor=new Pose(camera.transform.TransformPoint(new Vector3(0,-.025f,1.15f)),camera.transform.rotation);
            root.transform.SetPositionAndRotation(anchor.position,anchor.rotation);
            root.transform.localScale=Vector3.one*WorldScale;
            Visible=true;root.SetActive(true);page=0;ShowPage(now);return true;
        }
        void ShowPage(float now)
        {
            text.text=Content(pages[page])+(pages.Count>1?"\nPage "+(page+1)+"/"+pages.Count+" · continues automatically":"");
            root.GetComponent<RectTransform>().sizeDelta=new Vector2(Width,Mathf.Clamp(Mathf.Ceil(Measure(text.text))+2*Padding,180,MaximumHeight));
            pageUntil=now+Mathf.Clamp(6+text.text.Length/35f,8,14);
        }
        public void Tick(float now)
        {
            if(!Visible||disposed)return;
            root.transform.SetPositionAndRotation(anchor.position,anchor.rotation);
            root.transform.localScale=Vector3.one*WorldScale;
            while(Visible&&now>=pageUntil)
            {if(page+1<pages.Count){page++;ShowPage(pageUntil);}else Hide();}
        }
        void Ensure()
        {
            if(root!=null)return;
            root=new GameObject("Direct tool availability",typeof(RectTransform),typeof(Canvas),typeof(CanvasGroup),typeof(RoundedGlassImage));
            // The adapter owns disposal. A separate world root avoids inherited
            // XR/workspace scale, shear or motion changing physical text bounds.
            root.transform.localScale=Vector3.one*WorldScale;
            var canvas=root.GetComponent<Canvas>();canvas.renderMode=RenderMode.WorldSpace;canvas.overrideSorting=true;canvas.sortingOrder=3000;
            var group=root.GetComponent<CanvasGroup>();group.blocksRaycasts=false;group.interactable=false;
            var background=root.GetComponent<RoundedGlassImage>();GlassTheme.StylePanel(background);background.color=new Color(.15f,.075f,.09f,.99f);background.raycastTarget=false;
            var label=new GameObject("Tool availability text",typeof(RectTransform),typeof(Text));label.transform.SetParent(root.transform,false);
            var rect=label.GetComponent<RectTransform>();rect.anchorMin=Vector2.zero;rect.anchorMax=Vector2.one;rect.offsetMin=Vector2.one*Padding;rect.offsetMax=-Vector2.one*Padding;
            text=label.GetComponent<Text>();text.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");text.fontSize=28;text.lineSpacing=1.1f;
            text.color=GlassTheme.Ink;text.alignment=TextAnchor.UpperLeft;text.supportRichText=false;text.raycastTarget=false;
            text.horizontalOverflow=HorizontalWrapMode.Wrap;text.verticalOverflow=VerticalWrapMode.Overflow;
            root.SetActive(false);
        }
        public void Hide(){Visible=false;if(root!=null)root.SetActive(false);}
        public void Dispose()
        {
            if(disposed)return;Hide();disposed=true;
            if(root!=null){if(Application.isPlaying)UnityEngine.Object.Destroy(root);else UnityEngine.Object.DestroyImmediate(root);}
            root=null;text=null;
        }
    }
}
