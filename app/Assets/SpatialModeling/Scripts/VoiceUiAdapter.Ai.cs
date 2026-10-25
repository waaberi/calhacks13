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
        string aiRecipeRequest, aiOriginal, aiQuestion, aiFingerprint;
        DateTime aiQuestionUntil;
        int aiSequence, aiReviewPage, aiReviewedThrough;
        bool aiBusy;
        void InitializeAi() { ai = new GeminiVoiceInterpreter(geminiModel); }
        public void SetAi(bool enabled) { InvalidateAi(); aiMode = enabled; }
        void AcceptAiCatalog(JObject grammar)
        { aiTools = (int?)grammar["recipe_version"] == 1 && grammar["tools"] is JArray tools ? (JArray)tools.DeepClone() : new JArray(); }
        void InvalidateAi()
        {
            bool owned = aiBusy || aiRecipeRequest != null || aiReview != null || aiQuestion != null;
            if (aiReview != null) deleteWaiting = null;
            if (owned) session?.Cancel();
            aiSequence++; ai?.Cancel(); aiBusy = false; aiQuestion = aiRecipeRequest = null;
            aiPendingDraft = aiExpectedContext = null; aiReview = null;
        }
        JObject CaptureAiContext()
        {
            var preview = PreviewInteraction.Current; var drawing = preview?.Drawing;
            var model = drawing?.NativeState["model_edit"] as JObject ?? new JObject();
            var nativeSelection = model["selection"] as JObject ?? new JObject();
            var selected = preview?.DirectEditing?.SelectionSnapshot;
            if (selected == null || !(selected["objects"] is JArray selectedObjects) || selectedObjects.Count == 0)
            {
                string id = SelectedObjectId ?? (string)model["active_object_id"];
                selected = new JObject { ["component"] = (string)nativeSelection["component"] ?? (string)model["component"] ?? "object",
                    ["indices"] = nativeSelection["indices"]?.DeepClone() ?? model["selected_indices"]?.DeepClone() ?? new JArray(), ["objects"] = new JArray() };
                if (id != null && host.TryGetGeneration(id, out long generation))
                    ((JArray)selected["objects"]).Add(new JObject { ["id"] = id, ["generation"] = generation });
            }
            var shown = new List<KeyValuePair<string,string>>(); host.GetShownObjects(shown);
            var objects = new JArray();
            foreach (var obj in shown)
                if (host.TryGetGeneration(obj.Key, out long generation)) objects.Add(new JObject { ["id"] = obj.Key, ["name"] = obj.Value, ["generation"] = generation });
            return new JObject { ["document_id"] = host.DocumentId, ["open_epoch"] = host.OpenEpoch, ["revision"] = host.Revision,
                ["mode"] = (string)model["mode"] ?? (string)drawing?.NativeState["mode"] ?? "OBJECT",
                ["native_tool"] = (string)model["native_tool"] ?? "", ["topology_token"] = (string)model["topology_token"] ?? "",
                ["options"] = model["options"]?.DeepClone() ?? model["settings"]?.DeepClone() ?? new JObject(),
                ["native_selection"] = nativeSelection.DeepClone(),
                ["selection"] = selected.DeepClone(), ["objects"] = objects,
                ["gesture_epoch"] = preview?.DirectEditing?.ContextEpoch ?? 0,
                ["gesture_active"] = preview?.DirectEditing?.Gesturing == true || preview?.DirectEditing?.LiveBusy == true || drawing?.Session.ExternalEditBusy == true };
        }
        void TickAi()
        {
            if (aiQuestion != null && DateTime.UtcNow >= aiQuestionUntil) { aiQuestion = null; Note("AI question expired. Say the complete edit again."); }
            if ((aiBusy || aiQuestion != null || aiRecipeRequest != null || aiReview != null)
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
        static bool Control(string text) => Regex.IsMatch(text.Trim(), @"^(undo|redo|cancel|cancel that|never mind|save|save file|save the file)$", RegexOptions.IgnoreCase);
        void HearOrInterpret(RecognitionResult result, bool fromMic)
        {
            string text = fromMic ? RawAiTranscript() ?? result.Text : result.Text;
            if (aiReview != null && Regex.IsMatch(text.Trim(), @"^(next|next page|previous|previous page|back)$", RegexOptions.IgnoreCase))
            { aiReviewPage = Mathf.Clamp(aiReviewPage + (text.StartsWith("next",StringComparison.OrdinalIgnoreCase) ? 1 : -1), 0, Math.Max(0,(aiReview.Count-1)/3)); aiReviewedThrough = Math.Max(aiReviewedThrough,aiReviewPage); return; }
            if (Control(text) || session.Pending != null || session.Choice != null || session.CompositionQuestion != null || session.WaitingForHost)
            { Handle(session.Hear(result)); return; }
            bool mesh = (string)(PreviewInteraction.Current?.Drawing?.NativeState["model_edit"] as JObject)?["mode"] == "EDIT_MESH";
            bool newTool = Regex.IsMatch(text, @"\b(extrude|inset|knife|loop\s*cut|dissolve|proportional|snapping)\b|\b(bevel|merge|delete)\b.*\b(vertices|edges|faces|selected)\b", RegexOptions.IgnoreCase);
            if (!aiMode || !AiAvailable || (aiQuestion == null && !mesh && !newTool && KnownBasic(text)))
            { Handle(session.Hear(result)); return; }
            if (result.Confidence < .5f) { Enqueue(Prompt.LowConfidence,null); return; }
            string request = aiQuestion == null ? text : aiOriginal + "\nClarification question: " + aiQuestion + "\nUser answer: " + text;
            aiOriginal = aiQuestion == null ? text : aiOriginal; aiQuestion = null;
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
            { Note("AI could not prepare this edit. Nothing was run; retry or use a complete basic command."); yield break; }
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
            aiRecipeRequest = null;
            if ((string)payload["decision"] == "clarify")
            { session.Cancel(); aiQuestion = (string)payload["reason"] ?? "Which editing detail?"; aiQuestionUntil = DateTime.UtcNow.AddSeconds(30); return true; }
            if ((string)payload["decision"] == "run")
            {
                if (!(payload["recipe_plan"] is JObject plan) || !(plan["steps"] is JArray steps) || steps.Count == 0)
                { session.Cancel(); InvalidateAi(); Note("The complete AI review was unavailable. Nothing was run."); return true; }
                aiReview = (JArray)steps.DeepClone(); aiReviewPage = aiReviewedThrough = 0;
            }
            return false;
        }
        bool ShowAiReview()
        {
            if (aiReview == null) return false;
            int pages = Math.Max(1,(aiReview.Count+2)/3);
            var lines = new List<string> { "Review AI edit · page " + (aiReviewPage+1) + " / " + pages };
            for(int i=aiReviewPage*3;i<Math.Min(aiReview.Count,aiReviewPage*3+3);i++)
            {
                var step=aiReview[i]; string target = (string)(step["target"] as JValue);
                if (step["target"] is JObject reference) target = "output of " + (string)reference["step"];
                var shown = new List<KeyValuePair<string,string>>(); host.GetShownObjects(shown);
                target = shown.FirstOrDefault(obj => obj.Key == target).Value ?? target ?? "new object";
                string tool = ((string)step["tool"] ?? "Edit").Replace("mesh.","").Replace("object.","").Replace('_',' ');
                lines.Add((i+1)+". "+tool+" · "+target);
                if (step["selection"] is JObject selection)
                    lines.Add(selection["step"] != null ? "Use " + selection["output"] + " from " + selection["step"]
                        : (selection["indices"] as JArray)?.Count + " selected " + selection["component"] + " components");
                foreach (var property in (step["params"] as JObject ?? new JObject()).Properties())
                    lines.Add(property.Name.Replace('_',' ') + ": " + FriendlyAiValue(property.Name,property.Value));
            }
            lines.Add("Nothing has run. Say next page / previous page. After reviewing all pages, left stick click confirms; cancel discards.");
            panel.ShowComposition(string.Join("\n",lines),deleteExpiresAt); return true;
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
            if (aiReview != null && aiReviewedThrough < (aiReview.Count-1)/3)
            { Note("Review every page of the AI plan first. Say next page."); return false; }
            aiReview = null; return true;
        }
    }
}
