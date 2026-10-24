#if UNITY_EDITOR_OSX
using UnityEditor;
using UnityEngine;

namespace SpatialModeling.App
{
    /// <summary>On a Mac there is no Link headset, so play mode in the editor starts the XR Device Simulator
    /// (keyboard and mouse drive a simulated headset and controllers). XRI's own "Use XR Device Simulator in
    /// scenes" option stays off: it would also start in the Windows editor over Link, where the simulator
    /// removes the real headset.</summary>
    static class MacEditorDeviceSimulator
    {
        // "XR Device Simulator.prefab" from the XR Interaction Toolkit sample in Assets/Samples.
        const string k_PrefabGuid = "18ddb545287c546e19cc77dc9fbb2189";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Spawn()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(k_PrefabGuid));
            if (prefab == null)
            {
                Debug.LogWarning("XR Device Simulator sample is missing. Import it from the XR Interaction Toolkit package in the Package Manager.");
                return;
            }

            var simulator = Object.Instantiate(prefab);
            simulator.name = prefab.name;
            Object.DontDestroyOnLoad(simulator);
        }
    }
}
#endif
