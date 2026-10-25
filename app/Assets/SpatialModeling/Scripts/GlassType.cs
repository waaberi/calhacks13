using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    public sealed class GlassType : MonoBehaviour
    {
        Text label;float applied=-1;
        public void Initialize(Text text){if(label!=null)return;label=text;Apply();}
        void OnEnable(){GlassTheme.Changed+=Apply;}
        void OnDisable(){GlassTheme.Changed-=Apply;}
        void LateUpdate(){if(label!=null&&applied!=GlassTheme.TextScale)Apply();}
        void Apply()
        {
            if(label==null)return;applied=GlassTheme.TextScale;
            // Scale the complete UI's physical size instead of shrinking enlarged labels
            // back into old fixed-height controls. Root adapters handle this scale.
            label.horizontalOverflow=HorizontalWrapMode.Wrap;label.verticalOverflow=VerticalWrapMode.Overflow;
            label.resizeTextForBestFit=false;
        }
    }
}
