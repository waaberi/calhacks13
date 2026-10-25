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
        // Capture once when content opens. Turning the head must let the wearer look across it.
        public Vector3 offset = new Vector3(0f, 0f, 1.25f);

        TextMesh text;
        PendingCommand pending;
        string composition;
        string deleting;                             // a Delete waiting for the controller confirmation
        PendingChoice choice;                        // the host's "which one?" (#146)
        DateTime expiresAt;                          // UTC, like the session clock
        string content;
        string[] pages = new[] { "" };
        int page, reviewedThrough;
        bool anchored, review;
        public bool AllPagesReviewed => reviewedThrough >= pages.Length - 1;
        public bool MovePage(int delta)
        {
            if (!Visible || pages.Length < 2) return false;
            page = Math.Max(0, Math.Min(pages.Length - 1, page + delta));
            reviewedThrough = Math.Max(reviewedThrough, page); Refresh(); return true;
        }

        void Awake()
        {
            text = gameObject.AddComponent<TextMesh>();
            text.fontSize = 48;
            text.characterSize = 0.008f;
            text.anchor = TextAnchor.MiddleCenter;
            text.alignment = TextAlignment.Left;
            text.color = new Color(1f, 0.92f, 0.45f);
            VoiceUiAdapter.SetupText(text, gameObject);
            Hide();
        }

        public bool Visible => pending != null || deleting != null || choice != null || composition != null;

        // The host's question: up to 3 numbered options and Cancel. Answered by voice ("two", "cancel") or Esc.
        public void ShowChoice(PendingChoice c)
        {
            review = false; composition = null; choice = c; pending = null; deleting = null; expiresAt = c.ExpiresAt;
            gameObject.SetActive(true);
            Refresh();
        }

        public void Show(PendingCommand p)
        {
            review = false; composition = null; pending = p; deleting = null; choice = null; expiresAt = p.ExpiresAt;
            gameObject.SetActive(true);
            Refresh();
        }

        // The confirmation stays visible for as long as the trigger would still delete.
        public void ShowDelete(string command, DateTime expiresAtUtc)
        {
            review = false; composition = null; pending = null; deleting = command; choice = null; expiresAt = expiresAtUtc;
            gameObject.SetActive(true);
            Refresh();
        }

        public void Hide() { content = null; anchored = false; composition = null; pending = null; deleting = null; choice = null; gameObject.SetActive(false); }

        public void ShowComposition(string question, DateTime expiresAtUtc, bool isReview = false)
        {
            review = isReview;
            composition = question; pending = null; deleting = null; choice = null; expiresAt = expiresAtUtc;
            gameObject.SetActive(true); Refresh();
        }

        void Refresh()
        {
            string body = "";
            if (composition != null)
                body = composition + (review ? "" : "\nNothing has run. Supply the missing detail.");
            else if (choice != null)
            {
                var lines = new System.Text.StringBuilder("Which one? Say its number" + (choice.Reason != null ? " (" + choice.Reason + ")" : "") + "\n");
                for (int i = 0; i < choice.Candidates.Count && i < 3; i++) lines.Append(choice.Candidates[i]).Append('\n');
                body = lines.ToString();
            }
            else if (deleting != null)
                body = deleting + "?\nConfirm: left stick click (`)";
            else if (pending != null)
                body = "Pending: " + pending.Command + "\n" +
                            "Missing: " + pending.Missing + "\n" +
                            ((pending.Missing & MissingFields.Target) != 0 ? "Select or look at the object" : "Say the missing value") +
                            ".";
            if (body != content)
            {
                content = body; pages = VoiceDialogPages.Build(body); page = reviewedThrough = 0; anchored = false;
            }
            string left = Math.Max(0, (expiresAt - DateTime.UtcNow).TotalSeconds).ToString("0") + "s";
            text.text = pages[page] + "\n\n" +
                (pages.Length > 1 ? "Page " + (page + 1) + "/" + pages.Length + " · say next page / previous page\n" : "") +
                (review ? (AllPagesReviewed ? "Left stick click confirms.\n" : "Review every page before confirming.\n") : "") +
                "Cancel: say cancel (Esc) · " + left;
        }

        void LateUpdate()
        {
            if (!Visible) return;
            if (head == null && Camera.main != null) head = Camera.main.transform;
            if (head == null) return;
            if (!anchored)
            {
                transform.position = head.TransformPoint(offset);
                transform.rotation = head.rotation;
                anchored = true;
            }
            Refresh();
            VoiceUiAdapter.FitBacking(text);
            var bounds = text.GetComponent<MeshRenderer>().localBounds;
            float fit = Mathf.Min(1f, .95f / Mathf.Max(.001f, bounds.size.x), .65f / Mathf.Max(.001f, bounds.size.y));
            transform.localScale = Vector3.one * fit;
        }
    }
}
