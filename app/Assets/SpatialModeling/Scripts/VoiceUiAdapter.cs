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

        VoiceCommand deleteWaiting;
        float deleteUntil;
        string pointerId;
        string typed = "";

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
            cancel.started += _ => Handle(session.Cancel());
            talk.Enable(); confirm.Enable(); cancel.Enable();
        }

        void Start()
        {
            host.SceneChanged += OnScene;
            host.ConnectionLost += () => Handle(session.ConnectionLost());
            host.DocumentChanged += () => Handle(session.DocumentChanged());
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
                if (input.Error != null && Time.time > noteUntil) Note("Voice off: " + input.Error);
                while (input.TryGetResult(out RecognitionResult result))
                {
                    Debug.Log("HEARD: " + result);
                    Note("Heard: " + result.Text);
                    Handle(session.Hear(result));
                }
            }
            Handle(session.Tick());
            UpdatePointer();

            PendingCommand pending = session.Pending;
            if (pending != null) panel.Show(pending); else if (panel.Visible) panel.Hide();

            if (deleteWaiting != null && Time.time > deleteUntil) deleteWaiting = null;
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
            foreach (var o in shown) list.Add(MakeObject(o.Key, o.Value));
            Handle(session.SetObjects(list));
            input?.SetGrammar(session.GrammarPhrases());
        }

        // ---------- turns, sending ----------

        void Handle(VoiceTurn turn)
        {
            foreach (Prompt p in turn.Prompts) Enqueue(p, null);
            VoiceCommand vc = turn.Command;
            if (vc == null) return;

            HostCommand command = HostCommand.From(vc);
            if (command == null)
            {
                if (vc.Kind == CommandKind.Select && vc.TargetId != null)
                    Handle(session.SetSelection(new[] { vc.TargetId }));
                else if (vc.Kind == CommandKind.Cancel)
                    Handle(session.Cancel());
                return;
            }
            if (vc.RequiresConfirmation)
            {
                deleteWaiting = vc;
                deleteUntil = Time.time + 15f;
                Enqueue(Prompt.ConfirmDelete, null);
                return;
            }
            Send(command);
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
            string id = host.CanSend
                ? host.SendCommand(c.Op, c.TargetId, JObject.FromObject(c.Args), HostCommand.Source)
                : null;
            if (id == null) { Enqueue(Prompt.NotConnected, null); return; }
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
            t.rotation = Quaternion.LookRotation(t.position - cam.transform.position);
        }
    }
}