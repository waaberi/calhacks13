using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SpatialModeling.VoiceCore;
using SpatialModeling.VoiceCore.Whisper;
using UnityEngine;

namespace SpatialModeling
{
    public partial class VoiceUiAdapter
    {
        public bool aiMode = true;
        public string geminiModel = "";
        public bool AiAvailable => ai != null && ai.Available && aiTools.Count > 0;
        GeminiVoiceInterpreter ai;
        JArray aiTools = new JArray(), aiReview;
        JObject aiPendingDraft, aiExpectedContext;
        string aiRecipeRequest, aiOriginal, aiQuestion, aiFingerprint, aiRunResolution, aiSubmittedCommand;
        DateTime aiQuestionUntil;
        int aiSequence;
        bool aiBusy;
        void InitializeAi() { ai = new GeminiVoiceInterpreter(geminiModel); }
        public void SetAi(bool enabled) { InvalidateAi(); aiMode = enabled; }
        void AcceptAiCatalog(JObject grammar)
        { aiTools = (int?)grammar["recipe_version"] == 1 && grammar["tools"] is JArray tools ? (JArray)tools.DeepClone() : new JArray(); }
        bool InvalidateAi()
        {
            bool alreadySent = host != null && host.IsCommandInFlight(aiSubmittedCommand);
            if(aiSubmittedCommand!=null&&!alreadySent)
            {
                host?.CancelQueuedAiCommand(aiSubmittedCommand,"AI edit cancelled before native input release. No edit was sent.");
                aiSubmittedCommand=null;
            }
            bool owned = aiBusy || aiRecipeRequest != null || aiReview != null || aiQuestion != null || aiRunResolution != null;
            if (aiReview != null) deleteWaiting = null;
            if (owned) session?.Cancel();
            aiSequence++; ai?.Cancel(); aiBusy = false; aiQuestion = aiRecipeRequest = null;
            aiPendingDraft = aiExpectedContext = null; aiReview = null;
            aiRunResolution = null;
            return alreadySent;
        }
        bool IsAiRun(HostCommand command) => command.Op == HostCommand.RunOp && aiRunResolution != null
            && command.Args.TryGetValue("resolution",out var resolution) && (string)resolution == aiRunResolution;
        void TrackAiCommand(string id)
        {
            aiSubmittedCommand=id;
            // Queuing intentionally cancels any local direct draft while native
            // input releases. Capture that own epoch transition, then reject any
            // subsequent context change before this command crosses the wire.
            aiFingerprint=CaptureAiContext().ToString(Formatting.None);
        }
        void CompleteAiCommand(string id)
        {if(id==aiSubmittedCommand){aiSubmittedCommand=null;aiRunResolution=null;}}
        bool AiContextCurrent() => host != null && host.HasCurrentScene && aiFingerprint != null
            && CaptureAiContext().ToString(Formatting.None)==aiFingerprint;
        JObject CaptureAiContext()
        {
            var preview = PreviewInteraction.Current; var drawing = preview?.Drawing;
            var model = drawing?.NativeState["model_edit"] as JObject ?? new JObject();
            var nativeSelection = model["selection"] as JObject ?? new JObject();
            string mode=(string)model["mode"]??(string)drawing?.NativeState["mode"]??"OBJECT";
            var shown = new List<KeyValuePair<string,string>>(); host.GetVisibleNativeObjects(shown);
            var visible=new HashSet<string>(shown.Select(obj=>obj.Key),StringComparer.Ordinal);
            var selected=(JObject)nativeSelection.DeepClone();
            selected["component"]=(string)nativeSelection["component"]??(string)model["component"]??"object";
            selected["indices"]=nativeSelection["indices"]?.DeepClone()??new JArray();
            selected["active_id"]=(string)nativeSelection["active_id"]??(string)model["active_object_id"]??"";
            selected["topology_token"]=(string)model["topology_token"]??"";
            var selectedObjects=new JArray();
            if(nativeSelection["objects"] is JArray nativeObjects)foreach(var entry in nativeObjects)
            {
                string id=entry is JObject row?(string)row["id"]:(string)entry;
                if(id==null||!visible.Contains(id)||!host.TryGetGeneration(id,out long generation))continue;
                selectedObjects.Add(new JObject { ["id"]=id,["generation"]=entry is JObject record?record["generation"]?.DeepClone()??new JValue(generation):new JValue(generation) });
            }
            selected["objects"]=selectedObjects;
            // Native selection is authoritative outside an acknowledged current
            // spatial domain. In particular, an old mesh snapshot must not mask
            // Pose Mode or resurrect a natively cleared Object Mode selection.
            var direct=preview?.DirectEditing;var spatial=direct?.SelectionSnapshot;
            if(direct!=null&&direct.Active&&drawing.NativeStateCurrent&&(bool?)model["live_supported"]==true
                &&nativeSelection["objects"] is JArray&&nativeSelection["indices"] is JArray
                &&(mode=="OBJECT"||mode=="EDIT_MESH")&&SpatialSelectionAcknowledged(spatial,selected,model,mode))
                selected=spatial;
            var objects = new JArray();
            foreach (var obj in shown)
                if (host.TryGetGeneration(obj.Key, out long generation)) objects.Add(new JObject { ["id"] = obj.Key, ["name"] = obj.Value, ["generation"] = generation });
            return new JObject { ["document_id"] = host.DocumentId, ["open_epoch"] = host.OpenEpoch, ["revision"] = host.Revision,
                ["mode"] = mode,
                ["native_tool"] = (string)model["native_tool"] ?? "", ["topology_token"] = (string)model["topology_token"] ?? "",
                ["options"] = model["options"]?.DeepClone() ?? model["settings"]?.DeepClone() ?? new JObject(),
                ["native_selection"] = nativeSelection.DeepClone(),
                ["selection"] = selected.DeepClone(), ["objects"] = objects,
                ["gesture_epoch"] = preview?.DirectEditing?.ContextEpoch ?? 0,
                ["gesture_active"] = preview?.DirectEditing?.Gesturing == true || preview?.DirectEditing?.LiveBusy == true || drawing?.Session.ExternalEditBusy == true };
        }
        bool SpatialSelectionAcknowledged(JObject spatial,JObject native,JObject model,string mode)
        {
            if(spatial==null||(string)spatial["component"]!=(string)native["component"]
                ||(string)spatial["active_id"]!=(string)native["active_id"]
                ||(string)spatial["topology_token"]!=((string)model["topology_token"]??""))return false;
            if(mode=="OBJECT"&&(string)spatial["component"]!="object")return false;
            if(mode=="EDIT_MESH"&&((string)native["active_id"]!=(string)model["active_object_id"]
                ||(string)spatial["component"]=="object"))return false;
            if(!(spatial["indices"] is JArray indices)||!(native["indices"] is JArray nativeIndices)
                ||!JToken.DeepEquals(indices,nativeIndices))return false;
            if(!(spatial["objects"] is JArray objects)||!(native["objects"] is JArray nativeObjects)||objects.Count!=nativeObjects.Count)return false;
            if(mode=="EDIT_MESH"&&(objects.Count!=1||(string)objects[0]["id"]!=(string)model["active_object_id"]))return false;
            for(int i=0;i<objects.Count;i++)
            {
                string id=(string)objects[i]["id"];
                if(id!=(string)nativeObjects[i]["id"]||!host.TryGetGeneration(id,out long generation)
                    ||(long?)objects[i]["generation"]!=generation||(long?)nativeObjects[i]["generation"]!=generation)return false;
            }
            return true;
        }
        void TickAi()
        {
            if (aiQuestion != null && DateTime.UtcNow >= aiQuestionUntil) { aiQuestion = null; Note("AI question expired. Say the complete edit again."); }
            if ((aiBusy || aiQuestion != null || aiRecipeRequest != null || aiReview != null || (host != null && host.IsCommandQueued(aiSubmittedCommand)))
                && (!host.HasCurrentScene || CaptureAiContext().ToString(Formatting.None) != aiFingerprint))
            { InvalidateAi(); Note("Blender context changed. Say the complete edit again."); }
        }
        bool KnownBasic(string text)
        {
            var words = new HashSet<string>(session.GrammarPhrases().SelectMany(AiWords), StringComparer.OrdinalIgnoreCase);
            foreach (var obj in session.Objects) foreach (string word in AiWords(obj.Name)) words.Add(word);
            return AiWords(text).All(word => words.Contains(word) || double.TryParse(word, out _));
        }
        static IEnumerable<string> AiWords(string text) => Regex.Matches((text ?? "").ToLowerInvariant(), @"[a-z]+|[-+]?(?:\d+(?:\.\d*)?|\.\d+)").Cast<Match>().Select(match => match.Value);
        static bool Control(string text)
        {
            string bounded=Regex.Replace((text??"").Trim(),@"[.!?]+$","").Trim();
            if(Regex.IsMatch(bounded,@"^(never\s+mind|save(?:\s+(?:the\s+)?(?:file|project))?)$",RegexOptions.IgnoreCase))return true;
            // Use the existing core parser for its full Undo/Redo/Cancel
            // vocabulary (e.g. 'undo that' and 'redo that rotate'). The actual
            // session still owns confidence, composition and command execution.
            var core=new VoiceSession(new VoiceSessionOptions { AskHost=false },()=>DateTime.UtcNow);
            var kind=core.Hear(new RecognitionResult(bounded,1)).Command?.Kind;
            return kind==CommandKind.Undo||kind==CommandKind.Redo||kind==CommandKind.Cancel;
        }
        void HearOrInterpret(RecognitionResult result, bool fromMic)
        {
            string text = fromMic ? RawAiTranscript() ?? result.Text : result.Text;
            string navigation = Regex.Replace(text.Trim(), @"[.!?]+$", "").Trim();
            if (panel.Visible && Regex.IsMatch(navigation, @"^(next|next page|previous|previous page|back)$", RegexOptions.IgnoreCase)
                && panel.MovePage(navigation.StartsWith("next",StringComparison.OrdinalIgnoreCase) ? 1 : -1)) return;
            if (Control(text) || session.Pending != null || session.Choice != null || session.CompositionQuestion != null || session.WaitingForHost)
            { Handle(session.Hear(result)); return; }
            bool mesh = (string)(PreviewInteraction.Current?.Drawing?.NativeState["model_edit"] as JObject)?["mode"] == "EDIT_MESH";
            string creation = !mesh && aiQuestion == null ? VoiceDialogPages.BasicCreation(text) : null;
            if (creation != null)
            {
                // Preserve the app's small, beside-selection Add defaults. Never
                // ask a model to invent Blender's two-metre cube for this phrase.
                Debug.Log("VOICE basic creation normalized to " + creation);
                Handle(session.Hear(new RecognitionResult(creation,result.Confidence))); return;
            }
            bool newTool = Regex.IsMatch(text, @"\b(extrude|inset|knife|loop\s*cut|dissolve|proportional|snapping)\b|\b(bevel|merge|delete)\b.*\b(vertices|edges|faces|selected)\b", RegexOptions.IgnoreCase);
            if (!aiMode || !AiAvailable || (aiQuestion == null && !mesh && !newTool && KnownBasic(text)))
            { Handle(session.Hear(result)); return; }
            if (result.Confidence < .5f) { Enqueue(Prompt.LowConfidence,null); return; }
            string request;
            try { request = GeminiVoiceInterpreter.ComposeRequest(aiOriginal,aiQuestion,text); }
            catch (FormatException) { aiQuestion = null; Note("That request is too long. Repeat a shorter complete edit."); return; }
            aiOriginal = request; aiQuestion = null;
            StartAiRecipe(request);
        }
        string RawAiTranscript()
        {
            object recognizer = activeRecognizer;
            if (recognizer is FastPathRecognizer fast) { if (!fast.LastOutcome.ToString().StartsWith("Slow")) return null; recognizer = fast.Slow; }
            return (recognizer as WhisperServerRecognizer)?.LastTranscript;
        }
        bool TryInterpretUnmatched(NoResultReason why)
        {
            if (why == NoResultReason.Silence || !aiMode || !AiAvailable) return false;
            string raw = RawAiTranscript(); if (string.IsNullOrWhiteSpace(raw)) return false;
            HearOrInterpret(new RecognitionResult(raw,1),false); return true;
        }
        void StartAiRecipe(string text)
        {
            aiSequence++; ai?.Cancel(); int sequence = aiSequence;
            var context = CaptureAiContext();
            if (context["options"]?["native_context_fingerprint_unavailable"] != null)
            { Note("The complete Blender context could not be captured. Narrow the visible scene and repeat the edit."); return; }
            if ((bool?)context["gesture_active"] == true || PreviewInteraction.Current?.Drawing?.Session.Busy == true)
            { Note("Finish or cancel the current controller edit before asking for an AI edit."); return; }
            aiExpectedContext = context; aiFingerprint = context.ToString(Formatting.None); aiBusy = true;
            resultLine = "Preparing the complete AI editing plan";
            StartCoroutine(AwaitAiRecipe(sequence,text,context));
        }
        IEnumerator AwaitAiRecipe(int sequence, string text, JObject context)
        {
            GeminiVoiceInterpreter.Answer answer = null;
            yield return ai.Interpret(text,context,aiTools,() => sequence == aiSequence && aiBusy && host.HasCurrentScene
                && CaptureAiContext().ToString(Formatting.None) == aiFingerprint, value => answer = value);
            if (sequence != aiSequence) yield break;
            aiBusy = false;
            if (answer?.Draft == null || answer.Error != null)
            { Debug.Log("VOICE AI preparation refused: " + (answer?.Error ?? "No response") + " after " + (answer?.Ms ?? 0) + " ms");
                Note((answer?.Error ?? "AI returned no complete plan") + ". Nothing was run."); yield break; }
            string decision = (string)answer.Draft["decision"];
            if (decision != "propose" || (answer.Draft["missing"] as JArray)?.Count > 0)
            {
                if (decision == "clarify") { aiQuestion = (string)answer.Draft["reason"] ?? "Which editing detail?"; aiQuestionUntil = DateTime.UtcNow.AddSeconds(30); }
                else Note((string)answer.Draft["reason"] ?? "This whole edit could not be expressed; nothing was run.");
                yield break;
            }
            aiPendingDraft = answer.Draft; aiExpectedContext = context;
            Handle(session.ResolveRecipe(aiOriginal));
        }
        bool AcceptAiCandidates(string request, JObject payload)
        {
            if (request != aiRecipeRequest || aiRecipeRequest == null) return false;
            Debug.Log("VOICE AI native review " + (string)payload["decision"] + ": " + (string)payload["reason"]);
            aiRecipeRequest = null;
            if ((string)payload["decision"] == "clarify")
            { session.Cancel(); aiQuestion = (string)payload["reason"] ?? "Which editing detail?"; aiQuestionUntil = DateTime.UtcNow.AddSeconds(30); return true; }
            if ((string)payload["decision"] == "run")
            {
                if (string.IsNullOrEmpty((string)payload["resolution"]) || !(payload["recipe_plan"] is JObject plan) || !(plan["steps"] is JArray steps) || steps.Count == 0
                    ||aiExpectedContext==null||!AiContextCurrent())
                { session.Cancel(); InvalidateAi(); Note("The complete AI review was unavailable. Nothing was run."); return true; }
                try
                {
                    var answer=VoiceCandidates.FromJson(payload.ToString(Formatting.None));
                    if(answer.Candidates.Count!=1)throw new ArgumentException("Review requires one complete stored plan");
                    var candidate=answer.Candidates[0];SceneObject exact=null;
                    if(candidate.TargetId!=null||candidate.NeedsTarget)
                    {
                        var visible=new List<KeyValuePair<string,string>>();host.GetVisibleNativeObjects(visible);
                        var target=visible.FirstOrDefault(obj=>obj.Key==candidate.TargetId);
                        var captured=(aiExpectedContext["objects"] as JArray)?.OfType<JObject>().FirstOrDefault(obj=>(string)obj["id"]==candidate.TargetId);
                        if(target.Key==null||!host.TryGetGeneration(target.Key,out long generation)||(long?)captured?["generation"]!=generation)
                            throw new ArgumentException("The exact reviewed native target changed");
                        exact=new SceneObject(target.Key,target.Value);
                    }
                    var command=VoiceCommand.ReviewedRecipeCandidate(answer.Resolution,candidate,exact);
                    session.Cancel();aiReview=(JArray)steps.DeepClone();aiRunResolution=answer.Resolution;
                    deleteWaiting=command;deleteExpiresAt=DateTime.UtcNow.AddSeconds(120);Enqueue(Prompt.ConfirmSequence,command.Say);
                    ShowAiReview(); // Establish this plan's page gate before a controller can confirm.
                    return true;
                }
                catch(Exception error) when(error is ArgumentException||error is FormatException)
                {session.Cancel();InvalidateAi();Note("The reviewed AI target is no longer available. Nothing was run; request a fresh plan.");return true;}
            }
            return false;
        }
        bool AiConfirmationWaiting => deleteWaiting!=null&&deleteWaiting.Kind==CommandKind.Run
            &&aiRunResolution!=null&&deleteWaiting.Resolution==aiRunResolution;
        bool ShowAiReview()
        {
            if (aiReview == null) return false;
            var lines = new List<string> { "Review AI edit · nothing has run" };
            for(int i=0;i<aiReview.Count;i++)
            {
                var step=aiReview[i]; string target = (string)(step["target"] as JValue);
                if (step["target"] is JObject reference) target = "output of " + (string)reference["step"];
                var shown = new List<KeyValuePair<string,string>>(); host.GetVisibleNativeObjects(shown);
                target = shown.FirstOrDefault(obj => obj.Key == target).Value ?? target ?? "new object";
                string tool = ((string)step["tool"] ?? "Edit").Replace("mesh.","").Replace("object.","").Replace('_',' ');
                lines.Add((i+1)+". "+tool+" · "+target);
                if (step["selection"] is JObject selection)
                    lines.Add(selection["step"] != null ? "Use " + selection["output"] + " from " + selection["step"]
                        : (selection["indices"] as JArray)?.Count + " selected " + selection["component"] + " components");
                foreach (var property in (step["params"] as JObject ?? new JObject()).Properties())
                    lines.Add(property.Name.Replace('_',' ') + ": " + FriendlyAiValue(property.Name,property.Value));
            }
            panel.ShowComposition(string.Join("\n",lines),deleteExpiresAt,true); return true;
        }
        static string FriendlyAiValue(string name,JToken value)
        {
            if (name == "projection") return "captured Blender view";
            if (name.EndsWith("_m",StringComparison.Ordinal))
            {
                if (value is JArray vector) return string.Join(", ",vector.Select(v => FriendlyAiValue(name,v)));
                if (value.Type == JTokenType.Float || value.Type == JTokenType.Integer)
                    return (((double)value)*1000).ToString("0.###",System.Globalization.CultureInfo.InvariantCulture)+" mm";
            }
            return value.Type == JTokenType.String ? (string)value : value.ToString(Formatting.None);
        }
        bool CanConfirmAiReview()
        {
            if(aiReview!=null&&!AiContextCurrent())
            {InvalidateAi();Note("Blender context changed. Nothing was run; say the complete edit again.");return false;}
            if (aiReview != null && !panel.AllPagesReviewed)
            { Note("Review every page of the AI plan first. Say next page."); return false; }
            aiReview = null; return true;
        }
    }
}
