using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using SpatialModeling;

public static class LiveSelectionManagedChecks
{
    static int checks;
    static void Check(bool value,string why){checks++;if(!value)throw new Exception(why);}
    public static int Main()
    {
        try
        {
            var selected=new NativeSpatialSelection();
            selected.Pick("a",3,"object",-1,"ta",false);Check(selected.ActiveId=="a","tap selects");
            selected.SetAdditive(true);selected.Pick("b",4,"object",-1,"tb",false);
            Check(selected.ObjectIds.SequenceEqual(new[]{"a","b"}),"sticky shift adds");
            var snapshot=selected.Snapshot();snapshot["objects"][0]["generation"]=999;
            Check((long)selected.Snapshot()["objects"][0]["generation"]==3,"detached snapshot cannot mutate selection");
            selected.Pick("a",3,"object",-1,"ta",true);Check(selected.ObjectIds.Count==2,"drag preserves selected group");
            selected.Pick("a",3,"object",-1,"ta",false);Check(selected.ObjectIds.SequenceEqual(new[]{"b"}),"shift toggles removal");
            selected.SetAdditive(false);selected.Pick("b",4,"object",-1,"tb",false);Check(selected.ObjectIds.Count==0,"repeat plain tap deselects");
            selected.Pick("a",3,"face",7,"mesh",false);selected.SetAdditive(true);selected.Pick("a",3,"face",2,"mesh",false);
            Check(selected.Indices.SequenceEqual(new[]{7,2}),"ordered components preserve FIRST/LAST semantics");
            selected.Pick("a",3,"face",7,"mesh",false);Check(selected.Indices.SequenceEqual(new[]{2}),"exact component removal");
            string before=(string)selected.Snapshot()["selection_token"];long epoch=selected.Epoch;
            selected.InvalidateIntent();selected.InvalidateIntent();Check(selected.Epoch==epoch+2,"transient gesture changes epoch");
            Check((string)selected.Snapshot()["selection_token"]==before,"same final selection remains independently fenced by epoch");
            var objects=new Dictionary<string,JObject> { ["a"]=new JObject { ["id"]="a",["generation"]=9 } };
            var model=new JObject { ["topology_token"]="new mesh",["selection"]=new JObject { ["objects"]=new JArray(new JObject { ["id"]="a",["generation"]=9 }),["active_id"]="a",["component"]="edge",["indices"]=new JArray(3,5) } };
            selected.ObserveNative(model,objects,true);Check(selected.Component=="edge"&&selected.Indices.SequenceEqual(new[]{3,5}),"native menu selection imported");
            Check((long)selected.Snapshot()["objects"][0]["generation"]==9,"actual fresh generation imported");
            selected.Pick("a",9,"edge",8,"new mesh",false);selected.ObserveNative(model,objects,false);
            Check(selected.Indices.Contains(8),"unacknowledged local picks are not overwritten by an older native query");
            objects.Clear();selected.ObserveNative(model,objects,false);Check(selected.ObjectIds.Count==0&&selected.Indices.Count==0,"deleted target cannot remain selected");
            Console.WriteLine("LIVE_SELECTION_MANAGED_CHECK PASS checks="+checks+" actual selection state; no Unity/native/runtime invocation");return 0;
        }
        catch(Exception e){Console.Error.WriteLine(e);return 1;}
    }
}
