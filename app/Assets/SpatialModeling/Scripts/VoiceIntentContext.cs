using System;
using System.Linq;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;

namespace SpatialModeling
{
    // Interpretation hints are separate from the native fingerprint. A VR
    // selection identifies an intended object; it never invents mesh selection.
    public static class VoiceIntentContext
    {
        public static bool NeedsInterpretation(string text) =>
            Regex.IsMatch(text ?? "", @"\b(resize|smaller|bigger|larger|shrink|grow|halve|double|half|twice)\b|\b(scale|size)\b.*\b(down|up)\b",RegexOptions.IgnoreCase);

        public static JObject SelectedObject(JObject native,string id)
        {
            if ((string)native?["mode"] != "OBJECT" || string.IsNullOrEmpty(id)) return new JObject();
            var row=(native["objects"] as JArray)?.OfType<JObject>().FirstOrDefault(item=>(string)item["id"]==id);
            return row==null ? new JObject() : new JObject { ["selected_object"]=row.DeepClone() };
        }

        public static bool CanRebindTarget(JObject before,JObject after,JArray missing)
        {
            if(before==null||after==null||missing==null||!missing.Any(value=>
                Regex.IsMatch((string)value??"",@"^(target|object|object_id|target_id|target_object)$",RegexOptions.IgnoreCase)))return false;
            if((string)before["mode"]!="OBJECT"||(string)after["mode"]!="OBJECT"
                ||(bool?)before["gesture_active"]==true||(bool?)after["gesture_active"]==true)return false;
            var a=(JObject)before.DeepClone();var b=(JObject)after.DeepClone();
            // Only the explicit answer's selection can change. Document/revision,
            // generations, topology, options, mode and tool remain fenced.
            foreach(string key in new[]{"selection","native_selection","gesture_epoch"}){a.Remove(key);b.Remove(key);}
            return JToken.DeepEquals(a,b);
        }
    }
}
