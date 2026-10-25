# Voice

VoiceCore turns speech into the contract's commands, asks for whatever is missing, and says it out loud. It is a
Unity package (`com.calhacks13.voicecore`, loaded from `voice/VoiceCore`) of plain C# that is built and tested on Linux.
Owner: Waaberi. The Unity side, `VoiceUiAdapter.cs` in `app/`, is Jihyeon's.

| Path | What it is |
| --- | --- |
| `VoiceCore/Runtime/` | Assembly `SpatialModeling.VoiceCore`, no Unity or Vosk references: `VoiceSession` (conversation memory), `HostCommand` (mapping to the contract), `VoiceInput` (recognizer on a worker thread), `PcmConverter`, `Prompt`. |
| `VoiceCore/Vosk/` | Assembly `SpatialModeling.VoiceCore.Vosk`: `VoskSpeechRecognizer` on libvosk's C API. It compiles without the native library. |
| `VoiceCore/Prompts/Resources/VoiceCorePrompts/` | One clip per `Prompt`, made by `make-prompts.py`. |
| `VoiceCore/Plugins/` | Vosk's native libraries, from `fetch-vosk.sh`. Not in Git. |
| `fetch-model.sh`, `fetch-vosk.sh` | Download the pinned model and native libraries, with SHA-256 checks. |
| `VoskSpike/` | Measures real recognition on audio files through the same path as the app. |

## Setup on every machine

From the repository root (Git Bash on Windows):

```sh
voice/fetch-vosk.sh                                # native libraries into voice/VoiceCore/Plugins/
voice/fetch-model.sh app/Assets/StreamingAssets    # model for the app (also in the Windows build)
voice/fetch-model.sh                               # model for the tests and the spike, in voice/models/
dotnet test tests/voice
```

Run `fetch-vosk.sh` before opening Unity. Without it everything still compiles, and `VoiceInput.Error` reports the
missing library at run time.

## Driving VoiceSession from VoiceUiAdapter

Call everything from the main thread. Every call returns a `VoiceTurn`: play and show its `Prompts` in order, and send
its `Command` if there is one.

- **Audio:** `VoiceInput` loads Vosk and decodes on its own thread. Pass it the microphone's floats as they are, at the
  device rate; it converts them to 16 kHz PCM. Push-to-talk calls `StartUtterance` and `StopUtterance`. Results come
  out of `TryGetResult` and go into `session.Hear`. Call `session.Tick()` every frame for the timeout and the pointer dwell.
- **Scene:** after every snapshot or update, pass the objects the app shows to `SetObjects`: `visible` true and a `mesh`,
  so not the camera. Use the contract's object `id`, and pass objects others have leased too (the host answers
  `lease_conflict`, which becomes a prompt). When names change, pass `GrammarPhrases()` to `input.SetGrammar`.
- **Targets:** call `SetSelection` with the selected IDs whenever the selection changes, and `SetPointerTarget` with the
  ID under the ray, or null. "This" means the selection first, then the pointer, then the only object. When several
  objects or an ineligible object are selected, it asks.
- **State:** on Wrong document call `DocumentChanged()`, on Disconnected `ConnectionLost()`, and on your Cancel button `Cancel()`.
  Show `session.Pending`: `Command` (its `ToString()` and `TargetName`), the `Missing` fields and `ExpiresAt`.
- **Prompts:** show `prompt.Text` and play `Resources.Load<AudioClip>(prompt.ClipResource)`. While a clip plays, set
  `input.Paused = true`, and clear it about 0.3 s after the clip ends, because Air Link plays audio late. No result then
  contains a prompt. (`session.SetPromptPlaying` is only for a recognizer that listens by itself, such as Windows speech.) Put details such as an owner's name or the host's message next to the text; the clip stays the same.
