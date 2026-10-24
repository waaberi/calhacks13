using System;
using System.Collections;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem.UI;
using UnityEngine.XR;

namespace SpatialModeling
{
    // P1 selected-window screen. Bounded two-request prefetch; never queues old frames.
    public sealed class BlenderScreen : MonoBehaviour
    {
        public bool Visible { get; private set; } = true;
        public int ReceivedFrames { get; private set; }
        public int ToggleCount { get; private set; }
        public string CaptureState { get; private set; } = "Connecting to capture helper…";
        public long LastFrame { get; private set; }
        public long LastAgeMs { get; private set; }
        public bool HasImage => image != null && image.enabled;
        public float Magnification { get; private set; } = 1f;

        const float ScreenWidth = 1800f, ScreenHeight = 1100f, ScreenDistance = 1.25f;

        GameObject canvasObject, body;
        RawImage image;
        Text status, buttonText, hint, magnifyText, modeText, roomText;
        Button toggleButton, magnifyButton, modeButton, resetButton, roomButton, pointedButton;
        Button[] buttons;
        WorkspaceInteraction interaction;
        WorkspacePassthrough passthrough;
        bool controllerHover;
        string interactionNotice = "";
        public Transform Placement => canvasObject != null ? canvasObject.transform : null;
        Texture2D texture;
        InputAction toggle, select, magnify, panAction;
        readonly UnityWebRequest[] requests = new UnityWebRequest[2];
        Vector2 pan;
        string hostNotice = "";
        bool smokeStarted;
        bool placed;
        string etag;
        long lastCaptured;
        long lastConfirmed;
        float rateStarted;
        int rateFrames;
        string lastState;
        int loggedSourceWidth, loggedSourceHeight, loggedEyeWidth, loggedEyeHeight;
        float loggedViewportScale = -1f, loggedEyeScale = -1f;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (FindFirstObjectByType<HostScene>() != null && FindFirstObjectByType<BlenderScreen>() == null)
                new GameObject("Blender live screen").AddComponent<BlenderScreen>();
            if (FindFirstObjectByType<HostScene>() != null && FindFirstObjectByType<WorkspaceInteraction>() == null)
                new GameObject("Workspace controllers").AddComponent<WorkspaceInteraction>();
            if (FindFirstObjectByType<HostScene>() != null && FindAnyObjectByType<WorkspacePassthrough>() == null)
                new GameObject("Room view").AddComponent<WorkspacePassthrough>();
        }

        void OnEnable()
        {
            Application.runInBackground = true; // Desktop Blender keeps focus while its VR screen updates.
            Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
            toggle = new InputAction("Show or hide Blender", InputActionType.Button);
            toggle.AddBinding("<XRController>{RightHand}/primaryButton"); // A
            toggle.AddBinding("<XRController>{LeftHand}/primaryButton"); // X
            toggle.AddBinding("<Keyboard>/f2");
            toggle.performed += _ => Toggle();
            toggle.Enable();
            select = new InputAction("Select Blender screen button", InputActionType.Button);
            select.AddBinding("<XRController>{RightHand}/triggerPressed");
            select.AddBinding("<XRController>{LeftHand}/triggerPressed");
            select.performed += _ => { if (interaction == null || !interaction.HasTrackedHands) pointedButton?.onClick.Invoke(); };
            select.Enable();
            magnify = new InputAction("Magnify Blender screen", InputActionType.Button);
            magnify.AddBinding("<XRController>{RightHand}/thumbstickClicked");
            magnify.AddBinding("<Keyboard>/z");
            magnify.performed += _ => { if (Visible) CycleMagnification(); };
            magnify.Enable();
            panAction = new InputAction("Pan magnified Blender screen", InputActionType.Value);
            panAction.AddBinding("<XRController>{RightHand}/thumbstick");
            panAction.AddCompositeBinding("2DVector").With("Up", "<Keyboard>/upArrow")
                .With("Down", "<Keyboard>/downArrow").With("Left", "<Keyboard>/leftArrow").With("Right", "<Keyboard>/rightArrow");
            panAction.Enable();
            StartCoroutine(Poll(0));
            StartCoroutine(Poll(1));
        }

