using System;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Optional components use the same contours/states as the migrated runtime.
    // They do not enable any new product feature by themselves.
    public static class GlassComponents
    {
        public static Button Toggle(Transform parent,string label,Vector2 position,Vector2 size,bool initial,Action<bool> changed)
        {
            bool value=initial;Button button=null;
            void Refresh(){button.GetComponentInChildren<Text>().text=label+(value?"  ✓ ON":"  ○ OFF");GlassTheme.State(button,value);}
            button=GlassTheme.Action(parent,label,position,size,()=>{value=!value;Refresh();changed?.Invoke(value);});Refresh();return button;
        }
        public static InputField Field(Transform parent,string label,Vector2 position,Vector2 size,string value,Action<string> changed)
        {
            var rect=GlassTheme.Panel(parent,label,position,size);rect.GetComponent<RoundedGlassImage>().Radius=GlassTheme.FieldRadius;
            var field=rect.gameObject.AddComponent<InputField>();var text=GlassTheme.Label(rect,value,Vector2.zero,size-new Vector2(28,8),25);
            text.alignment=TextAnchor.MiddleLeft;field.textComponent=text;field.text=value;field.targetGraphic=rect.GetComponent<Image>();
            field.onEndEdit.AddListener(v=>changed?.Invoke(v));rect.GetComponent<Image>().raycastTarget=true;
            GlassTheme.StyleAction(rect.gameObject);return field;
        }
        public static Slider Slider(Transform parent,string name,Vector2 position,Vector2 size,float value,Action<float> changed)
        {
            var rect=GlassTheme.Panel(parent,name,position,size);var slider=rect.gameObject.AddComponent<Slider>();
            var track=GlassTheme.Panel(rect,"Track",Vector2.zero,new Vector2(size.x-32,10));track.GetComponent<Image>().color=GlassTheme.Secondary;
            var area=new GameObject("Handle travel",typeof(RectTransform)).GetComponent<RectTransform>();area.SetParent(rect,false);area.sizeDelta=new Vector2(size.x-32,0);
            var handle=GlassTheme.Panel(area,"Handle",Vector2.zero,new Vector2(32,32));handle.GetComponent<RoundedGlassImage>().Radius=16;
            handle.GetComponent<Image>().color=GlassTheme.Ink;slider.handleRect=handle;slider.targetGraphic=handle.GetComponent<Image>();
            slider.value=value;slider.onValueChanged.AddListener(v=>changed?.Invoke(v));
            GlassTheme.StyleAction(rect.gameObject);rect.GetComponent<Image>().raycastTarget=true;return slider;
        }
        public static Scrollbar Scrollbar(Transform parent,string name,Vector2 position,Vector2 size)
        {
            var rect=GlassTheme.Panel(parent,name,position,size);var bar=rect.gameObject.AddComponent<Scrollbar>();
            var handle=GlassTheme.Panel(rect,"Thumb",Vector2.zero,new Vector2(size.x,40));handle.GetComponent<Image>().color=GlassTheme.Secondary;
            bar.handleRect=handle;bar.targetGraphic=handle.GetComponent<Image>();bar.direction=UnityEngine.UI.Scrollbar.Direction.BottomToTop;bar.size=.3f;
            GlassTheme.StyleAction(rect.gameObject);rect.GetComponent<Image>().raycastTarget=true;return bar;
        }
        public static RectTransform Status(Transform parent,string message,Vector2 position,Vector2 size,bool error=false)
        {
            var rect=GlassTheme.Panel(parent,error?"Error message":"Status message",position,size);
            if(error)rect.GetComponent<Image>().color=GlassTheme.Error;
            GlassTheme.Label(rect,(error?"!  ":"i  ")+message,Vector2.zero,size-new Vector2(32,16),25);return rect;
        }
        public static RectTransform Tooltip(Transform parent,string message,Vector2 position,Vector2 size)
        {var rect=Status(parent,message,position,size);rect.name="Tooltip";return rect;}
        public static RectTransform Dialog(Transform parent,string title,string detail,Vector2 position,Vector2 size,Action confirm,Action cancel)
        {
            var rect=GlassTheme.Panel(parent,title,position,size);GlassTheme.Label(rect,title,new Vector2(0,size.y*.3f),new Vector2(size.x-40,50),30);
            GlassTheme.Label(rect,detail,Vector2.zero,new Vector2(size.x-40,size.y*.35f));
            GlassTheme.Action(rect,"Cancel",new Vector2(-size.x*.23f,-size.y*.32f),new Vector2(size.x*.4f,60),cancel);
            GlassTheme.Action(rect,"Continue",new Vector2(size.x*.23f,-size.y*.32f),new Vector2(size.x*.4f,60),confirm);return rect;
        }
    }
}
