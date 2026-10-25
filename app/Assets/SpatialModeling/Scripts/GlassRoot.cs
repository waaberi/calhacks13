using UnityEngine;

namespace SpatialModeling
{
    // Text size scales controls and their exact hit contours together, without truncation.
    public sealed class GlassRoot : MonoBehaviour
    {
        float previous=1;
        void OnEnable(){GlassTheme.Changed+=Apply;Apply();}
        void OnDisable(){GlassTheme.Changed-=Apply;}
        void LateUpdate(){if(previous!=GlassTheme.TextScale)Apply();}
        void Apply(){float next=GlassTheme.TextScale;transform.localScale*=next/previous;previous=next;}
    }
}
