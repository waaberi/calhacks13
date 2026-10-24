using System;
using System.Collections;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace SpatialModeling
{
    // A disabled component cannot finish its own coroutine. This independent,
    // bounded cleanup owner only releases input, then ends native permission.
    // A model operation is never retried, and failed release never proves safety.
    public sealed class PreviewInputCleanup : MonoBehaviour
    {
        public void Begin(string baseUrl, string captureInstance, Action released)
        {
            DontDestroyOnLoad(gameObject);
            StartCoroutine(Cleanup(baseUrl, captureInstance, released));
        }
        IEnumerator Cleanup(string baseUrl, string captureInstance, Action released)
        {
            if (baseUrl == null) { Destroy(gameObject); yield break; }
            for (int attempt = 0; attempt < 3; attempt++)
            {
                JObject state = null;
                using (var get = UnityWebRequest.Get(baseUrl + "/input/state"))
                {
                    get.timeout = 2; yield return get.SendWebRequest();
                    if (get.result == UnityWebRequest.Result.Success)
                    { try { state = JObject.Parse(get.downloadHandler.text); } catch (Exception) { } }
                }
                if (state == null || string.IsNullOrEmpty((string)state["token"]) || string.IsNullOrEmpty((string)state["session"])) continue;
                if (!string.IsNullOrEmpty(captureInstance) && captureInstance != (string)state["capture_instance"]) break;
                var payload = new JObject { ["type"] = "release", ["session"] = state["session"], ["token"] = state["token"], ["seq"] = state["next_seq"] };
                using (var post = new UnityWebRequest(baseUrl + "/input", "POST"))
                {
                    post.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(payload.ToString(Newtonsoft.Json.Formatting.None)));
                    post.downloadHandler = new DownloadHandlerBuffer(); post.SetRequestHeader("Content-Type", "application/json");
                    post.timeout = 2; yield return post.SendWebRequest();
                    if (post.result == UnityWebRequest.Result.Success)
                    {
                        released?.Invoke(); Destroy(gameObject); yield break;
                    }
                }
            }
            Debug.LogWarning("P2.5 input cleanup could not confirm release. Native reservation remains until connection cleanup/native modal completion.");
            Destroy(gameObject);
        }
    }
}
