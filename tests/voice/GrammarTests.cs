using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    public class GrammarTests
    {
        static readonly string[] SupportedUtterances =
        {
            "add a cube", "create a sphere", "add a cylinder",
            "select the cube", "select gear housing two",
            "move this ten centimeters along x", "move it up five millimeters", "move the cube minus one point five meters along negative y",
            "rotate this object ninety degrees", "rotate it one hundred and eighty degrees around z", "turn that forty five degrees about x",
            "scale it by two", "scale this to fifty percent", "scale it three times",
            "delete this", "remove the sphere", "undo", "redo", "cancel", "apply", "this one",
        };

        [Fact]
        public void GrammarHasEveryCommandWordObjectWordsAndUnk()
        {
            List<string> phrases = Vocabulary.GrammarPhrases(new[] { "GearHousing.002" });
            foreach (string word in new[] { "rotate", "cube", "z", "centimeters", "degrees", "ninety", "point", "minus", "this", "gear", "housing", "two" })
                Assert.Contains(word, phrases);
            Assert.Equal("[unk]", phrases.Last());
            Assert.Equal(phrases.Count, phrases.Distinct().Count());
            Assert.All(phrases.Take(phrases.Count - 1), p => Assert.Matches("^[a-z']+$", p));
        }

        [Fact]
        public void EverySupportedUtteranceUsesOnlyGrammarWords()
        {
            var grammar = new HashSet<string>(Vocabulary.GrammarPhrases(new[] { "Cube", "Sphere", "GearHousing.002" }));
            foreach (string utterance in SupportedUtterances)
                foreach (string word in Vocabulary.Words(utterance))
                    Assert.True(grammar.Contains(word), "'" + word + "' in '" + utterance + "' is not in the grammar");
        }

        [Fact]
        public void TheParserUnderstandsEveryGrammarWord()
        {
            foreach (string word in Vocabulary.GrammarPhrases(new string[0]).Where(w => w != "[unk]"))
                Assert.False(CommandParser.Parse(word, new SceneObject[0]).HasUnknownWords, word);
        }

        [Fact]
        public void SessionGrammarFollowsTheObjects()
        {
            var session = new VoiceSession();
            Assert.DoesNotContain("gear", session.GrammarPhrases());
            session.SetObjects(new[] { new SceneObject("id", "Gear") });
            Assert.Contains("gear", session.GrammarPhrases());
        }

        [Fact]
        public void VoskGrammarIsAJsonArrayOfThePhrases()
        {
            List<string> phrases = Vocabulary.GrammarPhrases(new[] { "Cube" });
            string[] parsed = JsonSerializer.Deserialize<string[]>(VoskJson.Grammar(phrases));
            Assert.Equal(phrases, parsed);
            Assert.Equal(new[] { "a \"b\" \\" }, JsonSerializer.Deserialize<string[]>(VoskJson.Grammar(new[] { "a \"b\" \\" })));
        }

        [Fact]
        public void ParsesVoskResultsWithTheLowestWordConfidence()
        {
            const string json = "{\n  \"result\" : [{\n      \"conf\" : 1.000000,\n      \"end\" : 1.02,\n      \"start\" : 0.6,\n" +
                "      \"word\" : \"rotate\"\n    }, {\n      \"conf\" : 0.734512,\n      \"end\" : 1.5,\n      \"start\" : 1.02,\n" +
                "      \"word\" : \"z\"\n    }],\n  \"text\" : \"rotate z\"\n}";
            RecognitionResult result = VoskJson.ParseResult(json);
            Assert.Equal("rotate z", result.Text);
            Assert.Equal(0.734512f, result.Confidence, 5);

            Assert.Equal("", VoskJson.ParseResult("{\n  \"text\" : \"\"\n}").Text);
            Assert.Equal(0f, VoskJson.ParseResult("{\"text\" : \"undo\"}").Confidence); // SetWords(true) missing
        }
    }

    public class ParserTests
    {
        [Theory]
        [InlineData("ninety", 90)]
        [InlineData("forty five", 45)]
        [InlineData("twelve", 12)]
        [InlineData("one hundred and eighty", 180)]
        [InlineData("one hundred eighty", 180)]
        [InlineData("one eighty", 180)]
        [InlineData("two seventy", 270)]
        [InlineData("one point five", 1.5)]
        [InlineData("zero point two five", 0.25)]
        [InlineData("point five", 0.5)]
        [InlineData("two point twenty five", 2.25)]
        [InlineData("nine hundred ninety nine point nine", 999.9)]
        [InlineData("90", 90)]
        [InlineData("1.5", 1.5)]
        public void ReadsSpokenNumbers(string text, double expected)
        {
            ParsedUtterance parsed = CommandParser.Parse("rotate " + text + " degrees", new SceneObject[0]);
            Assert.Equal(expected, parsed.Number.Value, 9);
            Assert.Equal(SpokenUnit.Degrees, parsed.Unit);
        }

        [Fact]
        public void EveryIntegerUpTo999RoundTrips()
        {
            for (int n = 0; n <= 999; n++)
            {
                List<string> words = Vocabulary.Words(NumberWords.ToWords(n));
                int i = 0;
                Assert.True(NumberWords.TryRead(words, ref i, out double value), n.ToString());
                Assert.Equal(n, value);
                Assert.Equal(words.Count, i);
            }
        }

        [Theory]
        [InlineData("Rotate Cube.001 by -90°", "rotate cube one by minus ninety degrees")]
        [InlineData("move 10cm", "move ten centimeters")]
        [InlineData("GearHousing_2", "gear housing two")]
        [InlineData("scale 50%", "scale fifty percent")]
        [InlineData("[unk] undo", "[unk] undo")]
        [InlineData("x-axis 1000", "x axis one zero zero zero")]
        public void TokenizesFreeTextAndObjectNames(string text, string words)
        {
            Assert.Equal(words, string.Join(" ", Vocabulary.Words(text)));
        }

        [Fact]
        public void FullNameBeatsBaseName()
        {
            var plain = new SceneObject("a", "Cube");
            var numbered = new SceneObject("b", "Cube.001");
            Assert.Equal("a", CommandParser.Parse("select cube", new[] { plain, numbered }).Named.Id);
            Assert.Equal("b", CommandParser.Parse("select cube one", new[] { plain, numbered }).Named.Id);
        }

        [Fact]
        public void ObjectNameNumbersAreNotAmounts()
        {
            var part = new SceneObject("p", "Part.002");
            ParsedUtterance parsed = CommandParser.Parse("move part two ten centimeters along x", new[] { part });
            Assert.Equal("p", parsed.Named.Id);
            Assert.Equal(10, parsed.Number.Value);
        }
    }
}
