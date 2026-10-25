using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using SpatialModeling.VoiceCore;
using SpatialModeling.VoiceCore.Vosk;
using SpatialModeling.VoiceCore.Whisper;

namespace SpatialModeling
{
    // Connects VoiceCore to HostScene: mic -> recognizer -> VoiceSession -> command -> host, plus prompts and feedback.
    // Voice off (no model/mic) never blocks controller or menu editing.
    [DefaultExecutionOrder(200)]
    public partial class VoiceUiAdapter : MonoBehaviour
    {
        public HostScene host;
        [Tooltip("Microphone to use, matched by name (case-insensitive, part of the name is enough). Empty: the default " +
                 "device. The command line -voiceMic NAME overrides it. A name that matches nothing turns voice off.")]
        public string microphoneName = "";
        [Tooltip("Whisper (the approved default, #159): whisper-server for every utterance, Vosk if it can't start. " +
                 "FastPath: Vosk first, Whisper when Vosk isn't sure. Vosk: Vosk only.")]
        public RecognizerKind recognizer = RecognizerKind.Whisper;
        // Voice text (status line, feedback, the question panel) is drawn on top of the scene over a dark backing, so it
        // stays readable over white or complex geometry and inside a big object. Call FitBacking after changing the text.
        public static void SetupText(TextMesh tm, GameObject go)
        {
            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font == null) font = Font.CreateDynamicFontFromOSFont("Arial", 32);
            tm.font = font;
            var mr = go.GetComponent<MeshRenderer>();
            if (mr == null) mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterial = OverlayTextMaterial(font);
            mr.sortingOrder = 4001; // World-space glass sorts at 4000; text must remain above its backing.

            GlassVoiceText.Create(tm);
        }

        static Material overlayText;
        static Material OverlayTextMaterial(Font font)
        {
            if (overlayText != null) return overlayText;
            Material source = font != null ? font.material : null;
            overlayText = source != null ? new Material(source) : new Material(Shader.Find("GUI/Text Shader"));
            overlayText.SetInt("unity_GUIZTestMode", (int)UnityEngine.Rendering.CompareFunction.Always);
            overlayText.renderQueue = 4001;
            if (font != null)
                Font.textureRebuilt += f => { if (f == font && overlayText != null) overlayText.mainTexture = f.material.mainTexture; };
            return overlayText;
        }

        public static void FitBacking(TextMesh tm) => tm.GetComponent<GlassVoiceText>()?.Fit();

        public const string TranscriptionPreference = "SpatialModeling.Voice.ShowTranscription";
        public bool ShowTranscription { get; private set; }
        public const string SelectionPopupPreference = "SpatialModeling.UI.SelectionPopups";
        public bool SelectionPopups { get; private set; }
        public void SetSelectionPopups(bool show)
        {
            SelectionPopups = show;
            PlayerPrefs.SetInt(SelectionPopupPreference, show ? 1 : 0);
            PlayerPrefs.Save();
            if (!show && feedback != null && IsSelectionPopup(feedback.text)) feedback.gameObject.SetActive(false);
        }
        static bool IsSelectionPopup(string message) => message != null &&
            (message.StartsWith("Selected:", StringComparison.Ordinal) || message.StartsWith("Deselected:", StringComparison.Ordinal));
        public void SetShowTranscription(bool show)
        {
            ShowTranscription = show;
            PlayerPrefs.SetInt(TranscriptionPreference, show ? 1 : 0);
            PlayerPrefs.Save();
            if (!show && feedback != null && feedback.text.StartsWith("Heard:", StringComparison.Ordinal))
                feedback.gameObject.SetActive(false);
            if (status != null) PlaceStatus();
        }

