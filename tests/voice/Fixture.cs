using System;
using System.Linq;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>A session with a controllable clock and a few objects.</summary>
    sealed class Fixture
    {
        public static readonly SceneObject Cube = new SceneObject("id-cube", "Cube");
        public static readonly SceneObject Sphere = new SceneObject("id-sphere", "Sphere");
        public static readonly SceneObject Cylinder = new SceneObject("id-cylinder", "Cylinder");

        public DateTime Now = new DateTime(2026, 10, 24, 19, 0, 0, DateTimeKind.Utc);
        public readonly VoiceSessionOptions Options = new VoiceSessionOptions();
        public readonly VoiceSession Session;

        public Fixture(params SceneObject[] objects)
        {
            Session = new VoiceSession(Options, () => Now);
            Session.SetObjects(objects);
        }

        public VoiceTurn Say(string text, float confidence = 0.95f) => Session.Hear(new RecognitionResult(text, confidence));

        public VoiceTurn Select(params SceneObject[] objects) => Session.SetSelection(objects.Select(o => o.Id));

        public void Wait(double seconds) => Now = Now.AddSeconds(seconds);

        public static string[] Prompts(VoiceTurn turn) => turn.Prompts.Select(p => p.Id).ToArray();
    }
}
