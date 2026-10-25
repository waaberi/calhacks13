using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Geometry, stencil mask and hit region share the same rounded contour.
    // Glass samples only the pre-UI Unity backdrop; never compositor or Blender pixels.
    [AddComponentMenu("Spatial Modeling/Glass/Rounded surface")]
    [ExecuteAlways]
    public sealed class RoundedGlassImage : Image
    {
        public float Radius=GlassTheme.ControlRadius;
        public bool IsPanel;
        public bool Emphasized;
        const int Steps=12;
        static Material glassMaterial;
        protected override void OnEnable()
        {
            base.OnEnable();GlassTheme.Changed+=Refresh;
            if(glassMaterial==null)
            {
                var shader=Resources.Load<Shader>("GlassSurface");
                if(shader!=null)glassMaterial=new Material(shader){name="Shared spatial glass",hideFlags=HideFlags.HideAndDontSave};
            }
            material=glassMaterial;
            var canvas=GetComponentInParent<Canvas>();
            if(canvas!=null)canvas.additionalShaderChannels|=AdditionalCanvasShaderChannels.TexCoord1;
        }
        protected override void OnDisable(){GlassTheme.Changed-=Refresh;base.OnDisable();}
        protected override void OnCanvasHierarchyChanged()
        {
            base.OnCanvasHierarchyChanged();
            if(canvas!=null)canvas.additionalShaderChannels|=AdditionalCanvasShaderChannels.TexCoord1;
        }
        void Refresh()=>SetVerticesDirty();
        public static bool Contains(Rect rect,Vector2 p,float radius)
        {
            if(!rect.Contains(p)) return false;
            float r=Mathf.Min(radius,Mathf.Min(rect.width,rect.height)*.5f);
            var q=new Vector2(Mathf.Max(Mathf.Abs(p.x-rect.center.x)-(rect.width*.5f-r),0),Mathf.Max(Mathf.Abs(p.y-rect.center.y)-(rect.height*.5f-r),0));
            return q.sqrMagnitude<=r*r;
        }
        public override bool IsRaycastLocationValid(Vector2 point,Camera camera)
            => RectTransformUtility.ScreenPointToLocalPointInRectangle(rectTransform,point,camera,out var local)
                && Contains(rectTransform.rect,local,Radius) && base.IsRaycastLocationValid(point,camera);
        protected override void OnPopulateMesh(VertexHelper vh)
        {
            // Dynamic factories attach the Image before parenting it. Editor lifecycle
            // callbacks can miss that transition; never silently drop optical metadata.
            var owner=GetComponentInParent<Canvas>();
            if(owner!=null&&(owner.additionalShaderChannels&AdditionalCanvasShaderChannels.TexCoord1)==0)
                owner.additionalShaderChannels|=AdditionalCanvasShaderChannels.TexCoord1;
            vh.Clear();var rect=GetPixelAdjustedRect();if(rect.width<=0||rect.height<=0)return;
            float radius=Mathf.Min(Radius,Mathf.Min(rect.width,rect.height)*.5f);
            Color fill=color;
            bool opaque=GlassTheme.ReducedTransparency||GlassTheme.HighContrast
                ||(BlenderViewAppearance.Opaque&&GetComponentInParent<BlenderViewAppearance>()!=null);
            if(opaque) fill.a=1;
            if(GlassTheme.HighContrast) fill= new Color(fill.r*.65f,fill.g*.65f,fill.b*.65f,1);
            const int count=4*(Steps+1);
            void Add(Vector2 p)
            {
                var vertex=UIVertex.simpleVert;vertex.position=p;vertex.color=fill;
                vertex.uv0=new Vector2((p.x-rect.xMin)/rect.width,(p.y-rect.yMin)/rect.height);
                vertex.uv1=new Vector4(rect.width,rect.height,radius,
                    opaque ? -1:IsPanel?1:Emphasized?2:0);
                vh.AddVert(vertex);
            }
            for(int corner=0;corner<4;corner++)for(int j=0;j<=Steps;j++)
            {
                float angle=(corner*90+j*90f/Steps)*Mathf.Deg2Rad;
                var center=new Vector2(corner==0||corner==3?rect.xMax-radius:rect.xMin+radius,corner<2?rect.yMax-radius:rect.yMin+radius);
                Add(center+new Vector2(Mathf.Cos(angle),Mathf.Sin(angle))*radius);
            }
            int mid=vh.currentVertCount;Add(rect.center);
            for(int j=0;j<count;j++)vh.AddTriangle(mid,j,(j+1)%count);
        }
    }
}
