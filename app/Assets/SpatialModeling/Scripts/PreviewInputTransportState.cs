using System;

namespace SpatialModeling
{
    // Shared by the real serialized HTTP owner and managed regression checks.
    // An uncertain POST may or may not have consumed its number. Only a later
    // authoritative GET can resolve that; increment-and-retry cannot.
    public sealed class PreviewInputTransportState
    {
        public string Session { get; private set; } = "";
        public bool Synchronized { get; private set; }
        public long NextSequence { get; private set; }

        public void Observe(string session, long nextSequence)
        {
            if (string.IsNullOrEmpty(session) || nextSequence < 1) throw new ArgumentException("Invalid input session state");
            Session = session; NextSequence = nextSequence; Synchronized = true;
        }
        public long TakeSequence()
        {
            if (!Synchronized) throw new InvalidOperationException("Refresh input state after an uncertain request");
            return NextSequence++;
        }
        public void Unknown() => Synchronized = false;
    }
}