        // The microphone to record from (null: the system default). A configured name wins (part of it, any case) and
        // never falls back. Without one, the first device whose name contains "Oculus" or "Headset" (the Quest's mic over
        // Link is "Headset Microphone (Oculus Virtual Audio Device)" on Windows), else the system default.
        // False: a name was configured and no device matches it.
        public static bool TryChooseMicrophone(string[] devices, string wanted, out string device)
        {
            device = null;
            if (!string.IsNullOrEmpty(wanted))
            {
                device = devices == null ? null : Array.Find(devices, d => d != null && d.IndexOf(wanted, StringComparison.OrdinalIgnoreCase) >= 0);
                return device != null;
            }
            if (devices == null) return true;
            device = Array.Find(devices, d => d != null && (d.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                                            d.IndexOf("Headset", StringComparison.OrdinalIgnoreCase) >= 0));
            return true;
        }
        // AskHost (#146): words VoiceCore can't parse go to the host's resolver (voice.resolve -> voice.candidates).
        VoiceSession session = new VoiceSession(new VoiceSessionOptions { AskHost = true }, () => DateTime.UtcNow);
        string grammarQuery;              // the voice.grammar_query request, so its unknown_type means "old host"
        ISpeechRecognizer activeRecognizer;
        TextMesh status;                  // what was heard and what came of it, head-locked
        string heardLine = "", resultLine = "";
        string micLine = "Mic: none (voice off)";   // the microphone in use, first line of the status
        double releasedAt = -1;           // realtimeSinceStartup at the last push-to-talk release, for the logged latency
        bool awaitingResult;              // released, no recognition result yet (logged if none comes)
        VoiceInput input;
        AudioClip mic;
        float[] chunk;
        int read;
        string micDevice;

        PendingCommandPanel panel;
        TextMesh feedback;
        AudioSource speaker;
        readonly Queue<Prompt> prompts = new Queue<Prompt>();
        readonly Queue<string> details = new Queue<string>();
        readonly HashSet<string> voiceRequests = new HashSet<string>();
        float noteUntil;

        VoiceCommand deleteWaiting;      // a complete Delete, until the controller confirms it
        DateTime deleteExpiresAt;
        string pointerId;
        string typed = "";
        string shownError;                // the VoiceInput error already shown, so it isn't repeated every 4 s
        string grammarNames;              // the names the recognizer grammar was last built from
        bool talking, waitingResult, playing;   // feedback: holding talk, waiting for a result, a prompt is playing
        float resultDeadline;
        InputAction talk, confirm, cancel, leftGrip;

        void Awake()
        {
            ShowTranscription = PlayerPrefs.GetInt(TranscriptionPreference, 0) == 1;
            SelectionPopups = PlayerPrefs.GetInt(SelectionPopupPreference, 0) == 1;
            if (host == null) host = FindAnyObjectByType<HostScene>();

            var p = new GameObject("PendingCommandPanel");
            panel = p.AddComponent<PendingCommandPanel>();
            var f = new GameObject("VoiceFeedback");
            feedback = f.AddComponent<TextMesh>();
            feedback.fontSize = 48; feedback.characterSize = 0.012f; feedback.anchor = TextAnchor.UpperLeft;
            feedback.color = Color.white;
            SetupText(feedback, f);
            f.SetActive(false);
            var st = new GameObject("VoiceStatus");
            status = st.AddComponent<TextMesh>();
            status.fontSize = 48; status.characterSize = 0.009f; status.anchor = TextAnchor.UpperLeft;
            status.color = new Color(0.6f, 1f, 0.7f);
            SetupText(status, st);
            st.SetActive(ShowTranscription);

            speaker = gameObject.AddComponent<AudioSource>();
            speaker.spatialBlend = 0f;

            talk = new InputAction("Talk", InputActionType.Button);
            // Push-to-talk on the left menu button: the right grip grabs (P2), both triggers click and draw.
            talk.AddBinding("<XRController>{LeftHand}/menuButton");
            talk.AddBinding("<Keyboard>/rightShift");
            // Confirm delete on the left stick click: both triggers click and draw (P2), so neither can confirm or cancel.
            // Cancel by voice ("cancel") or Esc.
            confirm = new InputAction("ConfirmDelete", InputActionType.Button);
            confirm.AddBinding("<XRController>{LeftHand}/thumbstickClicked");
            confirm.AddBinding("<Keyboard>/backquote");
            // Not while the left grip is held: P2 (#158) toggles free placement with a stick click during a grab.
            leftGrip = new InputAction("LeftGripHeld", InputActionType.Button);
            leftGrip.AddBinding("<XRController>{LeftHand}/gripPressed");
            cancel = new InputAction("CancelPending", InputActionType.Button);
            cancel.AddBinding("<Keyboard>/escape");
            talk.started += _ =>
            {
                Debug.Log("TALK down. ready=" + input?.Ready + " error=" + input?.Error);
                talking = input != null; waitingResult = false;
                if (input != null) Note("Listening...");
                input?.StartUtterance();
            };
            talk.canceled += _ =>
            {
                releasedAt = Time.realtimeSinceStartupAsDouble;
                awaitingResult = true;
                Debug.Log("TALK up");
                talking = false;
                input?.StopUtterance();
                if (input != null) { waitingResult = true; resultDeadline = Time.time + 3f; Note("Processing..."); }
            };
            confirm.started += _ => { if (!leftGrip.IsPressed()) ConfirmDelete(); };
            cancel.started += _ => CancelPressed();
            talk.Enable(); confirm.Enable(); cancel.Enable(); leftGrip.Enable();
            InitializeAi();
        }

