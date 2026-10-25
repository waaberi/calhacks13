using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // A gentle cylindrical canvas. Arrangement still moves its original root;
    // native pixel dimensions and UVs are unchanged by the display geometry.
    public sealed class GlassCurvedCanvas : MonoBehaviour
    {
        public const float DefaultRadius=5600f;
        public float Radius=DefaultRadius;
        public Vector3 Bend(Vector3 p)
        {float angle=p.x/Radius;return new Vector3(Mathf.Sin(angle)*Radius,p.y,(Mathf.Cos(angle)-1)*Radius+p.z);}
        public static Vector3 BendPoint(Vector3 p,float radius)
        {float angle=p.x/radius;return new Vector3(Mathf.Sin(angle)*radius,p.y,(Mathf.Cos(angle)-1)*radius+p.z);}
        public static bool Intersect(Ray local,float radius,float z,out Vector3 flat,out float t)
        {
            flat=default;t=0;var o=local.origin;var d=local.direction;
            float a=d.x*d.x+d.z*d.z;if(a<1e-10f)return false;
            float b=2*(o.x*d.x+(o.z+radius-z)*d.z);
            float c=o.x*o.x+(o.z+radius-z)*(o.z+radius-z)-radius*radius;
            float discriminant=b*b-4*a*c;if(discriminant<0)return false;
            float root=Mathf.Sqrt(discriminant);
            float first=(-b-root)/(2*a),second=(-b+root)/(2*a);
            foreach(float candidate in new[]{first,second})
            {
                if(candidate<0)continue;var p=local.GetPoint(candidate);
                if(p.z+radius-z<=0)continue; // Reject the cylinder's invisible rear half.
                float angle=Mathf.Atan2(p.x,p.z+radius-z);
                flat=new Vector3(angle*radius,p.y,z);t=candidate;return true;
            }
            return false;
        }
        public void ApplyToChildren()
        {
            foreach(var graphic in GetComponentsInChildren<Graphic>(true))
                if(graphic.GetComponent<GlassCurveMesh>()==null)graphic.gameObject.AddComponent<GlassCurveMesh>();
        }
        public Bounds LocalBounds()
        {
            var root=(RectTransform)transform;var result=new Bounds(Bend(root.rect.center),Vector3.zero);
            foreach(var graphic in GetComponentsInChildren<Graphic>())
            {
                if(!graphic.gameObject.activeInHierarchy)continue;
                var rect=graphic.rectTransform;var corners=new Vector3[4];rect.GetWorldCorners(corners);
                foreach(var world in corners)result.Encapsulate(Bend(transform.InverseTransformPoint(world)));
                result.Encapsulate(Bend(transform.InverseTransformPoint(rect.position)));
            }
            result.Expand(new Vector3(0,0,8));return result;
        }
        public bool Hit(RectTransform rect,Ray ray,out float distance,out Vector2 local,bool contour=true)
        {
            distance=0;local=default;
            // Unity's Ray constructor normalizes direction. Its intersection t is
            // in canvas units; convert the actual hit point back to world metres.
            var localRay=new Ray(transform.InverseTransformPoint(ray.origin),transform.InverseTransformVector(ray.direction));
            float z=transform.InverseTransformPoint(rect.position).z;
            if(!Intersect(localRay,Radius,z,out var flat,out float canvasDistance))return false;
            distance=Vector3.Distance(ray.origin,transform.TransformPoint(localRay.GetPoint(canvasDistance)));
            if(distance<=0||distance>4)return false;
            local=rect.InverseTransformPoint(transform.TransformPoint(flat));
            return !contour||GlassTheme.Contains(rect,local);
        }
    }
    public static class GlassRaycast
    {
        public static bool Hit(RectTransform rect,Ray ray,out float distance,out Vector2 local,bool contour=true)
        {
            distance=0;local=default;if(rect==null)return false;
            var curve=rect.GetComponentInParent<GlassCurvedCanvas>();
            if(curve!=null)return curve.Hit(rect,ray,out distance,out local,contour);
            if(!new Plane(rect.forward,rect.position).Raycast(ray,out distance)||distance<=0||distance>4)return false;
            local=rect.InverseTransformPoint(ray.GetPoint(distance));return !contour||GlassTheme.Contains(rect,local);
        }
    }
    public sealed class GlassCurveMesh : BaseMeshEffect
    {
        public override void ModifyMesh(VertexHelper vh)
        {
            if(!IsActive())return;var curve=GetComponentInParent<GlassCurvedCanvas>();if(curve==null)return;
            // Subdivide every input triangle before bending. This includes glyphs,
            // rounded mask contours, highlights and streamed pixels on the same arc.
            var input=new System.Collections.Generic.List<UIVertex>();vh.GetUIVertexStream(input);vh.Clear();
            for(int i=0;i<input.Count;i+=3)Subdivide(vh,curve,input[i],input[i+1],input[i+2],0);
        }
        void Subdivide(VertexHelper vh,GlassCurvedCanvas curve,UIVertex a,UIVertex b,UIVertex c,int depth)
        {
            float ax=curve.transform.InverseTransformPoint(transform.TransformPoint(a.position)).x;
            float bx=curve.transform.InverseTransformPoint(transform.TransformPoint(b.position)).x;
            float cx=curve.transform.InverseTransformPoint(transform.TransformPoint(c.position)).x;
            if(depth<7&&Mathf.Max(ax,Mathf.Max(bx,cx))-Mathf.Min(ax,Mathf.Min(bx,cx))>45)
            {
                float ab=Mathf.Abs(ax-bx),bc=Mathf.Abs(bx-cx),ca=Mathf.Abs(cx-ax);
                if(ab>=bc&&ab>=ca){var mid=Mid(a,b);Subdivide(vh,curve,a,mid,c,depth+1);Subdivide(vh,curve,mid,b,c,depth+1);}
                else if(bc>=ca){var mid=Mid(b,c);Subdivide(vh,curve,a,b,mid,depth+1);Subdivide(vh,curve,a,mid,c,depth+1);}
                else{var mid=Mid(c,a);Subdivide(vh,curve,a,b,mid,depth+1);Subdivide(vh,curve,mid,b,c,depth+1);}return;
            }
            int index=vh.currentVertCount;vh.AddVert(Bend(a,curve));vh.AddVert(Bend(b,curve));vh.AddVert(Bend(c,curve));vh.AddTriangle(index,index+1,index+2);
        }
        static UIVertex Mid(UIVertex a,UIVertex b)
        {var v=a;v.position=(a.position+b.position)*.5f;v.uv0=(a.uv0+b.uv0)*.5f;v.uv1=(a.uv1+b.uv1)*.5f;v.color=Color32.Lerp(a.color,b.color,.5f);return v;}
        UIVertex Bend(UIVertex v,GlassCurvedCanvas curve)
        {var p=curve.transform.InverseTransformPoint(transform.TransformPoint(v.position));v.position=transform.InverseTransformPoint(curve.transform.TransformPoint(curve.Bend(p)));return v;}
    }
}
