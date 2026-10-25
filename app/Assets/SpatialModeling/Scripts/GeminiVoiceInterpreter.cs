using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace SpatialModeling
{
    // Optional AI step of the voice UI. Free speech goes in; out comes ONE phrase VoiceCore already understands
    // (or a short reason why nothing fits). VoiceUiAdapter feeds that phrase into VoiceSession like typed words, so
    // the target rules, the questions for missing values, the host's resolver, the leases and the controller
    // confirmation for a delete all stay exactly as they are. Gemini never runs code and never talks to Blender.
    // Any failure (no key, no network, a slow or odd answer) gives the words back to the basic voice path.
    //
    // The key is read from the environment variable GEMINI_API_KEY or from a file gemini_key.txt (next to the
    // exe, or in the Unity project folder). It is never logged, never put in a URL and never stored in Git.
    public sealed class GeminiVoiceInterpreter
    {
        public const string DefaultModel = "gemini-3.5-flash-lite";
        const string Endpoint = "https://generativelanguage.googleapis.com/v1beta/models/";
        const int TimeoutSeconds = 5;
        const int MaxHostPhrases = 300;

        public sealed class Request
        {
            public string Heard = "";            // Whisper's own words when we have them, else the recognizer's
            public string Recognized = "";       // the recognizer's words, snapped onto its grammar
            public string Pointed;               // the object under the pointer, or null
            public readonly List<string> Objects = new List<string>();
            public IReadOnlyList<string> HostPhrases = new string[0];
        }

        public sealed class Answer
        {
            public string Phrase = "";           // one command phrase, or "" when nothing fits
            public string Reason = "";           // why nothing fits (short), or ""
            public string Error;                 // null when Gemini answered
            public long Ms;
        }

        readonly string apiKey;
        readonly string model;

        public GeminiVoiceInterpreter(string modelOverride)
        {
            string env = Environment.GetEnvironmentVariable("GEMINI_MODEL");
            model = !string.IsNullOrWhiteSpace(env) ? env.Trim()
                : !string.IsNullOrWhiteSpace(modelOverride) ? modelOverride.Trim() : DefaultModel;
            apiKey = FindKey(out string source);
            KeySource = source;
        }

        public string Model => model;
        public bool Available => !string.IsNullOrEmpty(apiKey);
        /// <summary>Where the key came from (a file path or the variable's name), never the key itself.</summary>
        public string KeySource { get; }

        // ---------- the key ----------

        static string FindKey(out string source)
        {
            source = null;
            string env = KeyFrom(Environment.GetEnvironmentVariable("GEMINI_API_KEY"));
            if (env != null) { source = "environment variable GEMINI_API_KEY"; return env; }
            string[] places =
            {
                Path.Combine(Application.dataPath, "..", "gemini_key.txt"),          // the exe's folder; in the editor: app/
                Path.Combine(Application.persistentDataPath, "gemini_key.txt"),
                Path.Combine(Directory.GetCurrentDirectory(), "gemini_key.txt"),
            };
            foreach (string place in places)
            {
                try
                {
                    if (!File.Exists(place)) continue;
                    string key = KeyFrom(File.ReadAllText(place));
                    if (key != null) { source = Path.GetFullPath(place); return key; }
                }
                catch (Exception) { /* unreadable: try the next place */ }
            }
            return null;
        }

        // The first line that looks like a key: 20+ characters without spaces.
        static string KeyFrom(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            foreach (string line in text.Split('\n'))
            {
                string t = line.Trim().Trim('﻿', '"', '\'');
                if (t.Length >= 20 && t.IndexOf(' ') < 0) return t;
            }
            return null;
        }

        // ---------- the request ----------

        // Minimal thinking keeps the answer fast. A model that refuses the setting answers 400: then once without it.
        string ThinkingLevel => model.IndexOf("lite", StringComparison.OrdinalIgnoreCase) >= 0 ? "minimal" : "low";

        public IEnumerator Interpret(Request request, Action<Answer> done)
        {
            var clock = System.Diagnostics.Stopwatch.StartNew();
            var answer = new Answer();
            string url = Endpoint + model + ":generateContent";
            for (int attempt = 0; attempt < 2; attempt++)
            {
                string json = BuildBody(request, attempt == 0).ToString(Formatting.None);
                using (var web = new UnityWebRequest(url, "POST"))
                {
                    web.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
                    web.downloadHandler = new DownloadHandlerBuffer();
                    web.SetRequestHeader("Content-Type", "application/json");
                    web.SetRequestHeader("x-goog-api-key", apiKey);
                    web.timeout = TimeoutSeconds;
                    yield return web.SendWebRequest();
                    string body = web.downloadHandler != null ? web.downloadHandler.text : "";
                    if (web.result == UnityWebRequest.Result.Success)
                    {
                        answer.Error = null;
                        Read(body, answer);
                        break;
                    }
                    answer.Error = Describe(web, body);
                    if (!(web.responseCode == 400 && attempt == 0)) break;
                }
            }
            answer.Ms = clock.ElapsedMilliseconds;
            done(answer);
        }

        JObject BuildBody(Request r, bool withThinking)
        {
            var body = new JObject
            {
                ["systemInstruction"] = new JObject
                {
                    ["parts"] = new JArray(new JObject { ["text"] = SystemPrompt(r.HostPhrases) }),
                },
                ["contents"] = new JArray(new JObject
                {
                    ["role"] = "user",
                    ["parts"] = new JArray(new JObject { ["text"] = UserText(r) }),
                }),
            };
            if (withThinking)
                body["generationConfig"] = new JObject { ["thinkingConfig"] = new JObject { ["thinkingLevel"] = ThinkingLevel } };
            return body;
        }

        static string UserText(Request r)
        {
            var sb = new StringBuilder();
            sb.Append("Objects in the scene: ").Append(r.Objects.Count == 0 ? "(none)" : string.Join(", ", r.Objects)).Append('\n');
            sb.Append("Object the user is pointing at: ").Append(string.IsNullOrEmpty(r.Pointed) ? "(none)" : r.Pointed).Append('\n');
            sb.Append("The user said: ").Append(JsonConvert.ToString(r.Heard ?? "")).Append('\n');
            if (!string.IsNullOrWhiteSpace(r.Recognized) &&
                !string.Equals(r.Recognized.Trim(), (r.Heard ?? "").Trim(), StringComparison.OrdinalIgnoreCase))
                sb.Append("The recognizer's guess for the same audio: ").Append(JsonConvert.ToString(r.Recognized)).Append('\n');
            return sb.ToString();
        }

        static string SystemPrompt(IReadOnlyList<string> hostPhrases)
        {
            var sb = new StringBuilder();
            sb.Append(Head);
            int n = 0;
            var seen = new HashSet<string>();
            if (hostPhrases != null)
                foreach (string p in hostPhrases)
                {
                    string t = (p ?? "").Trim();
                    // Whole commands only: two or more words. Single words and the recognizer's [unk] are not commands.
                    if (t.IndexOf(' ') < 0 || t.Length > 60 || t.IndexOf('[') >= 0 || !seen.Add(t)) continue;
                    sb.Append("- ").Append(t).Append('\n');
                    if (++n >= MaxHostPhrases) break;
                }
            if (n == 0) sb.Append("(the host has not sent its list: use the core commands only)\n");
            sb.Append(Tail);
            return sb.ToString();
        }

        const string Head =
@"You are the command interpreter of a VR app that edits 3D models in Blender by voice.
The user speaks freely. Turn what they want into ONE command phrase the app already understands, or say it can't be done.
Reply with a single JSON object and nothing else: {""phrase"": ""..."", ""reason"": ""...""}

Core commands, always available. Write every number as English words (""forty five"", ""one point five""):
- add a cube | add a sphere | add a cylinder
- move this <number> <millimeters|centimeters|meters> along <x|y|z|negative x|negative y|negative z>
  Directions: left = negative x, right = x, away from the user or forward = y, toward the user or back = negative y, up = z, down = negative z.
  Without a distance say for example ""move this up"" or ""move this along negative x"": the app asks for the distance.
- rotate this <number> degrees around <x|y|z>
- scale this by <factor>   (""by two"" doubles, ""by zero point five"" halves)
- scale this to <number> percent
- delete this | undo | redo | cancel
- select the <object name>
""this"" is the selected or pointed-at object. If the user names one of the scene's objects, say ""the <name>"" instead, exactly as listed.

More commands. Use the wording of one of these phrases when it fits, adding numbers or axes as words the way the examples below do:
";

        const string Tail =
@"
Rules:
- Never invent a value. If the user did not give a distance, an angle, an axis, a factor or a shape, leave it out: the app asks for it.
- One command only. If the user asks for several, return the first.
- If nothing fits (small talk, an unsupported operation, unclear words), return an empty phrase and a reason of at most ten words.
- ""reason"" is empty when you return a phrase.

Examples:
make this twice as big -> {""phrase"": ""scale this by two"", ""reason"": """"}
make it half the size -> {""phrase"": ""scale this to fifty percent"", ""reason"": """"}
turn it forty five degrees -> {""phrase"": ""rotate this forty five degrees"", ""reason"": """"}
shove it left ten centimeters -> {""phrase"": ""move this ten centimeters along negative x"", ""reason"": """"}
move the shaft up a bit -> {""phrase"": ""move the shaft up"", ""reason"": """"}
get rid of it -> {""phrase"": ""delete this"", ""reason"": """"}
put a ball on the table -> {""phrase"": ""add a sphere"", ""reason"": """"}
what's the weather -> {""phrase"": """", ""reason"": ""Not a modeling command""}
";

        // ---------- the answer ----------

        static void Read(string body, Answer answer)
        {
            try
            {
                JObject root = JObject.Parse(body);
                string block = (string)root["promptFeedback"]?["blockReason"];
                var candidates = root["candidates"] as JArray;
                var parts = candidates != null && candidates.Count > 0 ? candidates[0]["content"]?["parts"] as JArray : null;
                if (parts == null)
                {
                    answer.Error = block != null ? "Gemini blocked the request (" + block + ")" : "Gemini sent no answer";
                    return;
                }
                var text = new StringBuilder();
                foreach (JToken part in parts)
                {
                    if ((bool?)part["thought"] == true) continue;   // a thought summary, not the answer
                    text.Append((string)part["text"]);
                }
                JObject result = JObject.Parse(StripFence(text.ToString()));
                answer.Phrase = CleanPhrase((string)result["phrase"]);
                answer.Reason = Truncate(((string)result["reason"] ?? "").Trim(), 80);
            }
            catch (Exception e)
            {
                answer.Phrase = "";
                answer.Reason = "";
                answer.Error = "Unreadable answer: " + e.Message;
            }
        }

        // A reply wrapped in ```json ... ``` still counts.
        static string StripFence(string text)
        {
            string t = (text ?? "").Trim();
            if (!t.StartsWith("```")) return t;
            int open = t.IndexOf('\n');
            int close = t.LastIndexOf("```", StringComparison.Ordinal);
            return open >= 0 && close > open ? t.Substring(open + 1, close - open - 1).Trim() : t.Trim('`');
        }

        // One short line, no quotes: it is fed to VoiceSession like typed words.
        static string CleanPhrase(string phrase)
        {
            if (string.IsNullOrWhiteSpace(phrase)) return "";
            string first = phrase.Trim().Split('\n')[0].Trim().Trim('"', '\'');
            var sb = new StringBuilder();
            foreach (string word in first.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (sb.Length > 0) sb.Append(' ');
                sb.Append(word);
            }
            return Truncate(sb.ToString(), 200);
        }

        static string Truncate(string text, int length) => text.Length <= length ? text : text.Substring(0, length);

        // Never includes the key: it travels only in a header.
        static string Describe(UnityWebRequest web, string body)
        {
            if (web.responseCode == 0) return "no connection (" + web.error + ")";
            string message = null;
            try { message = (string)JObject.Parse(body)["error"]?["message"]; }
            catch (Exception) { /* not JSON */ }
            return "HTTP " + web.responseCode + (message != null ? ": " + Truncate(message, 160) : "");
        }
    }
}
