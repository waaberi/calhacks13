using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using SpatialModeling.VoiceCore;
using SpatialModeling.VoiceCore.Vosk;

namespace SpatialModeling
{
    // Connects VoiceCore to HostScene: mic -> Vosk -> VoiceSession -> command -> host, plus prompts and feedback.
    // Voice off (no model/mic) never blocks controller or menu editing.
    public class VoiceUiAdapter : MonoBehaviour
    {
        public HostScene host;
        public static void SetupText(TextMesh tm, GameObject go)
        {
            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font == null) font = Font.CreateDynamicFontFromOSFont("Arial", 32);
            tm.font = font;
            var mr = go.GetComponent<MeshRenderer>();
            if (mr == null) mr = go.AddComponent<MeshRenderer>();
            Material mat = font != null ? font.material : null;
            if (mat == null) mat = new Material(Shader.Find("GUI/Text Shader"));
            mr.sharedMaterial = mat;
        }
        VoiceSession session = new VoiceSession();
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

        InputAction talk, confirm, cancel;

        void Awake()
        {
            if (host == null) host = FindAnyObjectByType<HostScene>();

            var p = new GameObject("PendingCommandPanel");
            panel = p.AddComponent<PendingCommandPanel>();
            var f = new GameObject("VoiceFeedback");
            feedback = f.AddComponent<TextMesh>();
            feedback.fontSize = 48; feedback.characterSize = 0.012f; feedback.anchor = TextAnchor.UpperLeft;
            feedback.color = Color.white;
            SetupText(feedback, f);
            f.SetActive(false);

            speaker = gameObject.AddComponent<AudioSource>();
            speaker.spatialBlend = 0f;

            talk = new InputAction("Talk", InputActionType.Button);
            talk.AddBinding("<XRController>{RightHand}/gripPressed");
            talk.AddBinding("<Keyboard>/rightShift");
            confirm = new InputAction("ConfirmDelete", InputActionType.Button);
            confirm.AddBinding("<XRController>{RightHand}/triggerPressed");
            confirm.AddBinding("<Keyboard>/backquote");
            cancel = new InputAction("CancelPending", InputActionType.Button);
            cancel.AddBinding("<XRController>{LeftHand}/triggerPressed");
            cancel.AddBinding("<Keyboard>/escape");
            talk.started += _ => { Debug.Log("TALK down. ready=" + input?.Ready + " error=" + input?.Error); input?.StartUtterance(); };
            talk.canceled += _ => { Debug.Log("TALK up"); input?.StopUtterance(); };
            confirm.started += _ => ConfirmDelete();
            cancel.started += _ => CancelPressed();
            talk.Enable(); confirm.Enable(); cancel.Enable();
        }

        void Start()
        {
            host.SceneChanged += OnScene;
            host.ConnectionLost += () => { DropDelete(Prompt.ConnectionLost); Handle(session.ConnectionLost()); };
            host.DocumentChanged += () =>
            {
                // contracts/README.md, Wrong document: drop everything held for the old document. Object IDs survive
                // a reopen, so a waiting delete would otherwise hit the same object in the reopened file.
                DropDelete(Prompt.DocumentChanged);
                pointerId = null;   // the session forgets its pointer; report it again even if the gaze stays put
                Handle(session.DocumentChanged());
            };
            host.CommandAnswered += OnAnswered;
            StartCoroutine(PlayLoop());
            StartVoice();
            OnScene();
        }

        void StartVoice()
        {
            try
            {
                string model = Path.Combine(Application.streamingAssetsPath, VoskSpeechRecognizer.ModelName);
                input = new VoiceInput(() => VoskSpeechRecognizer.Load(model));
                if (Microphone.devices.Length == 0) { Note("No microphone. Use the text box (voice off)."); return; }
                micDevice = null;
                Microphone.GetDeviceCaps(micDevice, out int min, out int max);
                int rate = min == 0 && max == 0 ? 16000 : Mathf.Clamp(16000, min, max);
                mic = Microphone.Start(micDevice, true, 1, rate);
                chunk = new float[mic.frequency / 50 * mic.channels];
                input.SetGrammar(session.GrammarPhrases());
            }
            catch (Exception e) { Note("Voice off: " + e.Message); input = null; }
        }

        void OnDestroy()
        {
            talk?.Dispose(); confirm?.Dispose(); cancel?.Dispose();
            if (mic != null) Microphone.End(micDevice);
            input?.Dispose();
        }

        // ---------- per frame ----------

        void Update()
        {
            PumpMic();
            if (input != null)
            {
                if (input.Error != null && input.Error != shownError)
                {
                    shownError = input.Error;
                    Debug.LogWarning("VoiceUiAdapter: voice off: " + input.Error);
                    Note("Voice off: " + input.Error);
                }
                while (input.TryGetResult(out RecognitionResult result))
                {
                    Debug.Log("HEARD: " + result);
                    Note("Heard: " + result.Text);
                    Handle(session.Hear(result));
                }
            }
            Handle(session.Tick());
            UpdatePointer();

            if (deleteWaiting != null && DateTime.UtcNow >= deleteExpiresAt) DropDelete(Prompt.TimedOut);
            PendingCommand pending = session.Pending;
            if (pending != null) panel.Show(pending);
            else if (deleteWaiting != null) panel.ShowDelete(deleteWaiting.ToString(), deleteExpiresAt);
            else if (panel.Visible) panel.Hide();

            if (feedback.gameObject.activeSelf && Time.time > noteUntil && prompts.Count == 0)
                feedback.gameObject.SetActive(false);
            PlaceFeedback();
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

        void UpdatePointer()
        {
            var cam = Camera.main;
            if (cam == null) return;
            var ray = new Ray(cam.transform.position, cam.transform.forward);
            var shown = new List<KeyValuePair<string, string>>();
            host.GetShownObjects(shown);
            string best = null; float bestDist = float.MaxValue;
            foreach (var o in shown)
                if (host.TryGetBounds(o.Key, out Bounds b) && b.IntersectRay(ray, out float d) && d < bestDist)
                { best = o.Key; bestDist = d; }
            if (best != pointerId) { pointerId = best; Handle(session.SetPointerTarget(best)); }
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
                Handle(session.Hear(new RecognitionResult(phrase, 1f)));
                return;
            }
            GUI.SetNextControlName("voicebox");
            typed = GUI.TextField(new Rect(10, 10, 420, 26), typed);
        }

