# Voice

VoiceCore turns speech into the contract's commands, asks for whatever is missing, and says it out loud. It is a
Unity package (`com.calhacks13.voicecore`, loaded from `voice/VoiceCore`) of plain C# that is built and tested on Linux.
Owner: Waaberi. The Unity side, `VoiceUiAdapter.cs` in `app/`, is Jihyeon's.

| Path | What it is |
| --- | --- |
| `VoiceCore/Runtime/` | Assembly `SpatialModeling.VoiceCore`, no Unity or Vosk references: `VoiceSession` (conversation memory), `HostCommand` (mapping to the contract), `HostVoice.cs` (the host resolver's messages), `VoiceInput` (recognizer on a worker thread), `PcmConverter`, `Prompt`. |
| `VoiceCore/Vosk/` | Assembly `SpatialModeling.VoiceCore.Vosk`: `VoskSpeechRecognizer` on libvosk's C API. It compiles without the native library. |
| `VoiceCore/Whisper/` | Assembly `SpatialModeling.VoiceCore.Whisper`, no Unity references: `VoiceRecognizers.Create` (the app's recognizer), `FastPathRecognizer` (Vosk first, Whisper when Vosk isn't sure), `WhisperServerRecognizer` and `WhisperServer` (a local whisper.cpp server the app starts and stops), `PhraseSnapper`. See [Choosing the recognizer](#choosing-the-recognizer). |
| `VoiceCore/Prompts/Resources/VoiceCorePrompts/` | One clip per `Prompt`, made by `make-prompts.py`. |
| `VoiceCore/Plugins/` | Vosk's native libraries, from `fetch-vosk.sh`. Not in Git. |
| `fetch-model.sh`, `fetch-vosk.sh` | Download the pinned model and native libraries, with SHA-256 checks. |
| `fetch-whisper.sh` | Downloads the pinned whisper-server for Windows and the tiny.en and base.en models, with SHA-256 checks. |
| `VoskSpike/` | Measures real recognition on audio files through the same path as the app. |

## Setup on every machine

From the repository root (Git Bash on Windows):

```sh
voice/fetch-vosk.sh                                # native libraries into voice/VoiceCore/Plugins/
voice/fetch-model.sh app/Assets/StreamingAssets    # model for the app (also in the Windows build)
voice/fetch-model.sh                               # model for the tests and the spike, in voice/models/
voice/fetch-whisper.sh app/Assets/StreamingAssets  # whisper-server.exe and its models for the app (Windows)
dotnet test tests/voice
```

`fetch-whisper.sh` puts about 240 MB into `StreamingAssets/whisper/`, which is never committed. The Windows PC that
runs the app needs the [Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)
for whisper-server.exe; most PCs with games or Unity already have it. Without the download the app runs as before, on
Vosk alone.

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
- **Push-to-talk audio:** `new VoiceInput(create, 16000, VoiceInput.RecommendedPrerollMs, VoiceInput.RecommendedPostrollMs)`
  keeps 300 ms from before the press and 150 ms after the release. It needs `Write` every frame, also while the button
  is up (see [Push-to-talk pre-roll](#push-to-talk-pre-roll)).

### The host's resolver (P4)

With `new VoiceSessionOptions { AskHost = true }`, words VoiceCore can't turn into a command by itself go to the host,
which knows about 40 Blender operations ("add a monkey", "shade smooth", "subdivide, level two") and answers run, ask or
reject (contracts/README.md, Voice). Without `AskHost` nothing changes.

- **Grammar:** after `welcome`, send `voice.grammar_query` (`VoiceGrammar.QueryType`, payload `{}`). Pass the answer
  to `session.SetHostGrammar(VoiceGrammar.FromJson(payloadJson))` and then `input.SetGrammar(session.GrammarPhrases())`.
  An `error` `unknown_type` for the query means a host without voice: call `session.HostHasNoVoice()`.
- **Resolve:** when a turn has `Resolve`, send a `voice.resolve` (`VoiceResolve.Type`) with payload
  `turn.Resolve.Payload(generationOfTheTarget)`, then call `session.ResolveSent(turn.Resolve, messageId)` with the ID it
  went out with, or null if it couldn't be sent. Show "thinking" while `session.WaitingForHost`.
- **Candidates:** pass a `voice.candidates` to `session.HostAnswered(re, VoiceCandidates.FromJson(payloadJson))`, and an
  `error` whose `re` is the resolve to `session.HostError(re, code)`. Late answers are dropped by `re`; after
  `HostTimeout` (3 s) the words are handled as without a host. Show `turn.HostReason` ("Join isn't available by
  voice.") next to the turn's prompts.
- **Run:** a `Command` of kind `Run` goes out like the others: `HostCommand.From` gives op `voice.run` with args
  `resolution` and `choice`, and a target only when the candidate needs one. Its `result` gets
  `HostCommand.PromptFor("voice.run", ...)`; show the receipt's summary.
- **Ask:** the turn says `ask_choice`. Show `session.Choice.Candidates` numbered ("1. Subdivision Surface, level 2"),
  with buttons that call `session.Choose(n)` and a Cancel button (`session.Cancel()`).
- **Grammar changes:** when a turn has `GrammarChanged` (a question began or ended), call
  `input.SetGrammar(session.GrammarPhrases())`. While asking, the grammar is only the answers and "[unk]".
- **A new command while asking:** words that aren't an answer and aren't only answer words, "[unk]" and fillers
  ("make it thicker", "rotate this ninety degrees around z", "undo") drop the question and are handled as a new
  command in the same turn, routed to the host as usual. The turn has `ChoiceDismissed` (hide the choice panel) and
  `GrammarChanged`. Garbled answers ("[unk] two", "two please", "to") still ask again. `GrammarPhrases()` stays
  answers-only: with the host's phrases merged in, Vosk's TTS answers fell from 20/20 to 14/20 at 0.9 ("two" heard as
  "do"). With `FastPathRecognizer` (the default) the command still arrives: Vosk keeps the answers-only grammar, but
  Whisper's transcript is snapped onto the answers plus the last full grammar it was given, so "make it thicker"
  reaches `Hear` as "make it thicker" and runs (or goes to the host). The adapter calls `SetGrammar` as always; the
  fast path tells a question's grammar from the full one itself. With Vosk alone, a command said while asking reaches
  the session as a press without a result (next item), which dismisses the question, and saying it again gets the
  full grammar.
- **A press without a result:** `VoiceInput.TryGetNoResult(out NoResultReason reason)` reports each push-to-talk
  utterance that ended without any result. Drain it after `TryGetResult` and pass it to
  `session.NothingRecognized(reason)`. The turn's `NoResult` is set: show a short "Didn't catch that". `Silence`
  (an accidental tap, and the default for recognizers that don't say) has no prompt, so it never speaks and keeps any
  question. `NotUnderstood` (speech that matched no phrase) says `low_confidence` and dismisses an open question. A
  recognizer says which by implementing `IReportsNoResult` (raise `NoResult` from `Stop`, only when it raises no
  result). `WhisperServerRecognizer` and `FastPathRecognizer` do: a transcript that snapped onto nothing is
  `NotUnderstood`; a silent press and silence hallucinations such as "you" are `Silence`. Vosk alone doesn't say,
  so every press without a result is `Silence`. Empty words given to `Hear` are a `Silence` turn too.
- **A delete waiting for its confirmation:** the newest request wins. When a turn has `CancelsDelete` (a command other
  than Cancel, or a new question: a missing field or the host's "which one?"), drop the waiting delete and say
  `replaced_pending` before the turn's own prompts. A delete and a question are then never shown at once, and the
  trigger never confirms a delete the panel no longer shows. Words still waiting for the host don't cancel it; the
  host's run or question does.

Which words go to the host (`VoiceSession.Hear`), in order:

1. While the host's question is pending, only an exact answer counts: "one", "first", "the first one", "option one",
   "number one" (and two, three), "cancel" or "never mind", at confidence 0.9 or more, never with "[unk]". Garbled
   answers (only answer words, "[unk]" and fillers) ask again; other words dismiss the question and go on below as a
   new command.
2. Two different command verbs are a mishearing (#142), and "[unk]" alone is nothing: neither goes to the host.
3. Undo, redo and cancel never go to the host.
4. To the host: no command verb ("shade smooth", "a monkey" when "add" was lost), words VoiceCore doesn't know after
   the verb ("add a monkey", "select all"), or "apply" with more words ("apply the scale"). Below `MinConfidence`
   they still go, marked low confidence, and the host may only ask: Vosk gives "two" about 0.5. Words with one of
   VoiceCore's shapes but no verb ("selected cylinder" for "select the cylinder", "on cube" for "add a cube") also only
   ask: on TTS the host otherwise ran "add a cylinder" for "select the cylinder" 3 times out of 15.
5. Everything else stays on VoiceCore's path, as before. While a command waits for a field, answers keep priority:
   only words without a verb that can't fill it go to the host, and none while it waits for its object (unknown words
   are then a name, as before). The pending command is dropped only when the host runs or asks.

Whenever the host can't help (reject, `unknown_type`, a send failure or the timeout), the words get exactly the turn
they would get without a host.

```csharp
using SpatialModeling.VoiceCore;
using SpatialModeling.VoiceCore.Whisper;

VoiceSession session = new VoiceSession();
VoiceInput input;
AudioClip mic;
float[] chunk;
int read;

void Start()
{
    var recognizer = VoiceRecognizerSettings.ForStreamingAssets(Application.streamingAssetsPath, Debug.Log);
    input = new VoiceInput(() => VoiceRecognizers.Create(recognizer));  // input.Error says why if it fails
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
    while (input.TryGetNoResult(out NoResultReason why))                // after the results: "Didn't catch that"
        Handle(session.NothingRecognized(why));
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

## Choosing the recognizer

The app makes its recognizer with `VoiceRecognizers.Create(settings)` inside VoiceInput's factory, so it runs on
VoiceInput's worker thread and never stalls a frame. `VoiceRecognizerSettings.ForStreamingAssets(path, log)` fills in
the paths of `fetch-model.sh` and `fetch-whisper.sh`; `log` (for example `Debug.Log`) says which recognizer runs and why.

| `Kind` | What it does |
| --- | --- |
| `FastPath` (default) | Vosk in grammar mode answers when it heard exactly one grammar phrase at confidence 0.9 or more (about 7 ms after release). Otherwise whisper tiny.en decodes the utterance (about 0.45 s on 4 CPU threads) and its transcript is snapped onto the grammar. If whisper-server can't start (no download, no VC++ runtime), it logs why and runs Vosk alone. |
| `Vosk` | Vosk alone, VoiceCore's behaviour before Whisper. Use it for an open microphone: the fast path answers on release only. |
| `Whisper` | Whisper for every utterance. For measurements. |

**What Whisper's text turns into.** Whisper is trained on real speech, so it hears real voices better than Vosk's small
model, but it writes free text ("At a cone.", "Rotate it 90°."). `PhraseSnapper` maps it onto the grammar with the
parser's tokenizer: either the closest single phrase by character similarity, or a split into consecutive grammar
phrases the way Vosk chains them, whichever is closer. Repeated words ("left, left, left") count once. Then:

- word for word (at most some words left out, or a word the grammar doesn't know turned into the grammar's form of it:
  "add a mirror, modify," gives "add a mirror modifier"): the result's confidence is the similarity, 1 when nothing
  was dropped;
- words replaced ("devil" became "bevel"): a guess, confidence at most 0.49, just under `MinConfidence`. Today that gives
  the LowConfidence prompt; once results below `MinConfidence` reach the host, the host may only ask about it;
- a word the grammar knows is never turned into another form of it: "make it smooth." can't become "make it smoother"
  (with "make it smooth" in the host grammar, #147, it is exact);
- similarity under 0.65: speech that is no command. No result is raised; `NoResult` (`IReportsNoResult`) says
  `NotUnderstood`, so `VoiceInput.TryGetNoResult` reports it and `session.NothingRecognized` says "Sorry, I didn't
  catch that" (see [A press without a result](#the-hosts-resolver-p4)).

**No speech says nothing.** Before Whisper is asked, a speech gate needs three 30 ms frames at RMS 100 (-50 dBFS) or
more (`WhisperServerRecognizer.DefaultMinSpeechRms`; the quietest of 1,100 real Speech Commands clips reached 293, the
silent press of the Unity run 0). Whisper's silence hallucinations ("you", "thank you", "thanks for watching", "bye",
"[BLANK_AUDIO]", "(music)", a lone "um") are dropped too; in `FastPath` only when Vosk heard nothing, so a "you" that
Vosk also heard goes out. Both raise no result and `NoResult` `Silence`, so an accidental press of push-to-talk never
speaks (the UI may show "Didn't catch that"); `FastPathRecognizer.LastOutcome` is `Silence`. A decode that failed
(server down, timeout) raises no reason: Vosk's results go out instead, and if Vosk heard nothing VoiceInput counts it
as `Silence`.

Measured on whisper tiny.en's transcripts (290 TTS clips, 48 chatter clips, the 16 of the Unity run) against the host
grammar the Unity run used: the TTS commands that run and the chatter accepted are unchanged (chatter 18 of 68
accepted, 6 above 0.5, as before); 8 commands that were guesses now run word for word ("make it symmetric", "add a
screw modifier", "add a subdivision surface modifier level two"). With #147's new phrases every cue-card transcript
of the Unity run snaps right: "make it smooth", "smooth the object", "add a mirror modifier" (0.90, runs), "subdivide
it twice", "subdivide level two". Tried and left out: letting every grammar word stand alone in the phrase sequence;
it kept "make it smooth" too, but three more chatter clips would have run ("wait on a second").

The prompt is the Blender vocabulary prompt plus the grammar's other words (object names, choice words), up to 600
characters.

**whisper-server.** `WhisperServer` starts `StreamingAssets/whisper/whisper-server.exe -m ggml-tiny.en.bin --host
127.0.0.1 --port 8178 -t 4 -l en -nt -ng` (CPU only; without `-ng` for the CUDA build, see below) without a console window, while Vosk loads
its model. It waits for `/health`, warms the model up with half a second of silence (about 0.5 s in total for tiny.en,
1 s for base.en) and is killed when VoiceInput is disposed. It runs at below-normal priority, so a decode never delays
a VR frame. On Windows it first checks for the VC++ runtime DLLs: without them Windows would show a "DLL was not found"
dialog on the desktop and the server would hang until someone closed it, so voice falls back to Vosk at once and the
log says what to install. Voice input isn't ready until the server is (at most `WhisperStartTimeoutMs`, 15 s; then
Vosk alone). A server already answering on the port, for example one left over from a crash, is reused. If the server
dies or goes away, it is started again at the next utterance, once: if that fails, Vosk answers alone from then on. An
utterance whose request fails or takes longer than 4 s gets Vosk's result instead. It listens on 127.0.0.1 only, so
Windows asks no firewall question. Settings: `WhisperModel` (`ggml-tiny.en.bin`, or `ggml-base.en.bin`),
`WhisperPort`, `WhisperThreads`, `WhisperTimeoutMs`, `WhisperStartTimeoutMs`, `PromptWithGrammar`,
`WhisperGuessConfidence` (1 lets guesses run), `SnapThreshold`, `MinFastConfidence`, `WhisperUseGpu`.

**GPU or CPU.** On a Windows PC with an NVIDIA GPU, prefer the CUDA 12.4 build of the same release:
`voice/fetch-whisper.sh --cuda app/Assets/StreamingAssets` (685 MB zip, SHA-256 pinned; about 1.2 GB unpacked with
cuBLAS; needs an NVIDIA driver for CUDA 12.4 or later). With `ggml-cuda.dll` in the folder, `WhisperUseGpu` (null:
auto) drops `-ng` and the GPU decodes; a Linux GPU build took 18-22 ms for tiny.en on an idle RTX 5070 Ti, against
about 460 ms on the CPU. The Windows CUDA build and a GPU busy rendering VR are unmeasured: set `WhisperUseGpu = false`
if frames drop. Without an NVIDIA GPU use the default CPU build with tiny.en. Running the script again with or without
`--cuda` swaps the build.

**In the Unity adapter** the change is one line, plus `using SpatialModeling.VoiceCore.Whisper;`:

```csharp
// before: input = new VoiceInput(() => VoskSpeechRecognizer.Load(model));
input = new VoiceInput(() => VoiceRecognizers.Create(
    VoiceRecognizerSettings.ForStreamingAssets(Application.streamingAssetsPath, m => Debug.Log("[Voice] " + m))));
```

**Tests on Linux or macOS.** The unit tests need nothing. `WhisperIntegrationTests` run a real whisper-server and are
skipped without one (CI has none). There is no prebuilt server for Linux or macOS; build whisper.cpp v1.9.5:

```sh
git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp /tmp/whisper.cpp
cmake -S /tmp/whisper.cpp -B /tmp/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF
cmake --build /tmp/whisper.cpp/build --target whisper-server -j
voice/fetch-whisper.sh --models-only                         # models into voice/models/whisper/
cp /tmp/whisper.cpp/build/bin/whisper-server voice/models/whisper/
dotnet test tests/voice
```

`WHISPER_SERVER` (the executable) and `WHISPER_MODELS` (the folder with the models) point the tests elsewhere.

### Measured (Linux, Ryzen AI 9 HX 370, CPU, 4 threads)

Through the repo's `VoiceInput` and `VoiceRecognizers.Create`, with the grammar the app will use after the host's phrase
list lands (VoiceSession's words plus the 428 phrases of `match_v2.grammar_phrases('demo')`), scored through the
voice-matching study's emulation of VoiceCore's routing and the host resolver, where results under confidence 0.5 may
only be asked about. Latencies were taken at a load average of 3 to 6 on 24 threads.

| | Vosk alone | Fast path, tiny.en |
| --- | --- | --- |
| Real speech: 1,008 Speech Commands clips, 220 speakers, 35-word grammar (right / wrong)¹ | 961 / 30 | 962 / 21 (base.en: 964 / 16) |
| TTS corpus (5 voices): 270 commands and choice words, top-1 / wrong runs / run or asked right | 244 / 0 / 87% | 247 / 1 / 88% |
| the same corpus: 20 chatter clips that ran / were asked about | 1 / 3 | 0 / 0 |
| realvoice kit², 108 commands per condition, top-1 / wrong runs / run or asked right: clean | 96 / 0 / 86% | 91 / 1 / 81% |
| first 200 ms cut off | 54 / 2 / 39% | 62 / 3 / 56% |
| far microphone | 91 / 1 / 82% | 83 / 1 / 74% |
| phone band | 86 / 2 / 78% | 88 / 2 / 80% |
| all three ("Lee-like"); 8 chatter clips ran | 26 / 6 / 20%; 3 | 30 / 4 / 27%; 0 |

| Release to text, 58 Piper clips, 3 repeats | median of medians | whisper-server CPU per utterance |
| --- | --- | --- |
| Vosk (the fast path answered 165 of the 290 corpus clips) | 7 ms | – |
| whisper tiny.en, Blender and grammar prompt | 464 ms (466 / 464 / 464) | 1.8 s |
| whisper tiny.en, Blender prompt only | 426 ms | 1.6 s |
| whisper base.en, Blender and grammar prompt | 1,004 ms (1,010 / 1,004 / 1,003) | 3.9 s |

¹ Google Speech Commands v0.02 test set (CC BY 4.0). Vosk through `VoiceInput` on the clips padded 300 ms before and
150 ms after, Whisper on the clips with a prompt of the 35 words; combined offline with this `PhraseSnapper` and the
fast-path rule. Whisper alone, snapped: tiny.en 909 / 29, base.en 913 / 27.
² Piper and espeak-en-us clips of the corpus, degraded to mimic what went wrong in #93 (cut-off starts, a distant laptop
microphone, a narrow band).

So on TTS the fast path is no better than Vosk with the full phrase grammar: it wins on cut-off and narrow-band audio,
loses on clean and distant audio, and runs fewer wrong commands and less chatter. Its case rests on real voices, where
Vosk's small model with today's word grammar got 3 of 20 intended commands in #93; the team's own recordings are the
test that decides.

tiny.en is the default: base.en is no more accurate here (2 more right of 1,008 real clips, 3 fewer of 270 on the TTS
corpus) and takes twice as long and twice the CPU. Whisper alone on real single words is worse than Vosk (909 of 1,008),
which is why Vosk answers first. The grammar words in the prompt are worth 9 of 270 for 38 ms. All but the Speech
Commands rows are TTS, so treat them as a proxy for real voices; the Quest microphone over Air Link is unmeasured.
On the demo PC the CPU also runs Unity and Blender, so expect whisper to be slower there.

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
accuracy and the confidence threshold with the Quest microphone. Steps 1 to 3 passed on Windows 11 with a laptop and an
earphone microphone ([#93](https://github.com/waaberi/calhacks13/issues/93); see [Confidence threshold](#confidence-threshold)).

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

## Push-to-talk pre-roll

`VoiceInput`'s pre-roll keeps the last 300 ms of microphone audio while push-to-talk is up and feeds it first when the
button goes down; the post-roll keeps listening 150 ms after the release, because Unity's microphone ring delivers the
last frames late. Both are 0 unless the constructor asks for them. Measured on TTS with simulated push-to-talk
(research, 10:50 PT): speaking right at the press, correct commands went from 169 to 238 of 250, and the leading "add"
was lost 3 times instead of 65 of 80; releasing 50 ms early no longer lost short answers ("one", "two"). Pressing about
300 ms before speaking does as well without it (255 of 270 exact), so it is cheap insurance for people who talk at the
press. A prompt during the post-roll ends the utterance with what it has.

## Routing to the host: measured

Scripts and data in `/var/tmp/research-voicecore-route/` (not in Git), all through this branch's real `VoiceSession`:

| Check | Result |
| --- | --- |
| Routing against the research's emulation (written before #142), on all 1,756 texts and Vosk transcripts it used | 1,748 agree; the 8 others are by design: 6 transcripts with two different verbs ("rotate add monkey grease random d") stay on the mishearing check, and empty or "[unk]"-only words don't go out |
| A host reject gives exactly the turn VoiceCore gives without a host | 1,756 of 1,756 |
| Today's 17 commands, 5 TTS voices, 3 runs (255), padded like the pre-roll, Cube selected | today's grammar, no host: 218 right. With the host's 407 phrases merged: 207 without routing, 201 with routing and the host's resolver (copy of codex/waaberi-p4-voice-ops at 12:50); without "to": 211 and 205 |
| "Two" in "move it minus two centimeters along y", "scale it by two", "two" (45 clips) | median confidence 0.50 with today's grammar; 0.71 to 0.87 with the host's phrases; 0.72 to 1.0 with them and without "to" |
| Answers to "which one?" on real speech (Speech Commands, from the real-voice run at 12:30) | exact phrase only: 69 of 71 right, 30 of 488 other words taken; at confidence 0.9: 68 right, 0 wrong, 13 taken |

The merged grammar costs today's commands about 5 % on TTS (218 to 205 of 255): host phrases such as "delete loose"
and "low" compete with "delete this" and "rotate the sphere". The host's phrase list decides that, so trim it there.

## Confidence threshold

`VoiceSessionOptions.MinConfidence` stays at 0.5. A result's confidence is its lowest word confidence, and Vosk gives
"two" about 0.5 for every voice (0.46 to 0.50), because "to" is in the grammar too and sounds the same. A higher
threshold rejects nearly every command with "two" in it. Intended / wrong / no command, by threshold:

| `MinConfidence` | TTS, 100 samples (Linux) | Lee's voice, laptop mic, 20 samples (#93) | Lee's voice, earphone mic, 20 samples (#93) |
| --- | --- | --- | --- |
| 0.5 | 54 / 0 / 46 | 3 / 1 / 16 | 1 / 0 / 19 |
| 0.6 | 43 to 46 / 0 / 54 to 57 | 3 / 0 / 17 | 1 / 0 / 19 |

Vosk's results vary a little between runs, hence the range. The one wrong command: on the laptop mic, "move it up five
millimeters" was heard as "move eight add y millimeters" (0.56) and moved the cube 8 mm along Y. That transcript has
two different verbs, so the parser now treats it as misheard: no command, and the low-confidence prompt. Only undo,
redo, cancel and apply may name another command ("undo the move"). Recheck with the Quest microphone over Air Link.
