using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>The prerecorded prompt clips from voice/make-prompts.py.</summary>
    public class PromptClipTests
    {
        static readonly string Clips = Path.Combine(Contract.Root, "voice", "VoiceCore", "Prompts", "Resources", "VoiceCorePrompts");

        /// <summary>What a clip's Ogg Vorbis headers say.</summary>
        sealed class Clip
        {
            public int Channels, Rate;
            public double Seconds;
            public readonly Dictionary<string, string> Tags = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }

        static Clip Read(string path)
        {
            byte[] data = File.ReadAllBytes(path);
            var packets = new List<byte[]>();
            var packet = new List<byte>();
            long granule = 0;
            int at = 0;
            while (at < data.Length)
            {
                Assert.Equal("OggS", Encoding.ASCII.GetString(data, at, 4));
                granule = BitConverter.ToInt64(data, at + 6);
                int segments = data[at + 26];
                int body = at + 27 + segments;
                for (int s = 0; s < segments; s++)
                {
                    int size = data[at + 27 + s];
                    packet.AddRange(new ArraySegment<byte>(data, body, size));
                    body += size;
                    if (size < 255)
                    {
                        packets.Add(packet.ToArray());
                        packet.Clear();
                    }
                }
                at = body;
            }

            byte[] id = packets[0], comments = packets[1];
            Assert.Equal("\u0001vorbis", Encoding.ASCII.GetString(id, 0, 7));
            Assert.Equal("\u0003vorbis", Encoding.ASCII.GetString(comments, 0, 7));
            var clip = new Clip { Channels = id[11], Rate = BitConverter.ToInt32(id, 12) };
            clip.Seconds = (double)granule / clip.Rate;
            int pos = 7;
            pos += 4 + BitConverter.ToInt32(comments, pos); // vendor
            int count = BitConverter.ToInt32(comments, pos);
            pos += 4;
            for (int i = 0; i < count; i++)
            {
                int length = BitConverter.ToInt32(comments, pos);
                string tag = Encoding.UTF8.GetString(comments, pos + 4, length);
                pos += 4 + length;
                int eq = tag.IndexOf('=');
                clip.Tags[tag.Substring(0, eq)] = tag.Substring(eq + 1);
            }
            return clip;
        }

        [Fact]
        public void EveryPromptHasAMonoClipOfItsText()
        {
            foreach (Prompt prompt in Prompt.All)
            {
                string path = Path.Combine(Clips, prompt.Id + ".ogg");
                Assert.True(File.Exists(path), "No clip for " + prompt.Id + ": run uv run voice/make-prompts.py " + prompt.Id);
                Clip clip = Read(path);
                Assert.True(clip.Tags.TryGetValue("COMMENT", out string spoken) && spoken == prompt.Text,
                    prompt.Id + ".ogg says \"" + spoken + "\", not \"" + prompt.Text + "\": run uv run voice/make-prompts.py " + prompt.Id);
                Assert.Equal(1, clip.Channels);
                Assert.Equal(22050, clip.Rate);
                Assert.InRange(clip.Seconds, 0.2, 0.1 * prompt.Text.Length + 1);
                Assert.Equal("VoiceCorePrompts/" + prompt.Id, prompt.ClipResource);
            }
        }

        [Fact]
        public void EveryClipBelongsToAPromptAndHasItsOwnMeta()
        {
            var ids = new HashSet<string>(Prompt.All.Select(p => p.Id));
            var guids = new HashSet<string>();
            string[] clips = Directory.GetFiles(Clips, "*.ogg");
            Assert.Equal(ids.Count, clips.Length);
            foreach (string clip in clips)
            {
                Assert.Contains(Path.GetFileNameWithoutExtension(clip), ids);
                string meta = File.ReadAllText(clip + ".meta");
                Assert.Contains("AudioImporter:", meta);
                Assert.True(guids.Add(meta.Split('\n')[1]), "Repeated GUID in " + clip + ".meta");
            }
            Assert.Equal(new[] { ".meta", ".ogg" }, Directory.GetFiles(Clips).Select(Path.GetExtension).Distinct().OrderBy(e => e));
        }

        [Fact]
        public void ClipsAreSmall()
        {
            long bytes = Directory.GetFiles(Clips, "*.ogg").Sum(f => new FileInfo(f).Length);
            Assert.InRange(bytes, 1, 1024 * 1024);
        }
    }
}
