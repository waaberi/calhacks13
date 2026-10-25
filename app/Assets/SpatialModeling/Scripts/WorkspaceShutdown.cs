using System.Collections;
using System.Runtime.InteropServices;
using UnityEngine;

namespace SpatialModeling
{
    // Release Windows UIA providers while the Player window and its providers are
    // still alive. Doing this during window destruction can re-enter an already
    // destroyed provider through WM_GETOBJECT (#125).
    public sealed class WorkspaceShutdown : MonoBehaviour
    {
        static WorkspaceShutdown instance;
        bool pending, ready;
        int exitCode;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Install()
        {
            instance = new GameObject("Workspace shutdown").AddComponent<WorkspaceShutdown>();
            DontDestroyOnLoad(instance.gameObject);
        }

        void OnEnable() => Application.wantsToQuit += WantsToQuit;
        void OnDisable() => Application.wantsToQuit -= WantsToQuit;

        public static void Quit(int code = 0)
        {
            if (instance != null) instance.exitCode = code;
            Application.Quit(code);
        }

        bool WantsToQuit()
        {
#if UNITY_STANDALONE_WIN && !UNITY_EDITOR
            if (ready) return true;
            if (!pending)
            {
                pending = true;
                StartCoroutine(PrepareQuit());
            }
            return false;
#else
            return true;
#endif
        }

        IEnumerator PrepareQuit()
        {
            // Leave the close-message handler. UIA disconnection must not be
            // called in a synchronous SendMessage handler (Microsoft API contract).
            yield return null;
            yield return null;
#if UNITY_STANDALONE_WIN && !UNITY_EDITOR
            if (InSendMessageEx(System.IntPtr.Zero) != 0)
            {
                Debug.LogWarning("P1_SHUTDOWN UIA release deferred from synchronous window message");
                yield return null;
            }
            int result = UiaDisconnectAllProviders();
            Debug.Log($"P1_SHUTDOWN UIA providers released hr=0x{result:X8}");
#endif
            ready = true;
            Application.Quit(exitCode);
        }

#if UNITY_STANDALONE_WIN && !UNITY_EDITOR
        [DllImport("UIAutomationCore.dll", ExactSpelling = true)]
        static extern int UiaDisconnectAllProviders();
        [DllImport("user32.dll", ExactSpelling = true)]
        static extern uint InSendMessageEx(System.IntPtr reserved);
#endif
    }
}