        void OnDisable()
        {
            StopAllCoroutines();
            for (int i = 0; i < requests.Length; i++)
            {
                requests[i]?.Abort();
                requests[i]?.Dispose();
                requests[i] = null;
            }
            toggle?.Dispose();
            select?.Dispose();
            magnify?.Dispose();
            panAction?.Dispose();
            if (canvasObject != null) canvasObject.SetActive(false);
        }

        void OnDestroy()
        {
            if (texture != null) Destroy(texture);
            if (canvasObject != null) Destroy(canvasObject);
        }

        void LateUpdate()
        {
            LogDisplayQuality();
            var camera = Camera.main;
            if (camera == null) return;
            if (canvasObject == null) BuildUi(camera);
            if (!canvasObject.activeSelf) canvasObject.SetActive(true);
            if (!placed)
            {
                var workspace = FindFirstObjectByType<HostScene>();
                // Use the same settled tracked-head pose as the model placement.
                // Do not independently commit a first-frame/default camera pose.
                if (workspace != null && workspace.DisplayPlacementReady
                    && HostScene.TryGetDisplayPose(workspace.PlacementHeadPose.position,
                        workspace.PlacementHeadPose.rotation * Vector3.forward, ScreenDistance, 0f,
                        out var position, out var rotation))
                {
                    canvasObject.transform.SetPositionAndRotation(position + Vector3.up * 0.05f, rotation);
                    placed = true;
                    Debug.Log("P1_SCREEN_PLACEMENT shared_tracked_head=True");
                }
                if (!placed) canvasObject.SetActive(false);
            }
            if (interaction == null) interaction = FindFirstObjectByType<WorkspaceInteraction>();
            if (passthrough == null) passthrough = FindAnyObjectByType<WorkspacePassthrough>();
            // Keep gaze fallback for devices with no tracked hand; tracked rays select their own targets.
            var ray = new Ray(camera.transform.position, camera.transform.forward);
            pointedButton = null;
            if (interaction == null || !interaction.HasTrackedHands) foreach (var button in buttons)
            {
                var rect = button.GetComponent<RectTransform>();
                bool hovering = new Plane(rect.forward, rect.position).Raycast(ray, out float enter) && enter > 0f
                    && rect.rect.Contains((Vector2)rect.InverseTransformPoint(ray.GetPoint(enter)));
                if (hovering) pointedButton = button;
                button.GetComponent<Image>().color = hovering
                    ? new Color(0.15f, 0.5f, 0.72f, 1f) : new Color(0.08f, 0.22f, 0.33f, 1f);
            }
            if (Visible && Magnification > 1f && (interaction == null || !interaction.IsHolding))
            {
                var axis = panAction.ReadValue<Vector2>();
                if (axis.sqrMagnitude > 0.04f) pan += axis * (0.3f * Time.unscaledDeltaTime);
            }
            var crop = CropFor(Magnification, pan);
            pan = crop.center - new Vector2(0.5f, 0.5f);
            image.uvRect = crop;
            if (lastCaptured > 0 && DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - lastCaptured > 3000 && HasImage)
                Unavailable("Capture stalled — waiting for a fresh Blender frame");
            status.text = hostNotice.Length > 0 ? hostNotice : HasImage ? "Blender connected · Live view" : CaptureState;
            status.color = HasImage && hostNotice.Length == 0 ? Color.white : new Color(1f, 0.7f, 0.25f);
            buttonText.text = Visible ? "Hide Blender" : "Show Blender";
            magnifyText.text = $"Magnify: {Magnification:0.#}×";
            modeText.text = interaction != null && interaction.MoveIndividualParts ? "Arrange: one part" : "Arrange: whole build";
            roomButton.interactable = passthrough != null && passthrough.Supported;
            roomText.text = passthrough != null && passthrough.Supported
                ? passthrough.Active ? "Room view: on" : "Room view: off" : "Room view: unavailable";
            if (passthrough != null && !passthrough.Active && hostNotice.Length == 0 && HasImage)
                status.text += " · " + passthrough.State;
            hint.text = hostNotice.Length > 0 && !Visible ? hostNotice
                : interactionNotice.Length > 0 ? interactionNotice
                : "A / X: show–hide · B / Y: recenter · Grip: move screen or build";
            hint.color = hostNotice.Length > 0 && !Visible ? new Color(1f, 0.7f, 0.25f) : Color.white;
            if (!smokeStarted && Array.IndexOf(Environment.GetCommandLineArgs(), "--p1-smoke") >= 0)
            {
                smokeStarted = true;
                StartCoroutine(Smoke());
            }
        }

