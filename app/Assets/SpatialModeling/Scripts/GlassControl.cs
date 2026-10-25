using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace SpatialModeling
{
    public sealed class GlassControl : MonoBehaviour,IPointerEnterHandler,IPointerExitHandler,IPointerDownHandler,IPointerUpHandler,ISelectHandler,IDeselectHandler
    {
        public bool Selected,Error;
        public bool Hovered {get;private set;}
        public bool Focused {get;private set;}
        public bool PressActive => Time.unscaledTime<=pressedUntil;
        float hoverUntil=-1,pressedUntil=-1;
        Image image;Selectable button;Text label;
        void Awake(){image=GetComponent<Image>();button=GetComponent<Selectable>();}
        public void Hover(){hoverUntil=Time.unscaledTime+.08f;}
        public void ClearHover(){hoverUntil=-1;}
        public void Press(){pressedUntil=Time.unscaledTime+(GlassTheme.ReducedMotion ? .12f:.28f);Refresh();}
        public void OnPointerEnter(PointerEventData _){Hovered=true;}
        public void OnPointerExit(PointerEventData _){Hovered=false;}
        public void OnPointerDown(PointerEventData _){Press();}
        public void OnPointerUp(PointerEventData _){ }
        public void OnSelect(BaseEventData _){Focused=true;}
        public void OnDeselect(BaseEventData _){Focused=false;}
        void LateUpdate()=>Refresh();
        public void Refresh()
        {
            if(image==null)image=GetComponent<Image>();if(button==null)button=GetComponent<Selectable>();if(image==null)return;
            bool disabled=button!=null&&!button.interactable;
            var color=Error?GlassTheme.Error:Selected?GlassTheme.Selected:GlassTheme.Control;
            if(!disabled&&(Hovered||Focused||Time.unscaledTime<=hoverUntil))color=Color.Lerp(color,GlassTheme.Hover,.65f);
            if(!disabled&&Time.unscaledTime<=pressedUntil)color=new Color(.36f,.28f,.13f,1);
            if(disabled)color=new Color(.10f,.115f,.14f,.96f);
            if(image.color!=color)image.color=color;
            if(label==null)label=GetComponentInChildren<Text>();
            if(label!=null){var ink=disabled?GlassTheme.Secondary:GlassTheme.Ink;if(label.color!=ink)label.color=ink;}
            // Non-color state cue. Focus/hover brightens the rim; selected retains ON/LOCKED text in the caller.
            if(image is RoundedGlassImage rounded)
            {
                bool emphasized=Focused||Selected||Error;
                if(rounded.IsPanel||rounded.Emphasized!=emphasized)
                {rounded.IsPanel=false;rounded.Emphasized=emphasized;rounded.SetVerticesDirty();}
            }
        }
    }
}
