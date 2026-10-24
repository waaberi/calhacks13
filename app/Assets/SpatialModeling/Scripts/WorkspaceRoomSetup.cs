using UnityEngine;

namespace SpatialModeling
{
    // PC room setup uses the system's saved scene; system capture runs on Quest.
    public sealed class WorkspaceRoomSetup : MonoBehaviour
    {
        public bool IsOpen { get; private set; }
        public bool ShowingHandoff { get; private set; }
        public string Heading => ShowingHandoff
            ? "Scan / update on Quest\nLeave Link → open Room Setup companion\nFinish Meta Space Setup → reconnect Link"
            : "Environment setup\nLoad your saved Meta room first\nScan/update on Quest only when needed";
        public void Open() { IsOpen=true;ShowingHandoff=false; }
        public void Close() { IsOpen=false;ShowingHandoff=false; }
        public void Scan() { ShowingHandoff=true; }
    }
}
