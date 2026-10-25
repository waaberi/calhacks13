using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

namespace SpatialModeling
{
    public static class GlassController
    {
        // Mesh local +Z is forward; its rounded pole is exactly local zero.
        // The whole body sits behind the OpenXR aim origin, never at a guessed grip offset.
        public static Mesh RoundedCylinder(float radius=GlassTheme.ControllerRadius,float length=GlassTheme.ControllerLength)
        {
            var vertices=new List<Vector3>();var normals=new List<Vector3>();var triangles=new List<int>();
            const int slices=48,cap=12;int rings=cap*2+2;
            float middle=Mathf.Max(0,length-2*radius);
            for(int ring=0;ring<rings;ring++)
            {
                bool front=ring>cap;
                float angle=front?(ring-cap-1)*Mathf.PI*.5f/cap:-Mathf.PI*.5f+ring*Mathf.PI*.5f/cap;
                float z=(front?-radius:-radius-middle)+Mathf.Sin(angle)*radius;
                float r=Mathf.Cos(angle)*radius;
                for(int i=0;i<=slices;i++)
                {
                    float a=i*2*Mathf.PI/slices;var n=new Vector3(Mathf.Cos(a)*Mathf.Cos(angle),Mathf.Sin(a)*Mathf.Cos(angle),Mathf.Sin(angle));
                    vertices.Add(new Vector3(Mathf.Cos(a)*r,Mathf.Sin(a)*r,z));normals.Add(n);
                }
            }
            for(int ring=0;ring<rings-1;ring++)for(int i=0;i<slices;i++)
            {int a=ring*(slices+1)+i,b=a+slices+1;triangles.Add(a);triangles.Add(a+1);triangles.Add(b);triangles.Add(a+1);triangles.Add(b+1);triangles.Add(b);}
            var mesh=new Mesh{name="Smooth rounded cylinder +Z aim pole"};mesh.SetVertices(vertices);mesh.SetNormals(normals);mesh.SetTriangles(triangles,0);mesh.RecalculateBounds();return mesh;
        }
        public static GameObject Create(Transform parent,XRNode hand)
        {
            var go=new GameObject("Satin rounded aim cylinder",typeof(MeshFilter),typeof(MeshRenderer));go.transform.SetParent(parent,false);
            go.GetComponent<MeshFilter>().sharedMesh=RoundedCylinder();
            var shader=Resources.Load<Shader>("GlassSatinMetal");
            if(shader==null)shader=Shader.Find("Universal Render Pipeline/Lit");
            var material=new Material(shader){name=hand==XRNode.LeftHand?"Icy blue satin metal":"Lavender purple satin metal"};
            material.SetColor("_BaseColor",hand==XRNode.LeftHand?GlassTheme.LeftMetal:GlassTheme.RightMetal);
            material.SetFloat("_Metallic",GlassTheme.Metalness);material.SetFloat("_Smoothness",1-GlassTheme.Roughness);
            go.GetComponent<MeshRenderer>().sharedMaterial=material;go.AddComponent<GlassControllerLifetime>();return go;
        }
        public static void ApplyAim(Transform visual,LineRenderer ray,Transform target,Pose aim,float distance)
        {
            visual.SetPositionAndRotation(aim.position,aim.rotation);
            ray.SetPosition(0,aim.position);
            var endpoint=aim.position+aim.rotation*Vector3.forward*Mathf.Max(.01f,distance);
            ray.SetPosition(1,endpoint);target.position=endpoint;
        }
    }
    public sealed class GlassControllerLifetime : MonoBehaviour
    {
        void OnDestroy()
        {
            var mesh=GetComponent<MeshFilter>().sharedMesh;var material=GetComponent<MeshRenderer>().sharedMaterial;
            if(Application.isPlaying){Destroy(mesh);Destroy(material);}else{DestroyImmediate(mesh);DestroyImmediate(material);}
        }
    }
}
