using System.Collections.Generic;
using System.Linq;
using SpatialModeling.VoiceCore.Whisper;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>Snapping Whisper's free text onto the grammar (no server needed).</summary>
    public class PhraseSnapperTests
    {
        /// <summary>VoiceSession's word grammar plus a few whole intent phrases, as the app's grammar will be.</summary>
        static PhraseSnapper AppGrammar() =>
            new PhraseSnapper(new VoiceSession().GrammarPhrases()
                .Concat(new[] { "add a cone", "add a monkey", "bevel the edges", "shade smooth", "subdivide", "level two" }));

        [Theory]
        [InlineData("Rotate it 90°.", "rotate it ninety degrees")]
        [InlineData(" Move it up 5 mm.", "move it up five millimeters")]
        [InlineData("Scale it by 1.5!", "scale it by one point five")]
        [InlineData("Scale this to 50%", "scale this to fifty percent")]
        [InlineData("Don't", "dont")]
        [InlineData("[unk] cube", "cube")]
        [InlineData("", "")]
        public void NormalizesLikeTheParser(string text, string expected) => Assert.Equal(expected, PhraseSnapper.Normalize(text));

        [Theory]
        [InlineData("At a cone.", "add a cone")]
        [InlineData("Devil the edges.", "bevel the edges")]
        [InlineData("Shade smooth.", "shade smooth")]
        public void SnapsMisheardWordsToTheClosestPhrase(string transcript, string expected)
        {
            SnapResult snap = AppGrammar().Snap(transcript);
            Assert.True(snap.Accepted, snap.ToString());
            Assert.Equal(expected, snap.Text);
            Assert.Equal(transcript == "Shade smooth.", snap.WordForWord);
        }

        [Theory]
        [InlineData("Rotate this object 90 degrees.", "rotate this object ninety degrees")]
        [InlineData("Move the cube up 10 millimeters.", "move the cube up ten millimeters")]
        [InlineData("Add a cube, please.", "add a cube please")]
        [InlineData("Subdivide, level two.", "subdivide level two")]
        public void KeepsCommandsMadeOfGrammarWords(string transcript, string expected)
        {
            SnapResult snap = AppGrammar().Snap(transcript);
            Assert.True(snap.Accepted, snap.ToString());
            Assert.Equal(expected, snap.Text);
            Assert.Equal(1f, snap.Similarity);
            Assert.True(snap.WordForWord);
        }

        [Fact]
        public void DropsWordsOutsideTheGrammarAndCountsThemAgainstTheSimilarity()
        {
            SnapResult snap = AppGrammar().Snap("Rotate this object ninety degrees, quickly.");
            Assert.Equal("rotate this object ninety degrees", snap.Text);
            Assert.True(snap.Accepted);
            Assert.True(snap.WordForWord);
            Assert.InRange(snap.Similarity, 0.7f, 0.95f);
        }

        [Theory]
        [InlineData("This is our project.")]
        [InlineData("Thank you very much everybody.")]
        [InlineData("[BLANK_AUDIO]")]
        [InlineData("")]
        public void RejectsChatter(string transcript)
        {
            var commands = new PhraseSnapper(new[] { "add a cone", "add a monkey", "bevel the edges", "shade smooth", "undo", "redo", "[unk]" });
            SnapResult snap = commands.Snap(transcript);
            Assert.False(snap.Accepted, snap.ToString());
            Assert.True(snap.Similarity < PhraseSnapper.DefaultThreshold);
        }

        [Theory]
        [InlineData("Two.", "two")]
        [InlineData("to", "two")] // the word Vosk confuses with "two" at confidence 0.5
        [InlineData("Three!", "three")]
        [InlineData("Cancel.", "cancel")]
        [InlineData("Left, left, left.", "left")]
        public void ChoiceWordsAndRepeats(string transcript, string expected)
        {
            var choices = new PhraseSnapper(new[] { "one", "two", "three", "cancel", "left", "[unk]" });
            SnapResult snap = choices.Snap(transcript);
            Assert.True(snap.Accepted, snap.ToString());
            Assert.Equal(expected, snap.Text);
        }

        [Fact]
        public void IgnoresUnkAndDuplicatePhrases()
        {
            var snapper = new PhraseSnapper(new[] { "undo", "Undo", "[unk]", "", "redo" });
            Assert.Equal(2, snapper.Count);
            Assert.False(snapper.Snap("[unk]").Accepted);
        }

        [Fact]
        public void AnEmptyGrammarAcceptsNothing()
        {
            Assert.False(new PhraseSnapper(new List<string>()).Snap("add a cube").Accepted);
            Assert.False(new PhraseSnapper(null).Snap("add a cube").Accepted);
        }

        [Fact]
        public void ThresholdIsConfigurable()
        {
            var strict = new PhraseSnapper(new[] { "add a cone" }, threshold: 0.95f);
            Assert.False(strict.Snap("At a cone.").Accepted);
            Assert.True(strict.Snap("Add a cone.").Accepted);
        }
    }
}
