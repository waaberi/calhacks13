using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpatialModeling
{
    // These arrows compile the same native axis constraints as the existing
    // Blender tool. They own no input buttons, document state or geometry.
    public sealed class DirectTranslationHandles : IDisposable
    {
        static readonly Color[] Colours={new Color(1,.16f,.12f),new Color(.18f,1,.22f),new Color(.18f,.48f,1)};
        readonly LineRenderer[] shafts=new LineRenderer[3];
        readonly Transform[] tips=new Transform[3];
        readonly Material[] materials=new Material[3];
        GameObject root;
        Mesh cone;
        public sealed class Frame
        {
            public readonly Vector3 Pivot;
            public readonly float Length,Width,HeadLength,HeadRadius;
            readonly Vector3[] axes;
            public readonly bool Valid;
            public Frame(Vector3 pivot,Vector3[] directions,Vector3 eye)
            {
                Pivot=pivot;axes=directions!=null?(Vector3[])directions.Clone():null;
                float distance=Vector3.Distance(eye,pivot);
                Length=Mathf.Clamp(distance*.10f,.14f,.30f);Width=Mathf.Clamp(distance*.003f,.004f,.008f);
                HeadLength=Length*.22f;HeadRadius=Length*.075f;
                if(axes==null||axes.Length!=3)return;
                for(int i=0;i<3;i++)
                {if(!Finite(axes[i])||axes[i].sqrMagnitude<1e-10f)return;axes[i].Normalize();}
                Valid=Finite(pivot);
            }
            public Vector3 Axis(int i)=>axes[i];
            public Vector3 Start(int i)=>Pivot+axes[i]*.025f;
            public Vector3 Tip(int i)=>Pivot+axes[i]*Length;
            public Vector3 Shoulder(int i)=>Tip(i)-axes[i]*HeadLength;
        }
        public struct Hit { public int Axis;public float Distance; }
        public static bool TryPick(Frame frame,Ray ray,float nearest,out Hit hit)
        {
            hit=default;if(frame==null||!frame.Valid||nearest<=0)return false;
            bool found=false;float best=float.PositiveInfinity;
            for(int i=0;i<3;i++)
            {
                // Retain the free-move center when an axis points along the ray.
                bool endOn=Mathf.Abs(Vector3.Dot(frame.Axis(i),ray.direction.normalized))>.96f;
                if(endOn)continue;
                Vector3 start=frame.Start(i);
                if(!Closest(ray,start,frame.Tip(i),out float depth,out float miss)||depth>nearest)continue;
                float nearTip=Vector3.Distance(ray.GetPoint(depth),frame.Tip(i));
                float tolerance=Mathf.Max(.010f,depth*.008f);
                if(nearTip<=frame.HeadLength)tolerance=Mathf.Max(tolerance,frame.HeadRadius*1.35f);
                float score=miss/tolerance;
                if(score>1||found&&(score>best+.02f||Mathf.Abs(score-best)<=.02f&&depth>=hit.Distance))continue;
                found=true;best=score;hit=new Hit{Axis=i,Distance=depth};
            }
            return found;
        }
        static bool Closest(Ray ray,Vector3 a,Vector3 b,out float depth,out float miss)
        {
            var direction=ray.direction.normalized;var segment=b-a;var offset=a-ray.origin;
            float along=Vector3.Dot(segment,direction),denominator=segment.sqrMagnitude-along*along;
            float t=denominator>1e-10f?Mathf.Clamp01((along*Vector3.Dot(offset,direction)-Vector3.Dot(offset,segment))/denominator):0;
            var at=a+segment*t;depth=Vector3.Dot(at-ray.origin,direction);miss=Vector3.Distance(at,ray.origin+direction*depth);return depth>0;
        }
        public void Draw(Frame frame,int selected=-1)
        {
            if(frame==null||!frame.Valid){Hide();return;}Ensure();root.SetActive(true);
            for(int i=0;i<3;i++)
            {
                var colour=selected==i?new Color(1,.85f,.18f):Colours[i];
                if(materials[i].HasProperty("_Color"))materials[i].SetColor("_Color",colour);
                if(materials[i].HasProperty("_BaseColor"))materials[i].SetColor("_BaseColor",colour);
                shafts[i].startColor=shafts[i].endColor=colour;shafts[i].widthMultiplier=frame.Width*(selected==i?1.4f:1);
                shafts[i].SetPosition(0,frame.Start(i));shafts[i].SetPosition(1,frame.Shoulder(i));
                tips[i].position=frame.Tip(i);tips[i].rotation=Quaternion.LookRotation(frame.Axis(i));
                tips[i].localScale=new Vector3(frame.HeadRadius,frame.HeadRadius,frame.HeadLength);
            }
        }
        void Ensure()
        {
            if(root!=null)return;root=new GameObject("Native Blender Move arrows");
            cone=new Mesh{name="Native Move arrowhead"};
            var vertices=new Vector3[10];var colours=new Color[10];var triangles=new int[48];
            vertices[0]=Vector3.zero;vertices[9]=Vector3.back;
            for(int i=0;i<8;i++)vertices[i+1]=new Vector3(Mathf.Cos(i*Mathf.PI/4),Mathf.Sin(i*Mathf.PI/4),-1);
            for(int i=0;i<vertices.Length;i++)colours[i]=Color.white;
            for(int i=0;i<8;i++){int a=i+1,b=(i+1)%8+1,j=i*6;triangles[j]=0;triangles[j+1]=a;triangles[j+2]=b;triangles[j+3]=9;triangles[j+4]=b;triangles[j+5]=a;}
            cone.vertices=vertices;cone.colors=colours;cone.triangles=triangles;cone.RecalculateBounds();
            var shader=Shader.Find("UI/Default")??Shader.Find("Universal Render Pipeline/Unlit");
            for(int i=0;i<3;i++)
            {
                var material=new Material(shader){name="Native Move "+"XYZ"[i],renderQueue=4000};materials[i]=material;
                material.SetInt("unity_GUIZTestMode",(int)CompareFunction.Always);
                if(material.HasProperty("_ZTest"))material.SetInt("_ZTest",(int)CompareFunction.Always);
                if(material.HasProperty("_ZWrite"))material.SetInt("_ZWrite",0);
                var shaft=new GameObject("Native "+"XYZ"[i]+" Move shaft");shaft.transform.SetParent(root.transform,false);
                shafts[i]=shaft.AddComponent<LineRenderer>();shafts[i].sharedMaterial=material;shafts[i].positionCount=2;shafts[i].useWorldSpace=true;
                shafts[i].numCapVertices=3;shafts[i].shadowCastingMode=ShadowCastingMode.Off;shafts[i].receiveShadows=false;
                var tip=new GameObject("Native "+"XYZ"[i]+" Move arrow",typeof(MeshFilter),typeof(MeshRenderer));tip.transform.SetParent(root.transform,false);
                tip.GetComponent<MeshFilter>().sharedMesh=cone;var renderer=tip.GetComponent<MeshRenderer>();renderer.sharedMaterial=material;
                renderer.shadowCastingMode=ShadowCastingMode.Off;renderer.receiveShadows=false;tips[i]=tip.transform;
            }
        }
        public void Hide(){if(root!=null)root.SetActive(false);}
        public void Dispose(){if(root!=null)Release(root);if(cone!=null)Release(cone);foreach(var material in materials)if(material!=null)Release(material);root=null;}
        static bool Finite(Vector3 p)=>!float.IsNaN(p.x)&&!float.IsInfinity(p.x)&&!float.IsNaN(p.y)&&!float.IsInfinity(p.y)&&!float.IsNaN(p.z)&&!float.IsInfinity(p.z);
        static void Release(UnityEngine.Object obj){if(Application.isPlaying)UnityEngine.Object.Destroy(obj);else UnityEngine.Object.DestroyImmediate(obj);}
    }
}