        void Start()
        {
            BindHost();
            StartCoroutine(PlayLoop());
            StartVoice();
            OnScene();
            OVRManager.VrFocusLost += SuspendObjectTargeting;
            OVRManager.HMDUnmounted += SuspendObjectTargeting;
        }

        void BindHost()
        {
            host.SceneChanged += OnScene;
            host.ConnectionLost += () => { InvalidateAi(); ResetObjectTargeting(); DropDelete(Prompt.ConnectionLost); Handle(session.ConnectionLost()); };
            host.DocumentChanged += () =>
            {
                InvalidateAi();
                // contracts/README.md, Wrong document: drop everything held for the old document. Object IDs survive
                // a reopen, so a waiting delete would otherwise hit the same object in the reopened file.
                DropDelete(Prompt.DocumentChanged);
                ResetObjectTargeting();
                Handle(session.DocumentChanged());
            };
            host.CommandAnswered += OnAnswered;
            host.Welcomed += () => grammarQuery = host.SendVoice(VoiceGrammar.QueryType, new JObject());
            host.VoiceGrammarReceived += (re, json) =>
            {
                session.SetHostGrammar(VoiceGrammar.FromJson(json));
                session.EnableComposition((bool?)JObject.Parse(json)["composition"] == true);
                AcceptAiCatalog(JObject.Parse(json));
                input?.SetGrammar(session.GrammarPhrases());
                Debug.Log("VOICE grammar: " + session.GrammarPhrases().Count + " phrases with the host's");
            };
            host.VoiceCandidatesReceived += (re, json) =>
            {
                if (AcceptAiCandidates(re, JObject.Parse(json))) return;
                VoiceCandidates answer = VoiceCandidates.FromJson(json);
                Debug.Log($"VOICE candidates {answer.Decision} after {Since()} ms: {string.Join(" | ", answer.Candidates)}" +
                          (answer.Reason != null ? " (" + answer.Reason + ")" : ""));
                Handle(session.HostAnswered(re, answer));
            };
            host.RequestFailed += (re, code) =>
            {
                Debug.Log("VOICE host request refused " + re + ": " + code);
                if (re == grammarQuery) { if (code == "unknown_type") session.HostHasNoVoice(); }
                else if (re == aiRecipeRequest)
                { InvalidateAi(); Note("Blender could not prepare the AI review (" + code + "). Nothing was run."); }
                else Handle(session.HostError(re, code));
            };
        }

