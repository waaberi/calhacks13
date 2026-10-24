namespace SpatialModeling
{
    // Main-thread admission for the existing two HTTP slots. Headers can reserve
    // a fresh frame while its JPEG is still decoding; reservation never presents
    // pixels or renews their age. Complete responses retain all display checks.
    public sealed class CaptureRequestLanes
    {
        public enum Decision { Pending, Continue, Duplicate, Invalidated }
        struct Claim { public int epoch; public string tag; public long captured; }
        readonly Claim[] claims = new Claim[2];
        int epoch;
        string reservedTag;
        long reservedCaptured, presentedCaptured;

        public int Begin(int lane)
        {
            claims[lane] = new Claim { epoch = epoch };
            return epoch;
        }

        public bool IsCurrent(int ticket) => ticket == epoch;
        public string ConditionalTag(string displayedTag) => reservedTag ?? displayedTag;

        public Decision Observe(int lane, int ticket, string tag, long captured, long alive, long now)
        {
            if (!IsCurrent(ticket)) return Decision.Invalidated;
            if (string.IsNullOrEmpty(tag) || !BlenderScreen.CaptureIsFresh(captured, alive, now))
                return Decision.Pending;
            if (presentedCaptured > 0 && captured <= presentedCaptured) return Decision.Duplicate;
            for (int other = 0; other < claims.Length; other++)
                if (other != lane && claims[other].epoch == epoch && claims[other].tag == tag
                    && claims[other].captured == captured) return Decision.Duplicate;
            claims[lane] = new Claim { epoch = ticket, tag = tag, captured = captured };
            if (captured >= reservedCaptured) { reservedCaptured = captured; reservedTag = tag; }
            return Decision.Continue;
        }

        public void Presented(int ticket, long captured, string tag)
        {
            if (!IsCurrent(ticket)) return;
            if (captured > presentedCaptured) presentedCaptured = captured;
            if (captured >= reservedCaptured) { reservedCaptured = captured; reservedTag = tag; }
        }

        public void End(int lane, int ticket)
        {
            // An old request must not release a new request's claim after reset.
            if (claims[lane].epoch == ticket) claims[lane] = default;
        }

        public void Reset()
        {
            epoch++;
            reservedTag = null; reservedCaptured = presentedCaptured = 0;
            for (int lane = 0; lane < claims.Length; lane++) claims[lane] = default;
        }
    }
}
