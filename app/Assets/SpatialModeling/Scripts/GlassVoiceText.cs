using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Preserve the existing voice TextMesh/prompt lifecycle; share glass contours and type scaling.
    public sealed class GlassVoiceText : MonoBehaviour
    {
        TextMesh text;
        RectTransform backing;
        Material material;
        float baseSize;
        public static void Create(TextMesh text)
        {
            var style=text.gameObject.AddComponent<GlassVoiceText>();style.text=text;style.baseSize=text.characterSize;
            var go=new GameObject("VoiceTextBacking",typeof(RectTransform),typeof(Canvas),typeof(RoundedGlassImage));
            go.transform.SetParent(text.transform,false);style.backing=go.GetComponent<RectTransform>();
            var canvas=go.GetComponent<Canvas>();canvas.renderMode=RenderMode.WorldSpace;canvas.overrideSorting=true;canvas.sortingOrder=4000;
            var image=go.GetComponent<RoundedGlassImage>();GlassTheme.StylePanel(image);image.raycastTarget=false;
            style.material=new Material(image.material){name="Voice glass overlay",renderQueue=4000};
            style.material.SetInt("unity_GUIZTestMode",(int)UnityEngine.Rendering.CompareFunction.Always);image.material=style.material;
            go.SetActive(false);
        }
        public void Fit()
        {
            text.characterSize=baseSize*GlassTheme.TextScale;
            var bounds=text.GetComponent<MeshRenderer>().localBounds;
            bool show=text.gameObject.activeInHierarchy&&!string.IsNullOrEmpty(text.text)&&bounds.size.x>0&&bounds.size.y>0;
            backing.gameObject.SetActive(show);if(!show)return;
            // RoundedGlassImage restores its shared material on re-enable. Voice
            // overlays must retain their existing always-visible prompt contract.
            backing.GetComponent<RoundedGlassImage>().material=material;
            float margin=Mathf.Max(text.characterSize*text.fontSize*.02f,.024f*GlassTheme.TextScale);
            backing.localPosition=new Vector3(bounds.center.x,bounds.center.y,.002f);
            backing.localRotation=Quaternion.identity;backing.localScale=Vector3.one*.001f;
            backing.sizeDelta=new Vector2(bounds.size.x+2*margin,bounds.size.y+2*margin)*1000;
        }
        void OnDestroy(){if(material!=null){if(Application.isPlaying)Destroy(material);else DestroyImmediate(material);}}
    }
}
