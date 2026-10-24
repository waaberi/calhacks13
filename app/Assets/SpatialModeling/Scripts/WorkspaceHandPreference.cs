using System;
using UnityEngine;
using UnityEngine.XR;

namespace SpatialModeling
{
    public static class WorkspaceHandPreference
    {
        const string Key = "SpatialModeling.PrimaryHand";
        public static bool Left => PlayerPrefs.GetString(Key, "Right") == "Left";
        public static XRNode Primary => Left ? XRNode.LeftHand : XRNode.RightHand;
        public static XRNode MenuHand => Left ? XRNode.RightHand : XRNode.LeftHand;
        public static string Controller => Left ? "<XRController>{LeftHand}" : "<XRController>{RightHand}";
        public static event Action Changed;
        public static void SetLeft(bool left)
        {
            PlayerPrefs.SetString(Key, left ? "Left" : "Right");
            PlayerPrefs.Save();
            Changed?.Invoke();
        }
    }
}
