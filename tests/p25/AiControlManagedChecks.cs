using System;
using System.Reflection;

// Executes the actual client classifier without initializing Unity, microphones,
// Gemini, a native host or any socket. Editor routing coverage is separate.
public static class AiControlManagedChecks
{
    public static int Main()
    {
        var control=Assembly.LoadFrom("Assembly-CSharp.dll").GetType("SpatialModeling.VoiceUiAdapter")
            .GetMethod("Control",BindingFlags.Static|BindingFlags.NonPublic);
        int count=0;
        foreach(string phrase in new[]{"undo","undo that","undo the move","redo","redo that","redo that rotate","cancel","cancel that","never mind","save","save file","save the file","save project"})
        {if(!(bool)control.Invoke(null,new object[]{phrase}))throw new Exception("Core control routed toward AI: "+phrase);count++;}
        foreach(string phrase in new[]{"bevel selected faces","inset it two millimeters","knife across the selected face","save the file then bevel it"})
        {if((bool)control.Invoke(null,new object[]{phrase}))throw new Exception("Modeling/compound phrase classified as standalone control: "+phrase);count++;}
        Console.WriteLine("AI_CONTROL_MANAGED_CHECK PASS checks="+count+" actual client/core classifier; no Unity or AI/native runtime");return 0;
    }
}
