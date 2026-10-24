using System;
using System.Collections.Generic;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    public class PcmConverterTests
    {
        static float[] Tone(double hz, int rate, double seconds, double amplitude = 0.5, int channels = 1)
        {
            int frames = (int)(rate * seconds);
            var samples = new float[frames * channels];
            for (int i = 0; i < frames; i++)
                for (int c = 0; c < channels; c++)
                    samples[i * channels + c] = (float)(amplitude * Math.Sin(2 * Math.PI * hz * i / rate));
            return samples;
        }

        static short[] Convert(PcmConverter converter, float[] input, int chunk = int.MaxValue)
        {
            var output = new List<short>();
            for (int at = 0; at < input.Length; at += chunk)
            {
                int n = Math.Min(chunk, input.Length - at);
                n -= n % converter.Channels;
                var part = new float[n];
                Array.Copy(input, at, part, 0, n);
                var buffer = new short[converter.MaxOutput(n)];
                int written = converter.Convert(part, n, buffer);
                Assert.InRange(written, 0, buffer.Length);
                for (int i = 0; i < written; i++)
                    output.Add(buffer[i]);
            }
            return output.ToArray();
        }

        /// <summary>Amplitude (0 to 1 of full scale) of one frequency over a whole number of cycles, by Goertzel.</summary>
        static double Amplitude(short[] pcm, int start, int length, double hz, int rate)
        {
            double w = 2 * Math.PI * hz / rate, coeff = 2 * Math.Cos(w), s1 = 0, s2 = 0;
            for (int i = start; i < start + length; i++)
            {
                double s = pcm[i] / 32767.0 + coeff * s1 - s2;
                s2 = s1;
                s1 = s;
            }
            double power = s1 * s1 + s2 * s2 - coeff * s1 * s2;
            return 2 * Math.Sqrt(Math.Max(0, power)) / length;
        }

        static double Rms(short[] pcm, int start, int length)
        {
            double sum = 0;
            for (int i = start; i < start + length; i++)
                sum += (pcm[i] / 32767.0) * (pcm[i] / 32767.0);
            return Math.Sqrt(sum / length);
        }

        static double Db(double ratio) => 20 * Math.Log10(ratio);

        [Fact]
        public void SameRateScalesRoundsAndClips()
        {
            var converter = new PcmConverter(16000, 16000);
            short[] pcm = Convert(converter, new[] { 0f, 0.5f, -0.5f, 1f, -1f, 2f, -2f, float.NaN, 1e-5f });
            Assert.Equal(new short[] { 0, 16384, -16384, 32767, -32767, 32767, -32768, 0, 0 }, pcm);
        }

        [Fact]
        public void StereoIsMixedToMono()
        {
            var converter = new PcmConverter(16000, 16000, 2);
            Assert.Equal(new short[] { 16384, 0, -32767 }, Convert(converter, new[] { 1f, 0f, 0.5f, -0.5f, -1f, -1f }));
            Assert.Throws<ArgumentOutOfRangeException>(() => converter.Convert(new float[3], 3, new short[3]));
        }

        [Theory]
        [InlineData(48000)]
        [InlineData(44100)]
        [InlineData(22050)]
        [InlineData(96000)]
        [InlineData(8000)]
        public void KeepsSpeechFrequenciesAtTheirLevel(int inputRate)
        {
            foreach (double hz in inputRate > 8000 ? new[] { 200.0, 1000, 3000, 6000 } : new[] { 200.0, 1000, 3000 })
            {
                short[] pcm = Convert(new PcmConverter(inputRate, 16000), Tone(hz, inputRate, 1.2));
                Assert.InRange(pcm.Length, 16000 * 1.2 - 64, 16000 * 1.2);
                double gain = Amplitude(pcm, 1600, 16000, hz, 16000) / 0.5;
                Assert.True(Math.Abs(Db(gain)) < 0.1, $"{hz} Hz from {inputRate} Hz: {Db(gain):0.000} dB");
            }
        }

        [Theory]
        [InlineData(48000, 8800)]
        [InlineData(48000, 10000)]
        [InlineData(48000, 15000)]
        [InlineData(48000, 23000)]
        [InlineData(44100, 9000)]
        [InlineData(44100, 20000)]
        public void RemovesWhatSixteenKilohertzCannotHold(int inputRate, double hz)
        {
            // Without the low-pass these would fold back into the speech band at full level.
            short[] pcm = Convert(new PcmConverter(inputRate, 16000), Tone(hz, inputRate, 1.2));
            double level = Rms(pcm, 1600, 16000) / (0.5 / Math.Sqrt(2));
            Assert.True(Db(level) < -70, $"{hz} Hz from {inputRate} Hz leaks at {Db(level):0.0} dB");
        }

        [Fact]
        public void OutputDoesNotDependOnChunking()
        {
            float[] input = Tone(440, 48000, 0.5);
            var random = new Random(7);
            for (int i = 0; i < input.Length; i++)
                input[i] += (float)(random.NextDouble() - 0.5) * 0.2f;
            short[] whole = Convert(new PcmConverter(48000, 16000), input);
            foreach (int chunk in new[] { 1, 7, 480, 1023, 4800 })
                Assert.Equal(whole, Convert(new PcmConverter(48000, 16000), input, chunk));
        }

        [Fact]
        public void ResetStartsOver()
        {
            var converter = new PcmConverter(48000, 16000);
            short[] first = Convert(converter, Tone(440, 48000, 0.2));
            Convert(converter, Tone(3000, 48000, 0.3));
            converter.Reset();
            Assert.Equal(first, Convert(converter, Tone(440, 48000, 0.2)));
        }

        [Fact]
        public void ImpulseStaysAtItsPlace()
        {
            var input = new float[4800];
            input[3000] = 1;
            short[] pcm = Convert(new PcmConverter(48000, 16000), input);
            int peak = 0;
            for (int i = 1; i < pcm.Length; i++)
                if (pcm[i] > pcm[peak])
                    peak = i;
            Assert.Equal(1000, peak); // no delay: output sample n is input time 3n
        }

        [Fact]
        public void RefusesASmallOutputBuffer()
        {
            var converter = new PcmConverter(48000, 16000);
            Assert.Throws<ArgumentException>(() => converter.Convert(new float[4800], 4800, new short[100]));
        }
    }
}
