using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Read-only help. Every key modifies this local string only; no native,
    // voice, network, history, focus, selection or editing API is referenced.
    public sealed class SearchableGuidePanel : IDisposable
    {
        public const int MaximumQueryLength=48, ResultsPerPage=3;
        const float Scale=.0007f;
        readonly List<Button> buttons=new List<Button>();
        readonly List<string> pages=new List<string>();
        GameObject root,view;
        Text body;
        Pose anchor;
        VrGuideArticle article;
        IReadOnlyList<VrGuideArticle> matches=Array.Empty<VrGuideArticle>();
        int resultPage,stepPage;
        public bool Visible { get; private set; }
        public string Query { get; private set; }="";
        public int ResultPage=>resultPage;
        public int ResultCount=>matches.Count;
        public int ResultPageCount=>Mathf.Max(1,(matches.Count+ResultsPerPage-1)/ResultsPerPage);
        public string ArticleId=>article?.Id;
        public int StepPage=>stepPage;
        public int StepPageCount=>pages.Count;
        public string PageText=>body!=null?body.text:"";
        public GameObject VisualRoot=>root;
        public IReadOnlyList<Button> Controls=>buttons;
        public Pose WorldPose=>anchor;
        public bool TextFits=>body==null||Measure(body,body.text)<=body.rectTransform.rect.height+.5f;
        public bool IsDisposed { get; private set; }

        public bool Open(Camera camera)
        {
            if(IsDisposed||camera==null)return false;
            if(Visible)return true;
            Ensure();anchor=new Pose(camera.transform.TransformPoint(new Vector3(0,-.015f,1.5f)),camera.transform.rotation);
            Visible=true;root.SetActive(true);article=null;RefreshSearch();Tick();return true;
        }
        public void Close(){Visible=false;if(root!=null)root.SetActive(false);}
        public void Tick()
        {
            if(!Visible||root==null)return;
            root.transform.SetPositionAndRotation(anchor.position,anchor.rotation);
            root.transform.localScale=Vector3.one*Scale*GlassTheme.TextScale;
        }
        public void Search(string value)
        {
            Query=new string((value??"").Where(c=>c==' '||c>='a'&&c<='z'||c>='A'&&c<='Z'||c>='0'&&c<='9').Take(MaximumQueryLength).ToArray());
            article=null;resultPage=0;if(root!=null)RefreshSearch();
        }
        public void Key(string key)
        {
            if(!Visible)return;
            if(key=="Backspace")Search(Query.Length>0?Query.Substring(0,Query.Length-1):"");
            else if(key=="Clear")Search("");
            else if(key=="Space")Search(Query+" ");
            else if(key?.Length==1&&(key[0]>='A'&&key[0]<='Z'||key[0]>='0'&&key[0]<='9'))Search(Query+key.ToLowerInvariant());
        }
        public void MoveResults(int delta)
        {if(article!=null)return;resultPage=Mathf.Clamp(resultPage+delta,0,ResultPageCount-1);RefreshSearch();}
        public bool Read(string id)
        {
            var selected=VrGuideCatalog.Articles.FirstOrDefault(item=>item.Id==id);if(selected==null)return false;
            article=selected;stepPage=0;RefreshArticle(true);return true;
        }
        public void MoveStep(int delta)
        {if(article==null)return;stepPage=Mathf.Clamp(stepPage+delta,0,pages.Count-1);RefreshArticle(false);}
        public void Back(){article=null;RefreshSearch();}
        static float Measure(Text label,string value)
        {
            var settings=label.GetGenerationSettings(new Vector2(label.rectTransform.rect.width,0));settings.verticalOverflow=VerticalWrapMode.Overflow;
            return label.cachedTextGeneratorForLayout.GetPreferredHeight(value,settings)/label.pixelsPerUnit;
        }
        void Ensure()
        {
            if(root!=null)return;
            root=new GameObject("Local searchable Guide",typeof(RectTransform),typeof(Canvas),typeof(RoundedGlassImage),typeof(GlassCurvedCanvas));
            root.GetComponent<RectTransform>().sizeDelta=new Vector2(980,900);
            var canvas=root.GetComponent<Canvas>();canvas.renderMode=RenderMode.WorldSpace;canvas.overrideSorting=true;canvas.sortingOrder=2500;
            root.GetComponent<GlassCurvedCanvas>().Radius=4200;
            GlassTheme.StylePanel(root.GetComponent<Image>());root.GetComponent<Image>().color=new Color(.09f,.12f,.16f,.98f);
        }
        void BeginView(string title)
        {
            if(view!=null){view.SetActive(false);Release(view);}buttons.Clear();body=null;
            view=new GameObject("Guide reading and local search",typeof(RectTransform));view.transform.SetParent(root.transform,false);
            view.GetComponent<RectTransform>().sizeDelta=new Vector2(980,900);
            Label(title,new Vector2(0,390),new Vector2(900,65),32);
        }
        Text Label(string value,Vector2 position,Vector2 size,int font=28)
        {
            var label=GlassTheme.Label(view.transform,value,position,size,font);label.supportRichText=false;
            label.horizontalOverflow=HorizontalWrapMode.Wrap;label.verticalOverflow=VerticalWrapMode.Overflow;return label;
        }
        Button Action(string name,string label,Vector2 position,Vector2 size,Action callback)
        {
            var button=GlassTheme.Action(view.transform,label,position,size,callback);button.name=name;
            button.navigation=new Navigation { mode=Navigation.Mode.None };
            foreach(var text in button.GetComponentsInChildren<Text>())text.supportRichText=false;
            button.GetComponent<Image>().raycastTarget=false;buttons.Add(button);return button;
        }
        void RefreshSearch()
        {
            matches=VrGuideCatalog.Search(Query);resultPage=Mathf.Clamp(resultPage,0,ResultPageCount-1);
            BeginView("Guide · instructions only");
            Action("Search field","Search: "+(Query.Length==0?"type using the local keys below":Query),new Vector2(0,315),new Vector2(900,74),()=>{});
            Label(matches.Count+" matching topics · page "+(resultPage+1)+" / "+ResultPageCount,new Vector2(0,260),new Vector2(900,34),24);
            for(int row=0;row<ResultsPerPage;row++)
            {
                int index=resultPage*ResultsPerPage+row;if(index>=matches.Count)break;
                var item=matches[index];Action("Read "+item.Id,item.Title,new Vector2(0,205-row*70),new Vector2(900,60),()=>Read(item.Id));
            }
            if(matches.Count==0)Label("No matching topics. Try a shorter keyword, such as move, plane or voice.",new Vector2(0,170),new Vector2(870,120),28);
            Action("Previous results","Previous topics",new Vector2(-230,-20),new Vector2(420,60),()=>MoveResults(-1));
            Action("Next results","Next topics",new Vector2(230,-20),new Vector2(420,60),()=>MoveResults(1));
            Label("Guide search keyboard · local only",new Vector2(0,-80),new Vector2(900,35),24);
            string[] rows={"1234567890","QWERTYUIOP","ASDFGHJKL","ZXCVBNM"};
            for(int row=0;row<rows.Length;row++)for(int column=0;column<rows[row].Length;column++)
            {string key=rows[row][column].ToString();Action("Local key "+key,key,new Vector2((column-(rows[row].Length-1)*.5f)*85,-125-row*55),new Vector2(76,46),()=>Key(key));}
            Action("Local Space","Space",new Vector2(-290,-350),new Vector2(260,54),()=>Key("Space"));
            Action("Local Backspace","Backspace",new Vector2(0,-350),new Vector2(280,54),()=>Key("Backspace"));
            Action("Local Clear","Clear search",new Vector2(290,-350),new Vector2(260,54),()=>Key("Clear"));
            Action("Close Guide","Close Guide",new Vector2(0,-415),new Vector2(440,54),Close);
            root.GetComponent<GlassCurvedCanvas>().ApplyToChildren();
        }
        void RefreshArticle(bool rebuildPages)
        {
            BeginView(article.Title);Label(article.Category,new Vector2(0,330),new Vector2(900,45),25);
            body=Label("",new Vector2(0,25),new Vector2(880,460),30);body.alignment=TextAnchor.UpperLeft;
            if(rebuildPages)
            {
                pages.Clear();
                for(int i=0;i<article.Steps.Length;i++)AddPages("Step "+(i+1)+" / "+article.Steps.Length+"\n\n"+article.Steps[i]);
                if(!string.IsNullOrWhiteSpace(article.Limitation))AddPages("Requirements and limits\n\n"+article.Limitation);
                if(pages.Count==0)pages.Add("Instructions are not available for this topic yet.");
            }
            body.text=pages[stepPage];
            Label("Reading page "+(stepPage+1)+" / "+pages.Count+" · no tutorial action runs",new Vector2(0,285),new Vector2(900,42),24);
            Action("Previous step","Previous step",new Vector2(-230,-285),new Vector2(420,64),()=>MoveStep(-1));
            Action("Next step","Next step",new Vector2(230,-285),new Vector2(420,64),()=>MoveStep(1));
            Action("Guide Back","Back to search",new Vector2(-230,-390),new Vector2(420,64),Back);
            Action("Close Guide","Close Guide",new Vector2(230,-390),new Vector2(420,64),Close);
            root.GetComponent<GlassCurvedCanvas>().ApplyToChildren();
        }
        void AddPages(string value)
        {
            string current="";
            foreach(string word in value.Split(new[]{' '},StringSplitOptions.None))
            {
                string next=current.Length==0?word:current+" "+word;
                if(current.Length>0&&Measure(body,next)>body.rectTransform.rect.height){pages.Add(current);current=word;}
                else current=next;
            }
            if(current.Length>0)pages.Add(current);
        }
        public bool Raycast(Ray ray,out float distance)
        {distance=0;return Visible&&root!=null&&root.activeInHierarchy&&GlassRaycast.Hit(root.GetComponent<RectTransform>(),ray,out distance,out _);}
        public bool Hover(Ray ray,bool click)
        {
            if(!Raycast(ray,out _))return false;
            Button selected=null;float nearest=float.PositiveInfinity;
            foreach(var button in buttons)
                if(button!=null&&button.gameObject.activeInHierarchy&&GlassRaycast.Hit(button.GetComponent<RectTransform>(),ray,out float distance,out _)&&distance<nearest)
                {nearest=distance;selected=button;}
            if(selected!=null){selected.GetComponent<GlassControl>()?.Hover();if(click){selected.GetComponent<GlassControl>()?.Press();selected.onClick.Invoke();}}
            return true; // The body and a destroyed/rebuilt control both consume this press.
        }
        static void Release(UnityEngine.Object value)
        {if(Application.isPlaying)UnityEngine.Object.Destroy(value);else UnityEngine.Object.DestroyImmediate(value);}
        public void Dispose(){if(IsDisposed)return;Close();IsDisposed=true;if(root!=null)Release(root);root=view=null;buttons.Clear();}
    }
}
