using System;
using System.Reflection;
using SpatialModeling;
using SpatialModeling.VoiceCore;
using UnityEngine;

public static class VoiceDialogChecks
{
    static void Check(bool value,string message) { if(!value)throw new Exception("VOICE_DIALOG: "+message); }
    static void Tick(PendingCommandPanel panel) => typeof(PendingCommandPanel).GetMethod("LateUpdate",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(panel,null);
    public static void Run()
    {
        var head=new GameObject("isolated voice dialog head");
        var go=new GameObject("isolated voice dialog");
        try
        {
            var panel=go.AddComponent<PendingCommandPanel>();
            if(go.GetComponent<TextMesh>()==null)typeof(PendingCommandPanel).GetMethod("Awake",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(panel,null);
            panel.head=head.transform;
            string body="Review all requested operations\n";
            for(int i=0;i<24;i++)body+="Step "+i+": inset thickness 2 mm; use inner faces from previous step.\n";
            panel.ShowComposition(body,DateTime.UtcNow.AddSeconds(120),true);Tick(panel);
            Vector3 position=go.transform.position;Quaternion rotation=go.transform.rotation;
            Check(!panel.AllPagesReviewed,"long review cannot be confirmed before all text pages are visited");
            head.transform.SetPositionAndRotation(new Vector3(.5f,.2f,.1f),Quaternion.Euler(20,45,0));Tick(panel);
            Check(go.transform.position==position&&go.transform.rotation==rotation,"open dialog stays in world space while wearer looks around");
            var bounds=go.GetComponent<MeshRenderer>().localBounds;var scale=go.transform.localScale;
            Check(bounds.size.x*scale.x<=.951f&&bounds.size.y*scale.y<=.651f,"complete visible page fits bounded central view");
            Check(go.GetComponent<TextMesh>().anchor==TextAnchor.MiddleCenter,"page grows around view center rather than above it");
            for(int i=0;i<100;i++)panel.MovePage(1);
            Check(panel.AllPagesReviewed,"all detail pages can be reached");
            panel.ShowComposition(body,DateTime.UtcNow.AddSeconds(110),true);
            Check(panel.AllPagesReviewed,"countdown refresh preserves reading progress");
            panel.ShowComposition(body+"new operation",DateTime.UtcNow.AddSeconds(120),true);
            Check(!panel.AllPagesReviewed,"new plan invalidates prior page acceptance");
            panel.Hide();Check(!panel.Visible,"cancel hides world dialog");
            var session=new VoiceSession(new VoiceSessionOptions{AskHost=false},()=>DateTime.UtcNow);
            var turn=session.Hear(new RecognitionResult(VoiceDialogPages.BasicCreation("Add a cube to the scene."),1));
            Check(turn.Command?.Kind==CommandKind.AddShape,"physical phrase resolves directly through basic creation");
            var command=HostCommand.From(turn.Command);
            Check(command.Op=="object.add"&&(double)((double[])command.Args["dimensions"])[0]==HostCommand.DefaultAddSize,
                "basic creation preserves app defaults instead of invented two metre geometry");
            Debug.Log("VOICE_DIALOG_CHECK PASS world anchor/head-turn/bounded full page/all-detail review fence/countdown/new-plan reset/exact physical cube phrase; no microphone, service or user model edits");
        }
        finally { UnityEngine.Object.DestroyImmediate(go);UnityEngine.Object.DestroyImmediate(head); }
    }
}