        void StartVoice()
        {
            try
            {
                var settings = VoiceRecognizerSettings.ForStreamingAssets(Application.streamingAssetsPath, m => Debug.Log("[Voice] " + m));
                settings.Kind = recognizer;
                // Pre-roll 300 ms / post-roll 150 ms: needs Write every frame, also with the button up (PumpMic does).
                input = new VoiceInput(() => activeRecognizer = VoiceRecognizers.Create(settings), 16000,
                    VoiceInput.RecommendedPrerollMs, VoiceInput.RecommendedPostrollMs);
                input.SetGrammar(session.GrammarPhrases());
                string[] devices = Microphone.devices;
                if (devices.Length == 0) { micLine = "Mic: none (voice off)"; Note("No microphone. Use the text box (voice off)."); return; }
                string wanted = CommandLine("-voiceMic") ?? microphoneName;
                if (!TryChooseMicrophone(devices, wanted, out micDevice))
                {
                    micLine = "Mic: no \"" + wanted + "\" (voice off)";
                    Debug.Log("VoiceUiAdapter mic: no \"" + wanted + "\" (voice off)  all: " + string.Join(" | ", devices));
                    Note("Voice off: no microphone named \"" + wanted + "\"");
                    return;
                }
                micLine = "Mic: " + (micDevice ?? "system default");
                Debug.Log("VoiceUiAdapter mic: " + (micDevice ?? "(OS default)") +
                          (string.IsNullOrEmpty(wanted) ? "" : " (by name \"" + wanted + "\")") + "  all: " + string.Join(" | ", devices));
                Microphone.GetDeviceCaps(micDevice, out int min, out int max);
                int rate = min == 0 && max == 0 ? 16000 : Mathf.Clamp(16000, min, max);
                mic = Microphone.Start(micDevice, true, 1, rate);
                chunk = new float[mic.frequency / 50 * mic.channels];
            }
            catch (Exception e) { micLine = "Mic: none (voice off)"; Note("Voice off: " + e.Message); input = null; }
        }

        void OnDestroy()
        {
            InvalidateAi();
            DisposeObjectTargeting();
            talk?.Dispose(); confirm?.Dispose(); cancel?.Dispose(); leftGrip?.Dispose();
            if (mic != null) Microphone.End(micDevice);
            input?.Dispose();
        }

        // ---------- per frame ----------

