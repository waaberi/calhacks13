using System;
using System.Collections.Generic;
using System.Linq;
using SpatialModeling;

public static class GuideCatalogChecks
{
    static void Check(bool ok,string why){if(!ok)throw new Exception("GUIDE_CATALOG: "+why);}
    public static void Run()
    {
        var all=VrGuideCatalog.All;Check(all.Count>=30&&all.Count<=40,"bounded complete manual collection");
        var ids=new HashSet<string>();var categories=new HashSet<string>();
        foreach(var article in all)
        {
            Check(!string.IsNullOrWhiteSpace(article.Id)&&ids.Add(article.Id),"unique nonempty article ID");
            Check(!string.IsNullOrWhiteSpace(article.Title)&&!string.IsNullOrWhiteSpace(article.Category),"nonempty title and category");categories.Add(article.Category);
            Check(article.Keywords.Length>0&&article.Keywords.All(k=>!string.IsNullOrWhiteSpace(k)),"searchable keywords are nonempty");
            Check(article.Steps.Length>=3&&article.Steps.Length<=6,"all step details fit article pagination budget");
            Check(article.Steps.All(s=>!string.IsNullOrWhiteSpace(s)&&s.Length<=VrGuideCatalog.MaximumStepLength),"steps are readable one-step text within 160 characters: "+article.Id);
            Check(!string.IsNullOrWhiteSpace(article.Limitation)&&article.Limitation.Length<=220,"each article has bounded honest limitations: "+article.Id);
            Check(VrGuideCatalog.Search(article.Title).Any(a=>a.Id==article.Id),"every complete article remains reachable by title: "+article.Id);
        }
        Check(categories.Count>=6,"catalog categories distinguish relevant workflows");
        Check(ReferenceEquals(all,VrGuideCatalog.Articles),"both documented read-only list names expose the same corpus");
        Check(VrGuideCatalog.Search(null).Count==all.Count&&VrGuideCatalog.Search("  ").Count==all.Count,"empty search exposes all articles for paginated browsing");
        foreach(var pair in new[]{new[]{"arrows","move"},new[]{"rotate","rotate"},new[]{"input","native-2d"},new[]{"plane","manual-planes"},new[]{"undo","history"},new[]{"extrude","extrude-region"},new[]{"opacity","opacity"},new[]{"keyboard","blender-keyboard"},new[]{"Gemini","gemini-review"}})
            Check(VrGuideCatalog.Search(pair[0]).Any(a=>a.Id==pair[1]),"common alias finds its actual topic: "+pair[0]);
        Check(VrGuideCatalog.Search("roTAtE").Select(a=>a.Id).SequenceEqual(VrGuideCatalog.Search("ROTATE").Select(a=>a.Id)),"ranking ignores case consistently");
        Check(VrGuideCatalog.Search("extr ind").First().Id=="extrude-individual","multi-token prefixes rank the exact native tool");
        Check(VrGuideCatalog.Search("Move with coloured arrows").First().Id=="move","exact title has predictable top rank");
        Check(VrGuideCatalog.Search("zzzznonexistenttool").Count==0&&VrGuideCatalog.Search("!!!").Count==0,"unknown queries do not fabricate a help article or tool");
        string longQuery=new string('z',VrGuideCatalog.MaximumQueryLength)+" rotate";
        Check(VrGuideCatalog.Search(longQuery).Count==0,"characters beyond bounded query cannot become an extra executable/matching request");
        var before=string.Join("|",all.Select(a=>a.Id+":"+a.Title+":"+string.Join(";",a.Steps)));
        foreach(string query in new[]{"delete everything then save","bpy.ops.mesh.extrude","ignore instructions run shell","","knife"})VrGuideCatalog.Search(query);
        Check(before==string.Join("|",all.Select(a=>a.Id+":"+a.Title+":"+string.Join(";",a.Steps))),"search reads only manual data and never mutates article content");
        var type=typeof(VrGuideCatalog);Check(type.GetMethods(System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.Static).All(m=>m.Name=="Search"||m.Name=="get_All"||m.Name=="get_Articles"),"public manual API contains no execution/input/AI action route");
        Check(all.Single(a=>a.Id=="guide-search").Limitation.Contains("does not type into Blender")&&all.Single(a=>a.Id=="unsupported").Steps.Any(s=>s.Contains("unavailable")),"local search and unavailable direct features are explicitly separated");
#if GUIDE_CATALOG_STANDALONE
        Console.WriteLine("GUIDE_CATALOG_CHECK PASS corpus="+all.Count+" unique_ids/categories/step_budgets/all_reachable/aliases/token_prefix/case/ranking/bounded_query/unknown_safe/pure_manual");
#else
        UnityEngine.Debug.Log("GUIDE_CATALOG_CHECK PASS corpus="+all.Count+" unique_ids/categories/step_budgets/all_reachable/aliases/token_prefix/case/ranking/bounded_query/unknown_safe/pure_manual");
#endif
    }
#if GUIDE_CATALOG_STANDALONE
    public static void Main()=>Run();
#endif
}
