using System;
using System.Collections.Generic;
using System.Globalization;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpatialModeling
{
    // Read-only guides for the exact captured native topology. No colliders,
    // native settings, component indices, input ownership or geometry are changed.
    public sealed class DirectToolGuides : IDisposable
    {
        public const int MaximumSegments=1024,MaximumPoints=192;
        public sealed class Frame
        {
            public string Tool,Component,RadiusLabel,IntentLabel;
            public JObject Model,Acknowledged;
            public Matrix4x4 Map=Matrix4x4.identity;
            // Unity-swizzled native world metres. JSON stays Blender XYZ.
            public Vector3 Pivot;
            public int[] Indices;
            public Vector3[] KnifePath;
            public bool Held,Waiting,NativeObjectMirrored,ExtrudeNormalConstrained;
            public float? Radius;
            public Vector3? HoverPoint,SnapPoint;
            public int HoverIndex=-1;
            public string HoverComponent;
        }
        public struct Segment
        {
            public Vector3 A,B;public int Colour;public string Kind;
            public Segment(Vector3 a,Vector3 b,int colour,string kind){A=a;B=b;Colour=colour;Kind=kind;}
        }
        public struct Point
        {
            public Vector3 Position;public int NativeIndex,Colour;public string Kind;
            public Point(Vector3 at,int index,int colour,string kind){Position=at;NativeIndex=index;Colour=colour;Kind=kind;}
        }
        public sealed class Snapshot
        {
            public readonly List<Segment> Segments=new List<Segment>();
            public readonly List<Point> Points=new List<Point>();
            public string Label="",Limitation="";
            public bool Valid;
        }
        sealed class Geometry
        {
            public readonly Dictionary<int,Vector3> Vertices=new Dictionary<int,Vector3>();
            public readonly Dictionary<int,int[]> Edges=new Dictionary<int,int[]>(),Faces=new Dictionary<int,int[]>();
        }
        static readonly Color[] Colours={new Color(1,.43f,.05f),new Color(1,.85f,.16f),new Color(.15f,.95f,1),new Color(1,.2f,.7f)};
        readonly List<LineRenderer> lines=new List<LineRenderer>(),dots=new List<LineRenderer>();
        readonly Material[] materials=new Material[4];
        GameObject root;
        public Snapshot Last {get;private set;}
        public bool Visible=>root!=null&&root.activeSelf;

        static bool Finite(float v)=>!float.IsNaN(v)&&!float.IsInfinity(v);
        static bool Finite(Vector3 v)=>Finite(v.x)&&Finite(v.y)&&Finite(v.z);
        static bool Wire(JToken token,out Vector3 value)
        {
            value=default;if(!(token is JArray a)||a.Count!=3)return false;
            try{value=new Vector3((float)a[0],(float)a[2],(float)a[1]);return Finite(value);}catch(Exception){return false;}
        }
        static Geometry Read(JObject model)
        {
            var result=new Geometry();if(!(model?["vertices"] is JArray vertices)||vertices.Count>8192)return null;
            try
            {
                foreach(var token in vertices)
                {
                    if(!(token is JObject row)||!Wire(row["position"],out var at))return null;
                    int index=(int)row["index"];if(index<0||result.Vertices.ContainsKey(index))return null;result.Vertices[index]=at;
                }
                foreach(var name in new[]{"edges","faces"})
                {
                    if(!(model[name] is JArray items)||items.Count>(name=="edges"?16384:8192))return null;
                    var target=name=="edges"?result.Edges:result.Faces;
                    int corners=0;foreach(var token in items)
                    {
                        if(!(token is JObject row)||!(row["vertices"] is JArray ids)||ids.Count<(name=="edges"?2:3)||ids.Count>16384||name=="edges"&&ids.Count!=2)return null;
                        corners+=ids.Count;if(corners>65536)return null;
                        int index=(int)row["index"];if(index<0||target.ContainsKey(index))return null;
                        var list=new int[ids.Count];var seen=new HashSet<int>();
                        for(int i=0;i<ids.Count;i++){list[i]=(int)ids[i];if(!result.Vertices.ContainsKey(list[i])||!seen.Add(list[i]))return null;}
                        target[index]=list;
                    }
                }
                return result;
            }
            catch(Exception){return null;}
        }
        static void Line(Snapshot s,Vector3 a,Vector3 b,int colour,string kind)
        {if(s.Segments.Count<MaximumSegments&&Finite(a)&&Finite(b)&&(a-b).sqrMagnitude>1e-14f)s.Segments.Add(new Segment(a,b,colour,kind));}
        static void Dot(Snapshot s,Vector3 at,int index,int colour,string kind)
        {if(s.Points.Count<MaximumPoints&&Finite(at))s.Points.Add(new Point(at,index,colour,kind));}
        static void Arrow(Snapshot s,Vector3 a,Vector3 b,int colour,string kind)
        {
            var direction=b-a;if(direction.sqrMagnitude<1e-12f)return;
            Line(s,a,b,colour,kind);var side=Vector3.Cross(direction.normalized,Mathf.Abs(Vector3.Dot(direction.normalized,Vector3.up))<.9f?Vector3.up:Vector3.right).normalized;
            float head=Mathf.Min(.024f,direction.magnitude*.24f);var shoulder=b-direction.normalized*head;
            Line(s,b,shoulder+side*head*.5f,colour,kind);Line(s,b,shoulder-side*head*.5f,colour,kind);
        }
        static Vector3 Centre(Geometry g,int[] ids){var at=Vector3.zero;foreach(int id in ids)at+=g.Vertices[id];return at/ids.Length;}
        static Vector3 Normal(Geometry g,int[] ids,bool mirrored)
        {
            // World-space Newell normal, corrected for the XYZ->XZY reflection
            // and native object mirror. Map transforms displacement as a vector.
            var normal=Vector3.zero;var origin=g.Vertices[ids[0]];for(int i=0;i<ids.Length;i++)normal+=Vector3.Cross(g.Vertices[ids[i]]-origin,g.Vertices[ids[(i+1)%ids.Length]]-origin);
            return normal.sqrMagnitude<1e-16f?Vector3.zero:normal.normalized*(mirrored?1:-1);
        }
        static void Outline(Snapshot s,Geometry g,Frame f,int[] ids,string kind)
        {for(int i=0;i<ids.Length;i++)Line(s,f.Map.MultiplyPoint3x4(g.Vertices[ids[i]]),f.Map.MultiplyPoint3x4(g.Vertices[ids[(i+1)%ids.Length]]),0,kind);}
        static string Number(double v)=>v.ToString("0.###",CultureInfo.InvariantCulture);
        static string Metric(JObject value,string key,string name)
        {return value?[key]!=null?name+" "+Number((double)value[key]*1000)+" mm":"";}
        static string Readout(Frame f)
        {
            var a=f.Acknowledged;if(a==null)return f.Held||f.Waiting?"Waiting for Blender":"";
            var parts=new List<string>();
            foreach(var pair in new[]{new[]{"normal_distance_m","normal"},new[]{"thickness_m","thickness"},new[]{"width_m","width"},new[]{"depth_m","depth"},new[]{"distance_m","distance threshold"}})
                if(a[pair[0]]!=null)parts.Add(Metric(a,pair[0],pair[1]));
            if(a["angle_limit"]!=null)parts.Add("angle limit "+Number((double)a["angle_limit"]*180/Math.PI)+"°");
            if(a["normal_distance_m"]==null&&Wire(a["translation_m"],out var move))parts.Add("X "+Number(move.x*1000)+" / Y "+Number(move.z*1000)+" / Z "+Number(move.y*1000)+" mm");
            if(a["scale"] is JArray scale&&scale.Count==3)parts.Add("X ×"+Number((double)scale[0])+" / Y ×"+Number((double)scale[1])+" / Z ×"+Number((double)scale[2]));
            if(a["rotation"] is JArray rotation&&rotation.Count==4)parts.Add("shortest rotation "+Number(2*Math.Acos(Math.Min(1,Math.Abs((double)rotation[0])))*180/Math.PI)+"°");
            if(a["cuts"]!=null)parts.Add((string)a["cuts"]+" cuts");if(a["slide"]!=null)parts.Add("slide "+Number((double)a["slide"]));
            if(a["segments"]!=null)parts.Add((string)a["segments"]+" segments");
            if(a["path_m"] is JArray path)parts.Add(path.Count+" path samples");
            if(a["variant"]!=null)parts.Add((string)a["variant"]);if(a["domain"]!=null)parts.Add((string)a["domain"]);
            return "Blender accepted"+(parts.Count>0?" · "+string.Join(" · ",parts):"")+(f.Waiting?" · next update pending":"");
        }
        public static Snapshot Build(Frame f)
        {
            var result=new Snapshot();if(f==null||f.Model==null||!Finite(f.Pivot)||!Finite(f.Map.determinant)||Mathf.Abs(f.Map.determinant)<1e-12f)return result;
            for(int i=0;i<16;i++)if(!Finite(f.Map[i]))return result;
            var g=Read(f.Model);if(g==null){result.Limitation="Native topology unavailable";return result;}
            string tool=f.Tool??(string)f.Model["tool"]??"selection",component=f.Component??(string)f.Model["component"]??"object";
            var indices=f.Indices??Array.Empty<int>();var selected=new HashSet<int>();
            foreach(int index in indices)
            {
                if(component=="vertex"&&!g.Vertices.ContainsKey(index)||component=="edge"&&!g.Edges.ContainsKey(index)||component=="face"&&!g.Faces.ContainsKey(index)||!selected.Add(index))continue;
                if(component=="vertex"&&g.Vertices.TryGetValue(index,out var at))Dot(result,f.Map.MultiplyPoint3x4(at),index,0,"selected vertex");
                if(component=="edge"&&g.Edges.TryGetValue(index,out var edge)){Line(result,f.Map.MultiplyPoint3x4(g.Vertices[edge[0]]),f.Map.MultiplyPoint3x4(g.Vertices[edge[1]]),0,"selected edge");foreach(int id in edge)Dot(result,f.Map.MultiplyPoint3x4(g.Vertices[id]),id,0,"edge endpoint");}
                if(component=="face"&&g.Faces.TryGetValue(index,out var face))Outline(result,g,f,face,"selected face boundary");
            }
            if(f.HoverPoint.HasValue)Dot(result,f.HoverPoint.Value,-1,1,"controller target");
            if(f.HoverIndex>=0)
            {
                string hover=f.HoverComponent??component;
                if(hover=="vertex"&&g.Vertices.TryGetValue(f.HoverIndex,out var vertex))Dot(result,f.Map.MultiplyPoint3x4(vertex),f.HoverIndex,1,"hovered native vertex");
                if(hover=="edge"&&g.Edges.TryGetValue(f.HoverIndex,out var edge))Line(result,f.Map.MultiplyPoint3x4(g.Vertices[edge[0]]),f.Map.MultiplyPoint3x4(g.Vertices[edge[1]]),1,"hovered native edge");
                if(hover=="face"&&g.Faces.TryGetValue(f.HoverIndex,out var face))for(int i=0;i<face.Length;i++)Line(result,f.Map.MultiplyPoint3x4(g.Vertices[face[i]]),f.Map.MultiplyPoint3x4(g.Vertices[face[(i+1)%face.Length]]),1,"hovered native face");
            }
            if(f.SnapPoint.HasValue)Dot(result,f.SnapPoint.Value,-1,2,"actual snap target");
            var settings=f.Model["settings"] as JObject??new JObject();string action;
            if(tool=="mesh.extrude")
            {
                bool individual=(bool?)settings["individual"]==true||(string)f.Model["native_tool"]=="builtin.extrude_individual";
                action=individual?"Extrude individual · hold trigger, move along face normals":"Extrude region · hold trigger, "+(f.ExtrudeNormalConstrained?"pull face normal":"move aim");
                int count=0;foreach(int index in selected)if(component=="face"&&g.Faces.TryGetValue(index,out var face)&&count++<24)
                {var at=f.Map.MultiplyPoint3x4(Centre(g,face));var direction=f.Map.MultiplyVector(Normal(g,face,f.NativeObjectMirrored)).normalized;Arrow(result,at,at+direction*.11f,1,"native face normal");}
                if(component!="face")action="Extrude "+component+" · hold trigger and move aim";
                if(!individual&&!f.ExtrudeNormalConstrained&&component=="face")action+=" · yellow: normal reference";
            }
            else if(tool=="mesh.inset")
            {
                action="Inset faces · aim at selection, hold trigger and move for thickness";
                int count=0;foreach(int index in selected)if(component=="face"&&g.Faces.TryGetValue(index,out var face)&&count++<24)
                {var a=f.Map.MultiplyPoint3x4(g.Vertices[face[0]]);var b=f.Map.MultiplyPoint3x4(g.Vertices[face[1]]);Dot(result,(a+b)*.5f,index,1,"inset boundary reference");}
            }
            else if(tool=="mesh.bevel")
            {
                action="Bevel "+((string)settings["affect"]=="VERTICES"?"vertices":"edges")+" · aim at selection, hold trigger and move for width";
                int count=0;foreach(int index in selected)if(component=="edge"&&g.Edges.TryGetValue(index,out var edge)&&count++<24)
                {var a=f.Map.MultiplyPoint3x4(g.Vertices[edge[0]]);var b=f.Map.MultiplyPoint3x4(g.Vertices[edge[1]]);Dot(result,(a+b)*.5f,index,1,"bevel edge reference");}
            }
            else if(tool=="mesh.loop_cut")
            {
                action="Loop cut · aim at one quad edge, hold trigger and move to slide";
                int cuts=Mathf.Clamp((int?)f.Acknowledged?["cuts"]??(int?)settings["cuts"]??1,1,32);float slide=(float?)f.Acknowledged?["slide"]??0;
                if(!LoopPreview(g,f,indices,cuts,slide,result,out string reason)){result.Limitation=reason;action="Loop cut · "+reason;}
                else action+=" · "+(f.Acknowledged==null?"preview ":"")+cuts+" cut"+(cuts==1?"":"s");
            }
            else if(tool=="mesh.knife")
            {
                action="Knife · hold trigger and trace; release applies frozen-view projection\nCut through "+((bool?)settings["cut_through"]==true?"ON":"OFF")+" · selected only "+((bool?)settings["selected_only"]==true?"ON":"OFF");var path=f.KnifePath;
                if(path!=null&&path.Length>0)
                {if(path.Length>128){result.Limitation="Knife exceeds 128 samples; start a new gesture";return result;}int count=path.Length;for(int i=1;i<count;i++)Line(result,f.Map.MultiplyPoint3x4(path[i-1]),f.Map.MultiplyPoint3x4(path[i]),2,"sampled knife path");Dot(result,f.Map.MultiplyPoint3x4(path[0]),-1,1,"knife start");Dot(result,f.Map.MultiplyPoint3x4(path[count-1]),-1,2,"knife end");action+=" · "+count+"/128 sampled points";}
            }
            else if(tool=="mesh.merge"||tool=="mesh.dissolve"||tool=="mesh.delete")
            {
                string variant=(string)settings["variant"]??(string)settings["domain"]??"native setting";
                action=tool.Substring(5)+" · "+variant+" · "+selected.Count+" "+component+" selected\nHold trigger and move to apply once; release = one Undo";
                if(tool=="mesh.merge"&&variant=="DISTANCE"&&settings["distance_m"]!=null)action+="\nDistance threshold "+Number((double)settings["distance_m"]*1000)+" mm";
                if(tool=="mesh.dissolve"&&variant=="LIMITED"&&settings["angle_limit"]!=null)action+="\nAngle limit "+Number((double)settings["angle_limit"]*180/Math.PI)+"°";
                if(tool=="mesh.merge"&&component=="vertex"&&selected.Count>0)
                {
                    bool ordered=(bool?)f.Model["selection"]?["order_complete"]==true;
                    Vector3 target=Vector3.zero;bool known=variant=="CENTER"||(variant=="FIRST"||variant=="LAST")&&ordered;
                    if(variant=="CENTER"){foreach(int id in selected)target+=g.Vertices[id];target/=selected.Count;}
                    else if(variant=="FIRST"||variant=="LAST")
                    {
                        int step=variant=="FIRST"?1:-1;int start=step>0?0:indices.Length-1;
                        for(int i=start;i>=0&&i<indices.Length;i+=step)if(selected.Contains(indices[i])){target=g.Vertices[indices[i]];break;}
                    }
                    if(known){Dot(result,f.Map.MultiplyPoint3x4(target),-1,2,"merge "+variant+" destination");action+="\nCyan: "+variant.ToLowerInvariant()+" destination";}
                    else if(variant=="FIRST"||variant=="LAST"){action+="\nChoose ordered native vertex picks first";result.Limitation="Merge "+variant+" needs complete native selection order";}
                    // CURSOR/DISTANCE never invent an unexported cursor or a
                    // single destination for native merge-by-distance clusters.
                }
            }
            else action=tool.EndsWith(".scale",StringComparison.Ordinal)?"Scale · hold a coloured axis/plane, move; release = one Undo":
                tool.EndsWith(".rotate",StringComparison.Ordinal)?"Rotate · hold a coloured ring and move around it":
                tool.EndsWith(".translate",StringComparison.Ordinal)?"Move · hold a coloured arrow, move along its axis":"Select native "+component+" · trigger tap; SHIFT adds/removes";
            float radius=f.Radius??(float?)settings["proportional_radius_m"]??0;
            if(Finite(radius)&&radius>0)
            {
                bool projected=(bool?)settings["projected"]==true;
                action+="\n"+(projected?"Projected proportional radius ":"Proportional radius ")+Number(radius*1000)+" mm"+((bool?)settings["connected"]==true?" · connected":"")+" · "+((string)settings["proportional_falloff"]??"SMOOTH");
                if(projected)action+=" · native Blender view footprint";
                else for(int axis=0;axis<3;axis++)for(int i=0;i<48;i++)
                {var a=RadiusPoint(f.Pivot,radius,axis,i*Mathf.PI/24);var b=RadiusPoint(f.Pivot,radius,axis,(i+1)*Mathf.PI/24);Line(result,f.Map.MultiplyPoint3x4(a),f.Map.MultiplyPoint3x4(b),3,"native proportional radius");}
            }
            if(f.SnapPoint.HasValue)action+="\nCyan dot: actual native snap target";
            if(!string.IsNullOrWhiteSpace(f.IntentLabel))action+="\n"+f.IntentLabel;
            string readout=Readout(f);result.Label=action+(readout.Length>0?"\n"+readout:"");result.Valid=true;return result;
        }
        public static Vector3 RadiusPoint(Vector3 pivot,float radius,int axis,float angle)
        {var a=axis==0?Vector3.up:Vector3.right;var b=axis==2?Vector3.up:Vector3.forward;return pivot+radius*(a*Mathf.Cos(angle)+b*Mathf.Sin(angle));}
        static string Key(int a,int b)=>a<b?a+":"+b:b+":"+a;
        static bool LoopPreview(Geometry g,Frame f,int[] selection,int cuts,float slide,Snapshot s,out string reason)
        {
            reason="choose exactly one visible edge beside a quad";
            if((f.Component??(string)f.Model["component"])!="edge"||selection.Length!=1||!g.Edges.TryGetValue(selection[0],out var seed))return false;
            var edgeIds=new Dictionary<string,int>();foreach(var pair in g.Edges)edgeIds[Key(pair.Value[0],pair.Value[1])]=pair.Key;
            var oriented=new Dictionary<int,int[]> {{selection[0],new[]{seed[0],seed[1]}}};var queue=new Stack<int>();queue.Push(selection[0]);
            bool besideQuad=false;var links=new List<int[]>();var linkKeys=new HashSet<string>();
            while(queue.Count>0)
            {
                int current=queue.Pop();var rail=oriented[current];
                foreach(var face in g.Faces.Values)
                {
                    if(face.Length!=4)continue;int position=-1;
                    for(int i=0;i<4;i++)if(Key(face[i],face[(i+1)%4])==Key(rail[0],rail[1])){position=i;break;}
                    if(position<0)continue;besideQuad=true;int oppositeA=face[(position+2)%4],oppositeB=face[(position+3)%4];
                    if(!edgeIds.TryGetValue(Key(oppositeA,oppositeB),out int opposite))continue;
                    int paired=rail[0]==face[position]?face[(position+3)%4]:face[(position+2)%4];int other=paired==oppositeA?oppositeB:oppositeA;
                    if(oriented.TryGetValue(opposite,out var previous))
                    {if(previous[0]!=paired||previous[1]!=other){reason="conflicting quad slide orientation; choose another edge";return false;}}
                    else {oriented[opposite]=new[]{paired,other};queue.Push(opposite);}
                    string key=Key(current,opposite);if(linkKeys.Add(key))links.Add(new[]{current,opposite});
                }
            }
            if(!besideQuad)return false;
            // No preview is published before the whole rail graph is validated.
            foreach(var link in links)for(int cut=1;cut<=cuts;cut++)
            {float t=(float)cut/(cuts+1);t+=Mathf.Clamp(slide,-.999f,.999f)*(slide>=0?1-t:t);var a=oriented[link[0]];var b=oriented[link[1]];Line(s,f.Map.MultiplyPoint3x4(Vector3.Lerp(g.Vertices[a[0]],g.Vertices[a[1]],t)),f.Map.MultiplyPoint3x4(Vector3.Lerp(g.Vertices[b[0]],g.Vertices[b[1]],t)),1,"quad ring preview");}
            var start=f.Map.MultiplyPoint3x4(g.Vertices[seed[0]]);var end=f.Map.MultiplyPoint3x4(g.Vertices[seed[1]]);var mid=(start+end)*.5f;var dir=(end-start).normalized*.06f;
            Arrow(s,mid-dir,mid+dir,2,"positive slide direction");reason="";return true;
        }
        public void Draw(Frame frame,Camera camera)
        {
            Last=Build(frame);if(!Last.Valid){Hide();return;}Ensure();root.SetActive(true);
            Vector3 pivot=frame.Map.MultiplyPoint3x4(frame.Pivot);float distance=camera!=null?Vector3.Distance(camera.transform.position,pivot):1;
            float width=Mathf.Clamp(distance*.0022f,.0025f,.007f),radius=Mathf.Clamp(distance*.0045f,.004f,.013f);
            int index=0;foreach(var segment in Last.Segments){var line=Acquire(lines,index++,"Native tool guide");line.sharedMaterial=materials[segment.Colour];line.startWidth=line.endWidth=width;line.positionCount=2;line.SetPosition(0,segment.A);line.SetPosition(1,segment.B);line.gameObject.SetActive(true);}for(;index<lines.Count;index++)lines[index].gameObject.SetActive(false);
            Vector3 right=camera!=null?camera.transform.right:Vector3.right,up=camera!=null?camera.transform.up:Vector3.up;index=0;
            foreach(var point in Last.Points){var dot=Acquire(dots,index++,"Native component point");dot.sharedMaterial=materials[point.Colour];dot.startWidth=dot.endWidth=width;dot.positionCount=13;for(int i=0;i<=12;i++)dot.SetPosition(i,point.Position+radius*(right*Mathf.Cos(i*Mathf.PI/6)+up*Mathf.Sin(i*Mathf.PI/6)));dot.gameObject.SetActive(true);}for(;index<dots.Count;index++)dots[index].gameObject.SetActive(false);
        }
        LineRenderer Acquire(List<LineRenderer> pool,int index,string name)
        {
            if(index<pool.Count)return pool[index];var go=new GameObject(name);go.transform.SetParent(root.transform,false);var line=go.AddComponent<LineRenderer>();line.useWorldSpace=true;line.numCapVertices=3;line.shadowCastingMode=ShadowCastingMode.Off;line.receiveShadows=false;pool.Add(line);return line;
        }
        void Ensure()
        {
            if(root!=null)return;root=new GameObject("Native Blender contextual guides");var shader=Shader.Find("UI/Default")??Shader.Find("Unlit/Color");
            for(int i=0;i<materials.Length;i++){var material=new Material(shader){name="Native guide "+i,renderQueue=4000};material.color=Colours[i];if(material.HasProperty("_BaseColor"))material.SetColor("_BaseColor",Colours[i]);material.SetInt("unity_GUIZTestMode",(int)CompareFunction.Always);if(material.HasProperty("_ZTest"))material.SetInt("_ZTest",(int)CompareFunction.Always);if(material.HasProperty("_ZWrite"))material.SetInt("_ZWrite",0);materials[i]=material;}
            // Contextual geometry stays visible without automatic instructional
            // writing. Detailed steps live in the deliberately opened Guide.
        }
        public void Hide(){if(root!=null)root.SetActive(false);}
        public void Dispose(){if(root!=null)Release(root);foreach(var material in materials)if(material!=null)Release(material);root=null;lines.Clear();dots.Clear();Last=null;}
        static void Release(UnityEngine.Object value){if(Application.isPlaying)UnityEngine.Object.Destroy(value);else UnityEngine.Object.DestroyImmediate(value);}
    }
}
