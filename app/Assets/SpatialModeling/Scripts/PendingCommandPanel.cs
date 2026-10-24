using System;
using UnityEngine;
using SpatialModeling.VoiceCore;

namespace SpatialModeling
{
    // World-space text panel: shows the remembered voice command, what is still missing,
    // a countdown, and how to cancel. UI only; the adapter decides when to Show/Hide.
    public class PendingCommandPanel : MonoBehaviour
    {
        public Transform head;                       // defaults to Camera.main
        public Vector3 offset = new Vector3(0f, 0.25f, 1.1f);

        TextMesh text;
        PendingCommand pending;

        void Awake()
        {
            text = gameObject.AddComponent<TextMesh>();
            text.fontSize = 48;
            text.characterSize = 0.008f;
            text.anchor = TextAnchor.UpperCenter;
            text.color = new Color(1f, 0.92f, 0.45f);
            VoiceUiAdapter.SetupText(text, gameObject);
            Hide();
        }

        public bool Visible => pending != null;

        public void Show(PendingCommand p) { pending = p; gameObject.SetActive(true); Refresh(); }

        public void Hide() { pending = null; gameObject.SetActive(false); }

        void Refresh()
        {
            if (pending == null) return;
            double left = Math.Max(0, (pending.ExpiresAt - DateTime.UtcNow).TotalSeconds);
            text.text = "Pending: " + pending.Command + "\n" +
                        "Missing: " + pending.Missing + "\n" +
                        "Select a target, or Cancel (" + left.ToString("0") + "s)";
        }

        void LateUpdate()
        {
            if (pending == null) return;
            if (head == null && Camera.main != null) head = Camera.main.transform;
            if (head == null) return;
            transform.position = head.TransformPoint(offset);
            transform.rotation = Quaternion.LookRotation(transform.position - head.position);
            Refresh();
        }
    }
}