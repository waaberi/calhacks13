using System;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// Turns Unity microphone samples (floats from -1 to 1 at the device's rate, channels interleaved) into the 16-bit
    /// mono PCM a recognizer takes, at its rate. It resamples with a windowed-sinc low-pass, so frequencies the lower
    /// rate can't hold are removed instead of folding back as noise. It keeps its filter history between calls, so the
    /// output doesn't depend on how the input is split into chunks; resampling delays it by about a millisecond.
    /// Not thread-safe.
    /// </summary>
    public sealed class PcmConverter
    {
        const int ZeroCrossings = 16;     // filter half-width, in zero crossings of the sinc
        const int TablePerSample = 256;   // kernel table entries per input sample
        const double Rolloff = 0.9;       // the passband ends at 90% of the lower Nyquist frequency: 7.2 kHz at 16 kHz
        const double KaiserBeta = 8.6;    // about 90 dB stopband

        readonly double step;             // input samples per output sample
        readonly double halfWidth;        // in input samples
        readonly float[] kernel;          // kernel(x) at x = k / TablePerSample, x >= 0
        float[] history;                  // the mono input still in reach of the filter
        int count;                        // valid samples in history
        double time;                      // position of the next output sample, in history indices

        public PcmConverter(int inputRate, int outputRate = 16000, int channels = 1)
        {
            if (inputRate <= 0 || outputRate <= 0)
                throw new ArgumentOutOfRangeException(inputRate <= 0 ? nameof(inputRate) : nameof(outputRate));
            if (channels <= 0)
                throw new ArgumentOutOfRangeException(nameof(channels));
            InputRate = inputRate;
            OutputRate = outputRate;
            Channels = channels;
            if (inputRate == outputRate)
                return;

            step = (double)inputRate / outputRate;
            double cutoff = 0.5 * Math.Min(1.0, (double)outputRate / inputRate) * Rolloff; // cycles per input sample
            halfWidth = ZeroCrossings / (2 * cutoff);
            kernel = new float[(int)Math.Ceiling(halfWidth * TablePerSample) + 2];
            double norm = BesselI0(KaiserBeta);
            for (int k = 0; k < kernel.Length; k++)
            {
                double x = (double)k / TablePerSample;
                double u = x / halfWidth;
                if (u >= 1)
                    break;
                double window = BesselI0(KaiserBeta * Math.Sqrt(1 - u * u)) / norm;
                double arg = 2 * cutoff * x;
                double sinc = arg == 0 ? 1 : Math.Sin(Math.PI * arg) / (Math.PI * arg);
                kernel[k] = (float)(2 * cutoff * sinc * window);
            }
            history = new float[1024];
            Reset();
        }

        public int InputRate { get; }
        public int OutputRate { get; }
        public int Channels { get; }

        /// <summary>The most samples <see cref="Convert"/> can return for this many input floats.</summary>
        public int MaxOutput(int inputCount)
        {
            int frames = inputCount / Channels;
            return InputRate == OutputRate ? frames : (int)Math.Ceiling(frames / step) + 2;
        }

        /// <summary>Forgets earlier audio, for example at the start of an utterance.</summary>
        public void Reset()
        {
            if (history == null)
                return;
            // Silence before the input, so the first output sample is centered on the first input sample.
            count = (int)Math.Ceiling(halfWidth);
            Array.Clear(history, 0, count);
            time = count;
        }

        /// <summary>
        /// Converts the first <paramref name="inputCount"/> floats of <paramref name="input"/> (whole frames of
        /// <see cref="Channels"/> interleaved samples) into <paramref name="output"/>, which must hold
        /// <see cref="MaxOutput"/> samples. Returns how many it wrote.
        /// </summary>
        public int Convert(float[] input, int inputCount, short[] output)
        {
            if (input == null || output == null)
                throw new ArgumentNullException(input == null ? nameof(input) : nameof(output));
            if (inputCount < 0 || inputCount > input.Length || inputCount % Channels != 0)
                throw new ArgumentOutOfRangeException(nameof(inputCount));
            if (output.Length < MaxOutput(inputCount))
                throw new ArgumentException("Output buffer too small", nameof(output));

            int frames = inputCount / Channels;
            if (InputRate == OutputRate)
            {
                for (int i = 0; i < frames; i++)
                    output[i] = ToPcm(Mono(input, i));
                return frames;
            }

            if (count + frames > history.Length)
                Array.Resize(ref history, Math.Max(history.Length * 2, count + frames));
            for (int i = 0; i < frames; i++)
                history[count + i] = Mono(input, i);
            count += frames;

            int written = 0;
            while (time + halfWidth < count - 1)
            {
                output[written++] = ToPcm(Sample(time));
                time += step;
            }

            // Drop history the next output sample no longer reaches.
            int keepFrom = Math.Max(0, (int)Math.Floor(time - halfWidth) - 1);
            if (keepFrom > 0)
            {
                Array.Copy(history, keepFrom, history, 0, count - keepFrom);
                count -= keepFrom;
                time -= keepFrom;
            }
            return written;
        }

        /// <summary>The band-limited signal at a fractional history position.</summary>
        float Sample(double t)
        {
            int first = (int)Math.Ceiling(t - halfWidth), last = (int)Math.Floor(t + halfWidth);
            double sum = 0;
            for (int i = first; i <= last; i++)
            {
                double x = Math.Abs(t - i) * TablePerSample;
                int k = (int)x;
                double frac = x - k;
                sum += history[i] * (kernel[k] + (kernel[k + 1] - kernel[k]) * frac);
            }
            return (float)sum;
        }

        float Mono(float[] input, int frame)
        {
            if (Channels == 1)
                return input[frame];
            float sum = 0;
            for (int c = 0; c < Channels; c++)
                sum += input[frame * Channels + c];
            return sum / Channels;
        }

        static short ToPcm(float sample)
        {
            if (float.IsNaN(sample))
                return 0;
            double scaled = Math.Round(sample * 32767.0, MidpointRounding.AwayFromZero);
            return (short)Math.Max(short.MinValue, Math.Min(short.MaxValue, scaled));
        }

        static double BesselI0(double x)
        {
            double sum = 1, term = 1;
            for (int k = 1; k < 50; k++)
            {
                term *= x / (2 * k) * (x / (2 * k));
                sum += term;
                if (term < sum * 1e-12)
                    break;
            }
            return sum;
        }
    }
}