        // ---------- scene ----------

        // The one place that builds a VoiceCore SceneObject. If this line doesn't compile, only it needs fixing.
        static SceneObject MakeObject(string id, string name) => new SceneObject(id, name);

        void OnScene()
        {
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
            if (deleteWaiting != null && !deleteTargetShown) DropDelete(Prompt.TargetDeleted);
            Handle(session.SetObjects(list));
            // Only when the names change (voice/README.md): a host drag sends up to 20 updates a second, and every
            // new grammar makes Vosk build a new recognizer.
            string key = string.Join("\n", names);
            if (key != grammarNames) { grammarNames = key; input?.SetGrammar(session.GrammarPhrases()); }
        }

        // ---------- turns, sending ----------

        void Handle(VoiceTurn turn)
        {
            VoiceCommand vc = turn.Command;
            // A new command (complete, or a question about one) replaces a delete that waits for its confirmation,
            // as VoiceSession does with its own pending command. Cancel cancels it instead (CancelPressed).
            if (deleteWaiting != null && (vc != null ? vc.Kind != CommandKind.Cancel : session.Pending != null))
                DropDelete(Prompt.ReplacedPending);
            foreach (Prompt p in turn.Prompts) Enqueue(p, null);
            if (vc == null) return;

            HostCommand command = HostCommand.From(vc);
            if (command == null)
            {
                if (vc.Kind == CommandKind.Select && vc.TargetId != null)
                    Handle(session.SetSelection(new[] { vc.TargetId }));
                else if (vc.Kind == CommandKind.Cancel)
                    CancelPressed();
                return;
            }
            if (vc.RequiresConfirmation)
            {
                deleteWaiting = vc;
                deleteExpiresAt = DateTime.UtcNow.AddSeconds(15);
                Enqueue(Prompt.ConfirmDelete, null);
                return;
            }
            Send(command);
        }

        // Left trigger, Esc, or "cancel": drops the delete waiting for its confirmation and the pending command.
        void CancelPressed()
        {
            DropDelete(Prompt.Cancelled);
            Handle(session.Cancel());
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
            HostCommand command = HostCommand.From(deleteWaiting);
            deleteWaiting = null;
            if (command != null) Send(command);
        }

        void Send(HostCommand c)
        {
            if (!host.CanSend) { Enqueue(Prompt.NotConnected, null); return; }
            string id = host.SendCommand(c.Op, c.TargetId, JObject.FromObject(c.Args), HostCommand.Source);
            if (id == null)
            {
                // Connected but not sent: the target is no longer in the scene, or the socket just failed.
                Enqueue(c.TargetId != null && !host.HasObject(c.TargetId) ? Prompt.TargetDeleted : Prompt.NotConnected, null);
                return;
            }
            voiceRequests.Add(id);
        }

        void OnAnswered(CommandAnswer a)
        {
            if (!voiceRequests.Remove(a.RequestId)) return;   // controller/menu commands speak for themselves
            Enqueue(HostCommand.PromptFor(a.Op, a.Outcome, a.ErrorCode), a.Message);
        }

        // ---------- prompts ----------

        void Enqueue(Prompt p, string detail) { prompts.Enqueue(p); details.Enqueue(detail); }

        void Note(string text)
        {
            feedback.text = text;
            feedback.gameObject.SetActive(true);
            noteUntil = Time.time + 4f;
        }

        IEnumerator PlayLoop()
        {
            while (true)
            {
                if (prompts.Count == 0) { yield return null; continue; }
                Prompt p = prompts.Dequeue();
                string detail = details.Dequeue();
                Note(string.IsNullOrEmpty(detail) ? p.Text : p.Text + "\n" + detail);
                AudioClip clip = Resources.Load<AudioClip>(p.ClipResource);
                if (input != null) input.Paused = true;
                if (clip != null)
                {
                    speaker.PlayOneShot(clip);
                    yield return new WaitForSeconds(clip.length + 0.3f);   // Air Link plays audio late
                }
                else yield return new WaitForSeconds(1.5f);
                if (prompts.Count == 0 && input != null) input.Paused = false;
            }
        }

        void PlaceFeedback()
        {
            var cam = Camera.main;
            if (cam == null || !feedback.gameObject.activeSelf) return;
            var t = feedback.transform;
            t.position = cam.transform.TransformPoint(new Vector3(-0.35f, -0.25f, 1.1f));
            t.rotation = Quaternion.LookRotation(t.position - cam.transform.position, cam.transform.up);
        }
    }
}