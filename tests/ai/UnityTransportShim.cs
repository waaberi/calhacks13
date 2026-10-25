// Only a compile/transport test surface. Unity production uses UnityWebRequest;
// these tests execute its production orchestration against explicit fake replies.
using System;
using System.IO;
using System.Text;

namespace UnityEngine
{
    public static class Application
    {
        public static string dataPath => Path.Combine(Path.GetTempPath(),"CodexModelingAiNoProject","Assets");
        public static string persistentDataPath => Path.Combine(Path.GetTempPath(),"CodexModelingAiNoPreferences");
    }
}
namespace UnityEngine.Networking
{
    public class UploadHandlerRaw { public byte[] data; public UploadHandlerRaw(byte[] bytes) { data=bytes; } }
    public class DownloadHandlerBuffer { public string text=""; }
    public sealed class UnityWebRequest : IDisposable
    {
        public enum Result { Success, ConnectionError, ProtocolError }
        public static Func<UnityWebRequest,(long status,string body)> Responder;
        public string url, method;
        public string Body => Encoding.UTF8.GetString(uploadHandler.data);
        public UploadHandlerRaw uploadHandler;
        public DownloadHandlerBuffer downloadHandler;
        public long responseCode;
        public Result result;
        public int timeout;
        public bool HasKeyHeader;
        public UnityWebRequest(string endpoint,string verb) { url=endpoint;method=verb; }
        public void SetRequestHeader(string name,string value) { if(name=="x-goog-api-key") HasKeyHeader=!string.IsNullOrWhiteSpace(value); }
        public object SendWebRequest()
        {
            if(Responder==null)throw new InvalidOperationException("An explicit fake responder is required");
            var reply=Responder(this);responseCode=reply.status;downloadHandler.text=reply.body;
            result=responseCode==200?Result.Success:responseCode==0?Result.ConnectionError:Result.ProtocolError;
            return null;
        }
        public void Abort() { result=Result.ConnectionError; }
        public void Dispose() { }
    }
}