- **Sending:** `HostCommand.From(command)` gives `Op`, `TargetId` and `Args`. It returns null for Select (select it in the
  UI), Apply and Cancel (your draft's buttons). Ask for the controller confirmation before a Delete
  (`RequiresConfirmation`, prompt `ConfirmDelete`). For "add", pass the location where the pointer meets the table, in
  Blender coordinates. Add the request fields from `welcome`, `base_revision`, `source` `HostCommand.Source` and the
  target's current `generation`. When the app can't send, play `Prompt.NotConnected`.
- **Answers:** for the `result` (or an `error` whose `re` is the command), play
  `HostCommand.PromptFor(op, outcome, errorCode)`, and show the receipt's `summary` or the error's `message`.

```csharp
using SpatialModeling.VoiceCore;
using SpatialModeling.VoiceCore.Vosk;

VoiceSession session = new VoiceSession();
VoiceInput input;
AudioClip mic;
float[] chunk;
int read;

void Start()
{
    string model = Path.Combine(Application.streamingAssetsPath, VoskSpeechRecognizer.ModelName);
    input = new VoiceInput(() => VoskSpeechRecognizer.Load(model));      // input.Error says why if it fails
    Microphone.GetDeviceCaps(null, out int min, out int max);
    int rate = min == 0 && max == 0 ? 16000 : Mathf.Clamp(16000, min, max);
    mic = Microphone.Start(null, true, 1, rate);                         // a 1 s ring buffer
    chunk = new float[mic.frequency / 50 * mic.channels];               // 20 ms; 50 of them fill the ring exactly
}

void Update()
{
    int position = Microphone.GetPosition(null) * mic.channels;
    int ring = mic.samples * mic.channels;
    while ((position - read + ring) % ring >= chunk.Length)
    {
        mic.GetData(chunk, read / mic.channels);
        input.Write(chunk, chunk.Length, mic.frequency, mic.channels);
        read = (read + chunk.Length) % ring;
    }
    while (input.TryGetResult(out RecognitionResult result))
        Handle(session.Hear(result));
    Handle(session.Tick());
}

void OnTalkPressed() => input.StartUtterance();
void OnTalkReleased() => input.StopUtterance();
void OnScene(IEnumerable<SceneObject> shown) { Handle(session.SetObjects(shown)); input.SetGrammar(session.GrammarPhrases()); }
void OnSelection(IEnumerable<string> ids) => Handle(session.SetSelection(ids));
void OnPointer(string id) => Handle(session.SetPointerTarget(id));
void OnDestroy() { Microphone.End(null); input.Dispose(); }

void Handle(VoiceTurn turn)
{
    foreach (Prompt prompt in turn.Prompts)
        QueuePrompt(prompt.Text, Resources.Load<AudioClip>(prompt.ClipResource));   // input.Paused while it plays
    if (turn.Command == null)
        return;
    HostCommand command = HostCommand.From(turn.Command, addLocation: PointerOnTableInBlender());
    if (command == null) { HandleLocally(turn.Command); return; }    // Select, Apply, Cancel
    var payload = RequestFields();                                   // from welcome, plus base_revision
    payload["source"] = HostCommand.Source;
    payload["op"] = command.Op;
    if (command.TargetId != null)
        payload["target"] = new JObject { ["id"] = command.TargetId, ["generation"] = GenerationOf(command.TargetId) };
    payload["args"] = JObject.FromObject(command.Args);
    SendCommand(payload, turn.Command.RequiresConfirmation);         // Delete waits for the controller confirmation
}
```

## Windows checks (Lee, #93)

1. Install Git for Windows, the .NET 10 SDK and Unity 6000.6.5f1 with Windows Build Support. Clone into a path with
   only ASCII characters, such as `C:\calhacks13`: on Windows, Vosk opens the model through the ANSI code page.
2. In Git Bash at the repository root, run the four commands from [Setup](#setup-on-every-machine). `dotnet test
   tests/voice` must pass with nothing skipped. That loads `libvosk.dll` and its MinGW runtime on Windows for the first time.
3. Record your own voice: run `voice/VoskSpike/make-samples.sh` once on Linux, or copy its list of 17 commands and 3
   chatter lines. For each line, save `NAME.wav` (mono 16-bit, any rate; 48 kHz is fine) with the Quest microphone over
   Air Link, plus `NAME.txt` holding the exact words (`-` for chatter). Then run
   `dotnet run --project voice/VoskSpike -- voice/models/vosk-model-small-en-us-0.15 DIR`, and post the output to #93
   with the room noise level. It shows transcripts, wrong-command counts by confidence threshold and the plan's dialogue.
4. Open `app/` in Unity. The Console must show no errors, and the Inspector of
   `Packages/VoiceCore/Plugins/Windows/libvosk.dll` shows Editor (Windows, x86_64) and Standalone (Win64).
5. Once `VoiceUiAdapter` exists: in Play mode, say "rotate this object ninety degrees", select an object, say "z", and
   check that the prompts are audible and don't trigger a command themselves (P4-M1-3). Then make a Windows build and
   check that `<App>_Data/Plugins/x86_64/` holds `libvosk.dll`, `libstdc++-6.dll`, `libgcc_s_seh-1.dll` and
   `libwinpthread-1.dll`, and `<App>_Data/StreamingAssets/` holds `vosk-model-small-en-us-0.15`. Repeat the dialogue in the build.

Still untested on Windows: loading libvosk and its MinGW DLLs in the Unity editor and player, the Quest microphone's
rate and level through Air Link, prompt playback and echo in the headset, model paths with non-ASCII characters, and
accuracy and the confidence threshold with real voices.

## Prompt audio

`uv run voice/make-prompts.py` speaks every `Prompt` offline with [Piper](https://github.com/OHF-Voice/piper1-gpl) 1.3.0
and the `en_US-ljspeech-high` voice. The voice is MIT-licensed and trained on the public-domain
[LJ Speech](https://keithito.com/LJ-Speech-Dataset/) dataset, so the clips can ship with the app; it is pinned by
revision and SHA-256. The script writes Ogg Vorbis files (mono, 22.05 kHz; 32 clips, 81 s, 0.7 MB) with stable
`.meta` GUIDs, and puts each clip's text in its `COMMENT` tag. After changing a prompt's text, run it for that ID
(`uv run voice/make-prompts.py ask_axis`); the tests fail until then. `--say OUT.ogg "text"` makes test audio.

## Vosk binaries

`fetch-vosk.sh` takes the native libraries from the Vosk 0.3.38 NuGet package (24 MB download, checked by SHA-256), the
same build the Linux tests and the spike load. That's 85 MB unpacked: `libvosk.dll` with its MinGW runtime for Windows
x64, a universal `libvosk.dylib` (x86_64 and arm64) for the Mac editor, and `libvosk.so` for Linux. They are kept out of
Git like the model: this repository has no LFS, and Unity only needs them on disk. The script also writes their
`.meta` import settings, so each library loads only in its own editor and player. There is no managed `Vosk.dll`:
`VoskSpeechRecognizer` calls the C API itself, so the package compiles before the download. Licenses: Vosk (with Kaldi
inside) is Apache 2.0; libstdc++ and libgcc are GPLv3 with the GCC Runtime Library Exception, and winpthreads is
MIT-style; all of them may be
redistributed with the build. The model is Apache 2.0 too.

## Measured on Linux

Through `VoiceInput`, `PcmConverter` (48 kHz → 16 kHz) and libvosk 0.3.38 with the grammar, on 100 TTS samples
(`make-samples.sh`: 17 commands and 3 chatter lines in each of espeak-ng en-us and en-gb, flite slt and rms, and Piper):

| | Result |
| --- | --- |
| Exact transcripts (grammar / free dictation) | 48 / 85, 14 / 85 |
| At `MinConfidence` 0.5: intended / wrong / no command | 54 / 0 / 46 of 100 |
| Chatter that became a command | 0 of 15 |
| Decoding speed, including resampling | 0.025 × real time |

The misses are mostly dropped filler words ("scale by one point five" still scales) or mangled robotic espeak verbs,
which give no command. A synthetic one-word "z" is too short for Vosk; "the z axis" works. The plan's whole dialogue runs
from speech for both flite voices, and for Piper with "the z axis" (`tests/voice/VoskTests.cs`). It also runs in the Unity
6000.6.7f1 editor on Linux and in a Linux Mono player build (model from StreamingAssets, clips from Resources, only
`libvosk.so` in the build's `Plugins/`), and the ask_axis clip fed into a paused `VoiceInput` is never recognized
(unpaused, Vosk hears "axis x y on z"). TTS is cleaner than a headset microphone, so treat this as an upper bound until
the Windows recordings.
