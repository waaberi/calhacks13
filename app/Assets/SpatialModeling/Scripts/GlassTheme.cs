using System;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Stable public entry point for all app-owned UI. No native/editor state lives here.
    public static class GlassTheme
    {
        public static readonly Color Ink = new Color(.96f,.975f,1f);
        public static readonly Color Secondary = new Color(.78f,.83f,.9f);
        public static readonly Color Surface = new Color(.12f,.14f,.18f,.72f);
        public static readonly Color Control = new Color(.20f,.23f,.28f,.76f);
        public static readonly Color Hover = new Color(.24f,.28f,.35f,.98f);
        public static readonly Color Selected = new Color(.075f,.28f,.21f,.99f);
        public static readonly Color Error = new Color(.35f,.095f,.12f,.99f);
        public static readonly Color Focus = new Color(.55f,.77f,1f);
        public static readonly Color LeftMetal = new Color(.53f,.78f,.94f);
        public static readonly Color RightMetal = new Color(.64f,.46f,.85f);
        public const float PanelRadius=36, ControlRadius=24, FieldRadius=16, Gap=16;
        public const float ControllerRadius=.014f, ControllerLength=.105f, Metalness=.86f, Roughness=.27f;
        const string Prefix="SpatialModeling.Glass.";
        public static float TextScale => Mathf.Clamp(PlayerPrefs.GetFloat(Prefix+"TextScale",1),1,2);
        public static bool HighContrast => PlayerPrefs.GetInt(Prefix+"Contrast",0)==1;
        public static bool ReducedTransparency => PlayerPrefs.GetInt(Prefix+"Opaque",0)==1;
        public static bool ReducedMotion => PlayerPrefs.GetInt(Prefix+"Motion",0)==1;
        public static event Action Changed;
        public static void SetAccessibility(float scale,bool contrast,bool opaque,bool motion)
        {
            PlayerPrefs.SetFloat(Prefix+"TextScale",Mathf.Clamp(scale,1,2));
            PlayerPrefs.SetInt(Prefix+"Contrast",contrast?1:0);
            PlayerPrefs.SetInt(Prefix+"Opaque",opaque?1:0);
            PlayerPrefs.SetInt(Prefix+"Motion",motion?1:0);
            PlayerPrefs.Save(); Changed?.Invoke();
        }
        public static void CycleText() => SetAccessibility(TextScale<1.2f?1.25f:TextScale<1.4f?1.5f:TextScale<1.8f?2:1,HighContrast,ReducedTransparency,ReducedMotion);
        public static RectTransform Panel(Transform parent,string name,Vector2 position,Vector2 size)
        {
            var go=new GameObject(name,typeof(RectTransform),typeof(RoundedGlassImage));
            var rect=(RectTransform)go.transform;rect.SetParent(parent,false);rect.anchoredPosition=position;rect.sizeDelta=size;
            StylePanel(go.GetComponent<Image>());return rect;
        }
        public static void StylePanel(Image image)
        {
            var canvas=image.GetComponentInParent<Canvas>();
            if(canvas!=null)canvas.additionalShaderChannels|=AdditionalCanvasShaderChannels.TexCoord1;
            image.color=Surface;image.raycastTarget=false;
            if(image is RoundedGlassImage rounded) { rounded.Radius=PanelRadius;rounded.IsPanel=true; }
            // Optical edges live in the material. A duplicate Shadow mesh would sample
            // the background twice and make inset masks look dirty.
            Curve(image.gameObject);
        }
        public static GlassControl StyleAction(GameObject go)
        {
            var image=go.GetComponent<Image>();if(image!=null) { image.color=Control;if(image is RoundedGlassImage rounded) rounded.Radius=ControlRadius; }
            var button=go.GetComponent<Selectable>();
            if(button!=null) { button.transition=Selectable.Transition.None;button.targetGraphic=image; }
            Curve(go);var control=go.GetComponent<GlassControl>()??go.AddComponent<GlassControl>();return control;
        }
        public static Button Action(Transform parent,string label,Vector2 position,Vector2 size,Action action)
        {
            var rect=Panel(parent,label,position,size);var button=rect.gameObject.AddComponent<Button>();
            StyleAction(rect.gameObject);rect.GetComponent<Image>().raycastTarget=true;
            button.onClick.AddListener(()=>action?.Invoke());Label(rect,label,Vector2.zero,size-new Vector2(24,8),25);return button;
        }
        public static Text Label(Transform parent,string value,Vector2 position,Vector2 size,int fontSize=25)
        {
            var go=new GameObject("Label",typeof(RectTransform),typeof(Text));var rect=(RectTransform)go.transform;
            rect.SetParent(parent,false);rect.anchoredPosition=position;rect.sizeDelta=size;
            var text=go.GetComponent<Text>();text.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize=fontSize;text.text=value;text.color=Ink;text.alignment=TextAnchor.MiddleCenter;text.raycastTarget=false;
            StyleText(text);return text;
        }
        public static void StyleText(Text text)
        {
            var type=text.GetComponent<GlassType>()??text.gameObject.AddComponent<GlassType>();type.Initialize(text);
            Curve(text.gameObject);
        }
        static void Curve(GameObject go)
        {if(go.GetComponentInParent<GlassCurvedCanvas>()!=null&&go.GetComponent<GlassCurveMesh>()==null)go.AddComponent<GlassCurveMesh>();}
        public static bool Contains(RectTransform rect,Vector2 point)
        {
            var image=rect.GetComponent<RoundedGlassImage>();
            return image!=null?RoundedGlassImage.Contains(rect.rect,point,image.Radius):rect.rect.Contains(point);
        }
        public static bool ContainsWorld(Transform target,Vector3 world)
        {
            if(!(target is RectTransform rect))return false;
            var p=(Vector2)rect.InverseTransformPoint(world);
            return target.GetComponent<SettingsGearGraphic>()!=null?RoundedGlassImage.Contains(rect.rect,p,rect.rect.width*.5f):Contains(rect,p);
        }
        public static void State(Button button,bool selected=false,bool error=false,bool pressed=false)
        { if(button!=null) { var state=StyleAction(button.gameObject);state.Selected=selected;state.Error=error;if(pressed) state.Press();state.Refresh(); } }
    }
}
