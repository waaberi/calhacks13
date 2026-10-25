using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // Selection intent has no OS key ownership and does not mutate geometry.
    // SHIFT may stay visibly latched while synthetic native keys are released.
    public sealed class NativeSpatialSelection
    {
        readonly List<string> order = new List<string>();
        readonly Dictionary<string,long> generations = new Dictionary<string,long>();
        readonly List<int> components = new List<int>();
        public long Epoch { get; private set; }
        public bool Additive { get; private set; }
        public string ActiveId { get; private set; } = "";
        public string Component { get; private set; } = "object";
        public string TopologyToken { get; private set; } = "";
        public IReadOnlyList<string> ObjectIds => order;
        public IReadOnlyList<int> Indices => components;
        public void InvalidateIntent() => Epoch++;
        public void SetAdditive(bool value) { if(Additive==value)return;Additive=value;Epoch++; }
        public void Clear()
        { if(order.Count==0&&components.Count==0)return;order.Clear();generations.Clear();components.Clear();ActiveId="";Epoch++; }
        public bool Contains(string id,string component,int index)
            => generations.ContainsKey(id) && (component=="object" || (Component==component&&ActiveId==id&&components.Contains(index)));
        public void Pick(string id,long generation,string component,int index,string token,bool drag)
        {
            if(string.IsNullOrEmpty(id))return;
            bool has=Contains(id,component,index);
            if(drag&&has)return;
            bool sameDomain=Component==component&&(component=="object"||ActiveId==id);
            if(!Additive||!sameDomain)
            {
                if(!drag&&has&&order.Count==1&&(component=="object"||components.Count==1)) { Clear();return; }
                order.Clear();generations.Clear();components.Clear();
            }
            if(component=="object")
            {
                if(Additive&&has&&!drag) { order.Remove(id);generations.Remove(id); }
                else { if(!generations.ContainsKey(id))order.Add(id);generations[id]=generation; }
            }
            else
            {
                if(!generations.ContainsKey(id))order.Add(id);generations[id]=generation;
                if(Additive&&has&&!drag)components.Remove(index);else if(!components.Contains(index))components.Add(index);
                if(components.Count==0){order.Clear();generations.Clear();}
            }
            Component=component;ActiveId=order.Count==0?"":order[order.Count-1];TopologyToken=token??"";Epoch++;
        }
        public void ObserveNative(JObject model,Dictionary<string,JObject> objects,bool admitSelection)
        {
            if(model==null)return;
            string token=(string)model["topology_token"]??"";
            if(TopologyToken!=token){TopologyToken=token;Epoch++;}
            bool removed=false;
            foreach(string id in order.ToArray())
                if(!objects.TryGetValue(id,out var obj)){order.Remove(id);generations.Remove(id);removed=true;}
                else generations[id]=(long?)obj["generation"]??0;
            if(removed){components.Clear();ActiveId=order.LastOrDefault()??"";Epoch++;}
            if(!admitSelection||!(model["selection"] is JObject selected))return;
            var snapshot=Snapshot();
            if(selected["objects"] is JArray nativeObjects)
            {
                order.Clear();generations.Clear();
                foreach(var entry in nativeObjects)
                {
                    string id=entry.Type==JTokenType.String?(string)entry:(string)entry["id"];
                    if(string.IsNullOrEmpty(id)||!objects.TryGetValue(id,out var record))continue;
                    order.Add(id);generations[id]=(long?)record["generation"]??0;
                }
            }
            Component=(string)selected["component"]??(string)model["component"]??"object";
            ActiveId=(string)selected["active_id"]??order.LastOrDefault()??"";
            components.Clear();if(selected["indices"] is JArray indices)foreach(int index in indices.Values<int>())if(!components.Contains(index))components.Add(index);
            if(!JToken.DeepEquals(snapshot,Snapshot()))Epoch++;
        }
        public JObject Snapshot()
        {
            var value=new JObject { ["objects"]=new JArray(order.Select(id=>(object)new JObject { ["id"]=id,["generation"]=generations[id] })),
                ["active_id"]=ActiveId,["component"]=Component,["indices"]=new JArray(components),["topology_token"]=TopologyToken };
            using(var sha=SHA256.Create())value["selection_token"]=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value.ToString(Formatting.None)))).Replace("-","").ToLowerInvariant();
            return value;
        }
        public JArray Targets()=>new JArray(order.Select(id=>(object)new JObject { ["id"]=id,["generation"]=generations[id] }));
    }
}