        void LogDisplayQuality()
        {
            if (texture == null) return;
            int eyeWidth = XRSettings.eyeTextureWidth, eyeHeight = XRSettings.eyeTextureHeight;
            float viewport = XRSettings.renderViewportScale, eyeScale = XRSettings.eyeTextureResolutionScale;
            if (texture.width == loggedSourceWidth && texture.height == loggedSourceHeight
                && eyeWidth == loggedEyeWidth && eyeHeight == loggedEyeHeight
                && viewport == loggedViewportScale && eyeScale == loggedEyeScale) return;
            loggedSourceWidth = texture.width; loggedSourceHeight = texture.height;
            loggedEyeWidth = eyeWidth; loggedEyeHeight = eyeHeight;
            loggedViewportScale = viewport; loggedEyeScale = eyeScale;
            var pipeline = UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline
                as UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset;
            Debug.Log($"P1_DISPLAY_QUALITY source={texture.width}x{texture.height} eye={eyeWidth}x{eyeHeight} eye_scale={eyeScale:F2} viewport_scale={viewport:F2} pipeline_scale={pipeline?.renderScale:F2} msaa={pipeline?.msaaSampleCount} filter={texture.filterMode} mips={texture.mipmapCount}");
        }

        public void Toggle()
        {
            Visible = !Visible;
            ToggleCount++;
            if (body != null) body.SetActive(Visible);
            Debug.Log($"P1_SCREEN_TOGGLE visible={Visible} count={ToggleCount}");
        }

        public void RequestRecenter() => placed = false;

        public void SetHostNotice(string message) => hostNotice = message ?? "";
        public void SetInteractionNotice(string message) => interactionNotice = message ?? "";

        public bool RaycastSurface(Ray ray, out float distance)
        {
            distance = 0f;
            if (Placement == null || !canvasObject.activeInHierarchy) return false;
            if (!new Plane(Placement.forward, Placement.position).Raycast(ray, out distance) || distance < 0f || distance > 4f) return false;
            var local = Placement.InverseTransformPoint(ray.GetPoint(distance));
            return Mathf.Abs(local.x) <= 920 && local.y >= -820 && local.y <= (Visible ? 695 : -560);
        }

        public bool HoverController(Ray ray, bool pressed)
        {
            if (!RaycastSurface(ray, out var distance)) return false;
            foreach (var button in buttons)
            {
                if (!button.interactable) continue;
                var rect = button.GetComponent<RectTransform>();
                if (!rect.rect.Contains((Vector2)rect.InverseTransformPoint(ray.GetPoint(distance)))) continue;
                button.GetComponent<Image>().color = new Color(0.15f, 0.5f, 0.72f, 1f);
                controllerHover = true;
                if (pressed) button.onClick.Invoke();
                return true;
            }
            return false;
        }

        public void ClearControllerHover()
        {
            if (buttons == null) return;
            if (controllerHover) foreach (var button in buttons) button.GetComponent<Image>().color = new Color(0.08f, 0.22f, 0.33f, 1f);
            controllerHover = false;
        }

        public void Resize(float multiplier)
        {
            if (Placement != null) Placement.localScale = Vector3.one * Mathf.Clamp(Placement.localScale.x * multiplier, 0.00045f, 0.0018f);
        }

