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
        // Bottom edge of the text, in head space. Above HostScene's status panel (0.95 x 0.19 m at (0, 0.10, 1) in
        // camera space), which otherwise covers the lower lines.
        public Vector3 offset = new Vector3(0f, 0.24f, 1.1f);

        TextMesh text;
        PendingCommand pending;
        string deleting;                             // a Delete waiting for the controller confirmation
        PendingChoice choice;                        // the host's "which one?" (#146)
        DateTime expiresAt;                          // UTC, like the session clock

        void Awake()
        {
            text = gameObject.AddComponent<TextMesh>();
            text.fontSize = 48;
            text.characterSize = 0.008f;
            text.anchor = TextAnchor.LowerCenter;
            text.color = new Color(1f, 0.92f, 0.45f);
            VoiceUiAdapter.SetupText(text, gameObject);
            Hide();
        }

        public bool Visible => pending != null || deleting != null || choice != null;

        // The host's question: up to 3 numbered options and Cancel. Answered by voice ("two", "cancel") or Esc.
        public void ShowChoice(PendingChoice c)
        {
            choice = c; pending = null; deleting = null; expiresAt = c.ExpiresAt;
            gameObject.SetActive(true);
            Refresh();
        }

        public void Show(PendingCommand p)
        {
            pending = p; deleting = null; choice = null; expiresAt = p.ExpiresAt;
            gameObject.SetActive(true);
            Refresh();
        }

        // The confirmation stays visible for as long as the trigger would still delete.
        public void ShowDelete(string command, DateTime expiresAtUtc)
        {
            pending = null; deleting = command; choice = null; expiresAt = expiresAtUtc;
            gameObject.SetActive(true);
            Refresh();
        }

        public void Hide() { pending = null; deleting = null; choice = null; gameObject.SetActive(false); }

        void Refresh()
        {
            string left = Math.Max(0, (expiresAt - DateTime.UtcNow).TotalSeconds).ToString("0") + "s";
            if (choice != null)
            {
                var lines = new System.Text.StringBuilder("Which one? Say its number" + (choice.Reason != null ? " (" + choice.Reason + ")" : "") + "\n");
                for (int i = 0; i < choice.Candidates.Count && i < 3; i++) lines.Append(choice.Candidates[i]).Append('\n');
                lines.Append("Cancel: say cancel, or left trigger (Esc) (" + left + ")");
                text.text = lines.ToString();
            }
            else if (deleting != null)
                text.text = deleting + "?\n" +
                            "Confirm: right trigger (`)\n" +
                            "Cancel: left trigger (Esc) (" + left + ")";
            else if (pending != null)
                text.text = "Pending: " + pending.Command + "\n" +
                            "Missing: " + pending.Missing + "\n" +
                            ((pending.Missing & MissingFields.Target) != 0 ? "Select or look at the object" : "Say the missing value") +
                            ", or cancel: left trigger (Esc) (" + left + ")";
        }

        void LateUpdate()
        {
            if (!Visible) return;
            if (head == null && Camera.main != null) head = Camera.main.transform;
            if (head == null) return;
            transform.position = head.TransformPoint(offset);
            transform.rotation = Quaternion.LookRotation(transform.position - head.position, head.up);
            Refresh();
            VoiceUiAdapter.FitBacking(text);
        }
    }
}