        void Update()
        {
            TickAi();
            PumpMic();
            if (input != null)
            {
                if (input.Error != null && input.Error != shownError)
                {
                    shownError = input.Error;
                    if (!micLine.EndsWith("(voice off)")) micLine += " (voice off)";
                    Debug.LogWarning("VoiceUiAdapter: voice off: " + input.Error);
                    Note("Voice off: " + input.Error);
                }
                while (input.TryGetResult(out RecognitionResult result))
                {
                    awaitingResult = false;
                    waitingResult = false;
                    string how = activeRecognizer is FastPathRecognizer fp
                        ? " " + fp.LastOutcome + (fp.Slow is WhisperServerRecognizer w && fp.LastOutcome.ToString().StartsWith("Slow") ? " whisper '" + w.LastTranscript + "'" : "")
                        : "";
                    Debug.Log($"HEARD: {result} after {Since()} ms{how}");
                    resultLine = "";
                    if (string.IsNullOrWhiteSpace(result.Text))
                    {
                        // An empty result is a silent press (VoiceSession.Hear: NoResult Silence, nothing spoken).
                        Note(DidntHear);
                        Handle(session.Hear(result));
                        continue;
                    }
                    heardLine = $"Heard: \"{result.Text}\" ({result.Confidence:0.00})";
                    if (prompts.Count == 0 && !playing) Note("Heard: " + result.Text);   // don't cover a prompt that is playing
                    HearOrInterpret(result, true);
                }
                // A press that gave no result at all (#146): silence, or speech that matched no phrase.
                while (input.TryGetNoResult(out NoResultReason why))
                {
                    awaitingResult = false;
                    waitingResult = false;
                    Debug.Log($"VOICE no result {why} after {Since()} ms" + (activeRecognizer is FastPathRecognizer nr
                        ? ": " + nr.LastOutcome + (nr.Slow is WhisperServerRecognizer nw ? " whisper '" + nw.LastTranscript + "'" : "") : ""));
                    // Silence says nothing (VoiceSession), so show why; speech that matched nothing says "Sorry, I
                    // didn't catch that" (Prompt.LowConfidence), which the prompt loop shows.
                    if (why == NoResultReason.Silence) Note(DidntHear);
                    if (!TryInterpretUnmatched(why)) Handle(session.NothingRecognized(why));
                }
            }
            if (talking) noteUntil = Time.time + 1f;   // keep "Listening..." up while the button is held
            if (waitingResult && Time.time > resultDeadline)
            {
                waitingResult = false;
                Note(DidntHear);
            }
            if (awaitingResult && Since() > 2500)
            {
                // VoiceInput reports every press without a result (TryGetNoResult); this only logs one that never ended.
                awaitingResult = false;
                Debug.Log("VOICE no result 2.5 s after release" + (activeRecognizer is FastPathRecognizer f
                    ? ": " + f.LastOutcome + (f.Slow is WhisperServerRecognizer ws ? " whisper '" + ws.LastTranscript + "'" : "") : ""));
            }
            Handle(session.Tick());

            if (deleteWaiting != null && DateTime.UtcNow >= deleteExpiresAt) DropDelete(Prompt.TimedOut);
            PendingCommand pending = session.Pending;
            PendingChoice choice = session.Choice;
            if (choice != null) panel.ShowChoice(choice);
            else if (pending != null) panel.Show(pending);
            else if (session.CompositionQuestion != null) panel.ShowComposition(session.CompositionQuestion, session.CompositionExpiresAt);
            else if (deleteWaiting != null && ShowAiReview()) { }
            else if (deleteWaiting != null) panel.ShowDelete(deleteWaiting.ToString(), deleteExpiresAt);
            else if (aiQuestion != null) panel.ShowComposition(aiQuestion, aiQuestionUntil);
            else if (panel.Visible) panel.Hide();

            if (feedback.gameObject.activeSelf && Time.time > noteUntil && prompts.Count == 0)
                feedback.gameObject.SetActive(false);
            PlaceFeedback();
            PlaceStatus();
        }

        void PlaceStatus()
        {
            var cam = Camera.main;
            string text = micLine + "\n" + ObjectTargetLabel + (heardLine.Length > 0 ? "\n" + heardLine : "") +
                          (session.WaitingForHost ? "\nthinking..." : resultLine.Length > 0 ? "\n" + resultLine : "");
            status.gameObject.SetActive(ShowTranscription && cam != null);
            if (!status.gameObject.activeSelf) return;
            status.text = text;
            var t = status.transform;
            t.position = cam.transform.TransformPoint(new Vector3(-0.35f, -0.1f, 1.1f));
            t.rotation = cam.transform.rotation;   // parallel to the view, so the lines don't slant
            FitBacking(status);
        }

        public const string DidntCatch = "Didn't catch that.";
        const string DidntHear = "Didn't hear anything. Speak closer and louder.";

        // The status line for a press that gave nothing to act on (silence, or speech that matched no phrase); while the
        // host's question is still open, how to answer it.
        string NothingLine() => DidntCatch + (session.Choice != null ? " " + AnswerHint(session.Choice.Candidates.Count) : "");
        // "Say one, two or cancel.": how to answer a question with n options.
        public static string AnswerHint(int n)
        {
            string[] words = { "one", "two", "three" };
            int k = Math.Max(1, Math.Min(3, n));
            return "Say " + string.Join(", ", words, 0, k) + " or cancel.";
        }

        long Since() => releasedAt < 0 ? -1 : (long)((Time.realtimeSinceStartupAsDouble - releasedAt) * 1000);