        public void CycleMagnification()
        {
            Magnification = Magnification < 1.4f ? 1.5f : Magnification < 1.9f ? 2f : 1f;
            pan = Vector2.zero;
            Debug.Log($"P1_SCREEN_MAGNIFY factor={Magnification}");
        }

        public static Rect CropFor(float magnification, Vector2 offset)
        {
            float size = 1f / Mathf.Clamp(magnification, 1f, 3f);
            float half = size * 0.5f;
            var center = new Vector2(Mathf.Clamp(0.5f + offset.x, half, 1f - half),
                Mathf.Clamp(0.5f + offset.y, half, 1f - half));
            return new Rect(center.x - half, center.y - half, size, size);
        }

        void BuildUi(Camera camera)
        {
            canvasObject = new GameObject("Blender screen canvas", typeof(RectTransform), typeof(Canvas), typeof(GraphicRaycaster));
            canvasObject.transform.SetPositionAndRotation(camera.transform.position + camera.transform.forward * ScreenDistance, camera.transform.rotation);
            canvasObject.transform.localScale = Vector3.one * 0.001f;
            canvasObject.GetComponent<RectTransform>().sizeDelta = new Vector2(1840, 1450);
            var canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = camera;
            if (FindFirstObjectByType<EventSystem>() == null)
                new GameObject("Screen UI events", typeof(EventSystem), typeof(InputSystemUIInputModule));
            body = Rect("Live Blender window", canvasObject.transform, new Vector2(0, 70), new Vector2(1840, 1250));
            var background = body.AddComponent<Image>();
            background.color = new Color(0.015f, 0.02f, 0.03f, 0.98f);
            background.raycastTarget = false;
            Label("Title", body.transform, new Vector2(0, 580), new Vector2(1800, 60), "BLENDER", 32);
            var imageObject = Rect("Selected window image", body.transform, Vector2.zero, new Vector2(ScreenWidth, ScreenHeight));
            image = imageObject.AddComponent<RawImage>();
            image.raycastTarget = false;
            image.enabled = false;
            status = Label("Capture state", body.transform, new Vector2(0, -585), new Vector2(1800, 65), CaptureState, 32);
            var control = Rect("Show hide button", canvasObject.transform, new Vector2(-670, -610), new Vector2(420, 80));
            control.AddComponent<Image>();
            toggleButton = control.AddComponent<Button>();
            toggleButton.onClick.AddListener(Toggle);
            buttonText = Label("Label", control.transform, Vector2.zero, new Vector2(400, 65), "Hide Blender", 32);
            var zoomControl = Rect("Magnify button", canvasObject.transform, new Vector2(-230, -610), new Vector2(420, 80));
            zoomControl.AddComponent<Image>();
            magnifyButton = zoomControl.AddComponent<Button>();
            magnifyButton.onClick.AddListener(CycleMagnification);
            magnifyText = Label("Label", zoomControl.transform, Vector2.zero, new Vector2(400, 65), "Magnify: 1×", 32);
            var modeControl = Rect("Arrangement mode", canvasObject.transform, new Vector2(330, -610), new Vector2(600, 80));
            modeControl.AddComponent<Image>();
            modeButton = modeControl.AddComponent<Button>();
            modeButton.onClick.AddListener(() => interaction?.TogglePartMode());
            modeText = Label("Label", modeControl.transform, Vector2.zero, new Vector2(580, 65), "Arrange: whole build", 30);
            var resetControl = Rect("Reset arrangement", canvasObject.transform, new Vector2(780, -610), new Vector2(280, 80));
            resetControl.AddComponent<Image>();
            resetButton = resetControl.AddComponent<Button>();
            resetButton.onClick.AddListener(() => interaction?.ResetArrangement());
            Label("Label", resetControl.transform, Vector2.zero, new Vector2(260, 65), "Reset view", 30);
            var roomControl = Rect("Room view", canvasObject.transform, new Vector2(640, -730), new Vector2(560, 80));
            roomControl.AddComponent<Image>();
            roomButton = roomControl.AddComponent<Button>();
            roomButton.onClick.AddListener(() => passthrough?.Toggle());
            roomText = Label("Label", roomControl.transform, Vector2.zero, new Vector2(540, 65), "Room view: checking", 30);
            hint = Label("Controls", canvasObject.transform, new Vector2(-300, -735), new Vector2(1200, 120), "", 28);
            buttons = new[] { toggleButton, magnifyButton, modeButton, resetButton, roomButton };
            foreach (var button in buttons) button.GetComponent<Image>().color = new Color(0.08f, 0.22f, 0.33f, 1f);
            body.SetActive(Visible);
        }

        static GameObject Rect(string name, Transform parent, Vector2 position, Vector2 size)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            var rect = go.GetComponent<RectTransform>();
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
            return go;
        }

        static Text Label(string name, Transform parent, Vector2 position, Vector2 size, string value, int fontSize)
        {
            var go = Rect(name, parent, position, size);
            var text = go.AddComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize = fontSize;
            text.alignment = TextAnchor.MiddleCenter;
            text.color = Color.white;
            text.text = value;
            text.raycastTarget = false;
            return text;
        }

        void Unavailable(string message)
        {
            CaptureState = message;
            etag = null;
            if (image != null) { image.enabled = false; image.texture = null; }
            if (texture != null) { Destroy(texture); texture = null; }
        }

        IEnumerator Poll(int lane)
        {
            while (image == null) yield return null;
            if (lane == 1) yield return null; // Stagger a bounded two-request prefetch.
            while (true)
            {
                if (image == null) { yield return null; continue; }
                // Keep checking when hidden: reopening never shows a queued/stale frame.
                // Native DownloadHandlerTexture decodes off the render thread.
                var request = UnityWebRequestTexture.GetTexture(P1PipelineProfile.CaptureUrl(), true);
                requests[lane] = request;
                request.timeout = 2;
                if (etag != null) request.SetRequestHeader("If-None-Match", etag);
                long requestAt = P1PipelineProfile.Now();
                yield return request.SendWebRequest();
                P1PipelineProfile.End("request_with_worker_decode_ms", requestAt);
                P1PipelineProfile.Add("http_status/" + request.responseCode, 1);
                P1PipelineProfile.Add("downloaded_bytes", request.downloadedBytes);
                if (request.responseCode == 200 && request.result == UnityWebRequest.Result.Success)
                {
                    if (!long.TryParse(request.GetResponseHeader("X-Captured-At"), out var captured)
                        || !long.TryParse(request.GetResponseHeader("X-Capture-Alive"), out var alive)
                        || !CaptureIsFresh(captured, alive, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())
                        || request.downloadedBytes > 8 * 1024 * 1024)
                        Unavailable("Capture returned an invalid or old frame");
                    else
                    {
                        long contentAt = P1PipelineProfile.Now();
                        var decoded = DownloadHandlerTexture.GetContent(request);
                        P1PipelineProfile.End("get_decoded_texture_ms", contentAt);
                        if (decoded == null) Unavailable("Cannot decode Blender image");
                        else if (captured <= lastCaptured && HasImage)
                        {
                            // The other lane already presented this frame or a newer
                            // one. Never count duplicates or roll the display back.
                            Destroy(decoded);
                            lastConfirmed = Math.Max(lastConfirmed, alive);
                        }
                        else
                        {
                            long assignmentAt = P1PipelineProfile.Now();
                            if (texture != null) Destroy(texture);
                            texture = decoded;
                            texture.filterMode = FilterMode.Trilinear;
                            texture.anisoLevel = 4;
                            image.texture = texture;
                            image.enabled = true;
                            var scale = Mathf.Min(ScreenWidth / texture.width, ScreenHeight / texture.height);
                            image.rectTransform.sizeDelta = new Vector2(texture.width * scale, texture.height * scale);
                            P1PipelineProfile.End("destroy_filter_assign_texture_ms", assignmentAt);
                            lastCaptured = captured;
                            lastConfirmed = alive;
                            etag = request.GetResponseHeader("ETag");
                            long.TryParse(etag?.Trim('"'), out var frame);
                            LastFrame = frame;
                            LastAgeMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - captured;
                            ReceivedFrames++;
                            if (rateStarted <= 0f) rateStarted = Time.realtimeSinceStartup;
                            rateFrames++;
                            if (Time.realtimeSinceStartup - rateStarted >= 2f)
                            {
                                Debug.Log($"P1_SCREEN_RATE fps={rateFrames / (Time.realtimeSinceStartup - rateStarted):F1} age_ms={LastAgeMs} frames={rateFrames}");
                                rateStarted = Time.realtimeSinceStartup;
                                rateFrames = 0;
                            }
                            CaptureState = $"Live Blender · {texture.width} × {texture.height} · frame {frame} · age {LastAgeMs} ms";
                            if (ReceivedFrames == 1 || ReceivedFrames % 50 == 0)
                                Debug.Log($"P1_CAPTURE_FRAME frame={frame} age_ms={LastAgeMs} size={texture.width}x{texture.height}");
                        }
                    }
                }
                else if (request.responseCode == 304)
                {
                    // A live HTTP server cannot certify arbitrarily old pixels.
                    if (long.TryParse(request.GetResponseHeader("X-Capture-Alive"), out var alive)
                        && long.TryParse(request.GetResponseHeader("X-Captured-At"), out var captured)
                        && CaptureIsFresh(captured, alive, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()))
                        lastConfirmed = alive;
                    else Unavailable("Capture stalled — waiting for a fresh Blender frame");
                }
                else
                {
                    string message = "Capture helper unavailable — start it and select Blender";
                    if (request.responseCode == 503)
                    {
                        try { message = (string)JObject.Parse(request.downloadHandler.text)["message"]; }
                        catch (Exception) { message = "Blender capture unavailable"; }
                    }
                    Unavailable(message);
                }
                if (CaptureState != lastState && !CaptureState.StartsWith("Live Blender")) Debug.Log("P1_CAPTURE_STATE " + CaptureState);
                lastState = CaptureState;
                bool retryBackoff = request.responseCode != 200 && request.responseCode != 304;
                long disposeAt = P1PipelineProfile.Now();
                request.Dispose();
                P1PipelineProfile.End("request_dispose_ms", disposeAt);
                requests[lane] = null;
                // The request itself yields. No extra 100ms sleep or second-frame
                // delay: a fresh image can be presented on every render frame.
                if (retryBackoff) yield return new WaitForSecondsRealtime(0.25f);
            }
        }

        IEnumerator Smoke()
        {
            float until = Time.realtimeSinceStartup + 30;
            // A static selected window legitimately has one unique compositor frame.
            // Validate a decoded image plus recent service health, not fabricated updates.
            while (!HasImage && Time.realtimeSinceStartup < until) yield return null;
            bool passed = ReceivedFrames >= 1 && HasImage
                && CaptureIsFresh(lastCaptured, lastConfirmed, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            for (int i = 0; i < 10; i++)
            {
                Toggle();
                yield return new WaitForSecondsRealtime(0.15f);
                passed &= body.activeSelf == Visible;
            }
            passed &= Visible && ToggleCount == 10 && HasImage;
            CycleMagnification();
            passed &= Magnification == 1.5f;
            CycleMagnification();
            passed &= Magnification == 2f;
            var edge = CropFor(2f, new Vector2(10f, -10f));
            passed &= edge.xMin >= 0f && edge.yMin >= 0f && edge.xMax <= 1f && edge.yMax <= 1f;
            CycleMagnification();
            passed &= Magnification == 1f;
            passed &= CaptureIsFresh(lastCaptured, lastConfirmed, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            Debug.Log($"P1_SCREEN_SMOKE {(passed ? "PASS" : "FAIL")} frames={ReceivedFrames} toggles={ToggleCount} current_pixel_age_ms={DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - lastCaptured}");
            WorkspaceShutdown.Quit(passed ? 0 : 1);
        }

        public static bool CaptureIsFresh(long captured, long alive, long now) => captured > 0 && alive >= captured
            && captured <= now + 1000 && alive <= now + 1000 && now - captured <= 3000 && now - alive <= 3000;
    }
}