        static string CommandLine(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i + 1 < args.Length; i++) if (args[i] == name) return args[i + 1];
            return null;
        }

        void PumpMic()
        {
            if (input == null || mic == null || input.Error != null) return;
            if (!Microphone.IsRecording(micDevice)) return;

            int channels = Mathf.Max(1, mic.channels);
            int ring = mic.samples * channels;
            if (ring <= 0 || mic.frequency <= 0) return;                 // the mic isn't ready yet

            if (chunk == null || chunk.Length == 0)
                chunk = new float[Mathf.Max(1, mic.frequency / 50) * channels];

            int position = Microphone.GetPosition(micDevice) * channels;
            while ((position - read + ring) % ring >= chunk.Length)
            {
                mic.GetData(chunk, read / channels);
                input.Write(chunk, chunk.Length, mic.frequency, channels);
                read = (read + chunk.Length) % ring;
            }
        }

        // Mac testing without a mic: type a phrase (e.g. "rotate this ninety degrees around z") and press Enter.
        void OnGUI()
        {
            Event e = Event.current;
            bool enter = e.type == EventType.KeyDown &&
                        (e.keyCode == KeyCode.Return || e.keyCode == KeyCode.KeypadEnter) &&
                        GUI.GetNameOfFocusedControl() == "voicebox";
            if (enter && typed.Length > 0)
            {
                string phrase = typed;
                typed = "";
                e.Use();
                HearOrInterpret(new RecognitionResult(phrase, 1f), false);
                return;
            }
            GUI.SetNextControlName("voicebox");
            typed = GlassDesktopStatus.TextEntry(new Rect(Screen.width - 430, Screen.height - 42, 420, 32), typed);
        }

        // ---------- scene ----------

        // The one place that builds a VoiceCore SceneObject. If this line doesn't compile, only it needs fixing.
        static SceneObject MakeObject(string id, string name) => new SceneObject(id, name);

        void OnScene()
        {
            if (!host.HasCurrentScene)
            {
                ResetObjectTargeting();
                Handle(session.SetObjects(Array.Empty<SceneObject>()));
                return;
            }
            var shown = new List<KeyValuePair<string, string>>();
            host.GetShownObjects(shown);
            var list = new List<SceneObject>();
            var names = new List<string>();
            bool deleteTargetShown = false;
            foreach (var o in shown)
            {
                list.Add(MakeObject(o.Key, o.Value));
                names.Add(o.Value);
                if (deleteWaiting != null && o.Key == deleteWaiting.TargetId) deleteTargetShown = true;
            }
            if(AiConfirmationWaiting&&deleteWaiting.TargetId!=null)
            {
                var nativeTargets=new List<KeyValuePair<string,string>>();host.GetVisibleNativeObjects(nativeTargets);
                deleteTargetShown=nativeTargets.Exists(obj=>obj.Key==deleteWaiting.TargetId);
            }
            if (deleteWaiting?.TargetId != null && !deleteTargetShown) DropDelete(Prompt.TargetDeleted);
            Handle(session.SetObjects(list));
            if (SelectedObjectId != null && !list.Exists(o => o.Id == SelectedObjectId)) ClearObjectSelection();
            if (pointerId != null && !list.Exists(o => o.Id == pointerId)) SetControllerPointer(null);
            // Only when the names change (voice/README.md): a host drag sends up to 20 updates a second, and every
            // new grammar makes Vosk build a new recognizer.
            string key = string.Join("\n", names);
            if (key != grammarNames) { grammarNames = key; input?.SetGrammar(session.GrammarPhrases()); }
        }

        // ---------- turns, sending ----------

        void Handle(VoiceTurn turn)
        {
            VoiceCommand vc = turn.Command;
            // A new command or a new question (VoiceCore decides: turn.CancelsDelete, #146) replaces a delete that waits
            // for its confirmation, so the trigger can't confirm a delete the panel no longer shows. Cancel cancels it
            // instead (CancelPressed).
            if (deleteWaiting != null && turn.CancelsDelete)
                DropDelete(Prompt.ReplacedPending);
            if (turn.NoResult != null) { heardLine = NothingLine(); resultLine = ""; }
            // Words that weren't an answer closed the host's question (Update hides the panel); a command in them
            // follows in this turn and its result replaces this line.
            if (turn.ChoiceDismissed) resultLine = "Question closed.";
            foreach (Prompt p in turn.Prompts) Enqueue(p, turn.HostReason);
            if (turn.HostReason != null) resultLine = turn.HostReason;
            // #146: grammar changes (a question narrows it to its answers) and requests for the host's resolver.
            if (turn.GrammarChanged) input?.SetGrammar(session.GrammarPhrases());
            if (turn.Resolve != null)
            {
                long? g = turn.Resolve.TargetId != null && host.TryGetGeneration(turn.Resolve.TargetId, out long gen) ? gen : (long?)null;
                var voicePayload = JObject.FromObject(turn.Resolve.Payload(g));
                if (aiPendingDraft != null)
                { voicePayload["recipe"] = aiPendingDraft; voicePayload["context"] = aiExpectedContext; aiPendingDraft = null; }
                string id = host.SendVoice(VoiceResolve.Type, voicePayload);
                if (voicePayload["recipe"] != null) { aiRecipeRequest = id; aiFingerprint = CaptureAiContext().ToString(Newtonsoft.Json.Formatting.None); }
                Debug.Log($"VOICE resolve '{turn.Resolve.Text}' target {turn.Resolve.TargetId ?? "-"} sent {id ?? "(not sent)"} route={(voicePayload["recipe"] != null ? "gemini-recipe" : "basic-host")}");
                Handle(session.ResolveSent(turn.Resolve, id));
            }
            if (vc == null) return;

            HostCommand command = HostCommand.From(vc);
            if (command == null)
            {
                if (vc.Kind == CommandKind.Select && vc.TargetId != null)
                    SelectObject(vc.TargetId);
                else if (vc.Kind == CommandKind.Cancel)
                    CancelPressed();
                else if (vc.Kind != CommandKind.Select)
                    Enqueue(Prompt.Unsupported, null);   // e.g. "apply": say so instead of staying silent
                return;
            }
            if (vc.RequiresConfirmation)
            {
                deleteWaiting = vc;
                deleteExpiresAt = DateTime.UtcNow.AddSeconds(aiReview != null ? 120 : 15);
                Enqueue(vc.Kind == CommandKind.Run ? Prompt.ConfirmSequence : Prompt.ConfirmDelete, vc.Say);
                return;
            }
            Send(command);
        }

        // Esc or "cancel": drops the delete waiting for its confirmation and the pending command.
        void CancelPressed()
        {
            bool sentAiStillPending=InvalidateAi();
            PreviewInteraction.Current?.CancelDirectModelDraft("Voice / Escape cancelled the local direct edit");
            DropDelete(Prompt.Cancelled);
            Handle(session.Cancel());
            if(sentAiStillPending)
            {
                resultLine="AI edit was already sent. Waiting for Blender's actual receipt; check the model before another edit.";
                Enqueue(Prompt.Busy,resultLine);
            }
        }

        void DropDelete(Prompt why)
        {
            if (deleteWaiting == null) return;
            deleteWaiting = null;
            Enqueue(why, null);
        }

        void ConfirmDelete()
        {
            if (deleteWaiting == null) return;
            if (!CanConfirmAiReview()) return;
            HostCommand command = HostCommand.From(deleteWaiting);
            deleteWaiting = null;
            if (command != null) Send(command);
        }

        void Send(HostCommand c)
        {
            if (!host.CanSend) { Enqueue(Prompt.NotConnected, null); return; }
            bool aiOwned=IsAiRun(c);
            string id = aiOwned ? host.SendAiCommand(c.Op,c.TargetId,JObject.FromObject(c.Args),HostCommand.Source,AiContextCurrent)
                : host.SendCommand(c.Op, c.TargetId, JObject.FromObject(c.Args), HostCommand.Source);
            if (id == null)
            {
                // Connected but not sent: the target is no longer in the scene, or the socket just failed.
                Enqueue(c.TargetId != null && !host.HasObject(c.TargetId) ? Prompt.TargetDeleted : Prompt.NotConnected, null);
                return;
            }
            voiceRequests.Add(id);
            if(aiOwned)TrackAiCommand(id);
            Debug.Log($"VOICE command {c.Op} target {c.TargetId ?? "-"} args {JObject.FromObject(c.Args).ToString(Newtonsoft.Json.Formatting.None)} sent {id} after {Since()} ms");
            // Explicit selection stays latched until cleared, replaced, deleted or the document/session changes.
        }

        void OnAnswered(CommandAnswer a)
        {
            CompleteAiCommand(a.RequestId);
            if (!voiceRequests.Remove(a.RequestId)) return;   // controller/menu commands speak for themselves
            if(a.Outcome=="cancelled"&&a.ErrorCode=="cancelled_before_send")
            {resultLine="Cancelled: "+a.Message;Enqueue(Prompt.Cancelled,a.Message);return;}
            if (a.Outcome == "applied" && a.SelectionSpecified)
            {
                if (a.SelectedId == null || !SelectObject(a.SelectedId)) ClearObjectSelection();
            }
            Debug.Log($"VOICE result {a.Op} {a.Outcome} \"{a.Message}\" {a.ErrorCode} release_to_applied_ms={Since()}");
            resultLine = a.Outcome + ": " + (string.IsNullOrEmpty(a.Message) ? a.Op : a.Message);
            Enqueue(HostCommand.PromptFor(a.Op, a.Outcome, a.ErrorCode), a.Message);
        }

        // ---------- prompts ----------

        void Enqueue(Prompt p, string detail) { prompts.Enqueue(p); details.Enqueue(detail); }

        void Note(string text)
        {
            if (!SelectionPopups && IsSelectionPopup(text)) return;
            if (!ShowTranscription && text.StartsWith("Heard:", StringComparison.Ordinal)) return;
            feedback.text = string.Join("\n", VoiceDialogPages.Build(text,64,100));
            feedback.gameObject.SetActive(true);
            var cam = Camera.main;
            if (cam != null)
            {
                feedback.transform.position = cam.transform.TransformPoint(new Vector3(0f, -.43f, 1.25f));
                feedback.transform.rotation = cam.transform.rotation;
            }
            noteUntil = Time.time + Mathf.Clamp(text.Length / 18f,4f,15f);
        }

        IEnumerator PlayLoop()
        {
            while (true)
            {
                if (prompts.Count == 0) { yield return null; continue; }
                Prompt p = prompts.Dequeue();
                string detail = details.Dequeue();
                playing = true;
                Note(string.IsNullOrEmpty(detail) ? p.Text : p.Text + "\n" + detail);
                AudioClip clip = Resources.Load<AudioClip>(p.ClipResource);
                if (input != null) input.Paused = true;
                if (clip != null)
                {
                    speaker.PlayOneShot(clip);
                    yield return new WaitForSeconds(clip.length + 0.3f);   // Air Link plays audio late
                }
                else yield return new WaitForSeconds(1.5f);
                playing = false;
                if (prompts.Count == 0 && input != null) input.Paused = false;
            }
        }

        void PlaceFeedback()
        {
            var cam = Camera.main;
            if (cam == null || !feedback.gameObject.activeSelf) return;
            FitBacking(feedback);
            var bounds = feedback.GetComponent<MeshRenderer>().localBounds;
            feedback.transform.localScale = Vector3.one * Mathf.Min(1f,.95f/Mathf.Max(.001f,bounds.size.x),.35f/Mathf.Max(.001f,bounds.size.y));
        }
    }
}
