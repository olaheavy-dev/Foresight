# Demo video: recording, voice-over and updates

The narrated demo (about 4½ minutes) opens straight on the app with no presenter introduction. It shows how Foresight is built, explains each feature in detail in an engineer's voice (the problem, then why it's built that way), and lets the agents' process play out while the narration explains it. It is made from four parts:

1. **The walkthrough recording.** `frontend/e2e/walkthrough.spec.ts` drives the live app on the fictional demo profile and records video. It asks one real question and runs one proactive check, so **each recording costs about $0.10 of OpenAI credit**.
2. **The stack card.** `tools/demo/stack.html`, shown in the recording by the spec (scene `03-stack`) in the app's own fonts.
3. **The narration.** `tools/demo/script.md`, one `## <scene>` section per beat (one line over one action), rendered by `tools/demo/narrate.py` in a cloned voice.
4. **The edit.** `tools/demo/build.py` lays each line over its scene, labels the agent waits, adds captions and writes an MP4.

**The video is recorded to the narration.** Render the narration first: `narrate.py` writes each scene's length to `tools/demo/out/audio/durations.json`, and the walkthrough holds every scene until its line has been said before it moves on. Voice and screen then stay in step beat by beat, with nothing stretched in the edit. The spec refuses to record without that file.

Everything runs locally. The voice recording, the cloned audio and the video stay in `tools/demo/voice/` and `tools/demo/out/`, which git ignores. **Never commit a voice recording**: a short sample is enough for anyone to clone the voice.

## Saved videos

In `docs/assets/demo/`, from the walkthrough recorded on 25 Oct 2026 and narrated in the first cloned voice. The viewer notes that go with the video (scene guide, stack, results, limits, what's fictional) are in [`docs/assets/demo/README.md`](assets/demo/README.md).

| File | What |
|---|---|
| `foresight-demo.mp4` | 4:37. The proactive check (28.5 s) plays at 1.1× and the question (25.9 s) at 1.4×, each labelled on screen, so they fit the lines that explain them. |
| `walkthrough-2026-10-25.webm`, `.log` | The raw, silent recording and its scene marks. Rebuild from them with no new recording (and no model spend), after rendering the narration: `build.py --video docs/assets/demo/walkthrough-2026-10-25.webm --log docs/assets/demo/walkthrough-2026-10-25.log`. |

The earlier versions of 25 Oct 2026 (two minutes with a presenter introduction, then a three-minute cut) were replaced by this one.

## One-time setup (macOS, Apple Silicon)

```bash
brew install ffmpeg
uv venv -p 3.11 tools/demo/.venv
uv pip install -p tools/demo/.venv -r tools/demo/requirements.txt
cd frontend && npx playwright install chromium && cd ..
```

The demo environment is separate from the app's (`.venv`). `tools/demo/.venv` is covered by the `.venv/` ignore rule. The first narration run downloads the Chatterbox model (1–2 GB) from Hugging Face.

## 1. Record your voice (the reference)

Find your microphone's number. Virtual devices such as Microsoft Teams Audio are silent unless you're in a call:

```bash
ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | sed -n '/audio devices/,$p'
```

Record 20 seconds from that device (here `:2`, the MacBook Pro microphone). The terminal app needs microphone access (System Settings → Privacy & Security → Microphone):

```bash
mkdir -p tools/demo/voice
ffmpeg -y -hide_banner -loglevel error -f avfoundation -i ":2" -t 20 -ac 1 -ar 24000 tools/demo/voice/raw.wav
```

Read naturally, in the tone you want the narration to have. Use a quiet room, with the microphone 20–30 cm away. The original reading was:

> Any natural paragraph of about 20 seconds works; it is never played in the video. The original reading introduced the builder and Foresight in a few sentences.

Check that it isn't silent (`mean_volume` around −30 dB is good, −91 dB means nothing was recorded), then trim the silence and even out the level:

```bash
ffmpeg -hide_banner -i tools/demo/voice/raw.wav -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
ffmpeg -y -hide_banner -loglevel error -i tools/demo/voice/raw.wav \
  -af "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,highpass=f=80,loudnorm=I=-18:TP=-2" \
  -ar 24000 -ac 1 tools/demo/voice/reference.wav
```

## 2. Render the narration (before recording)

```bash
tools/demo/.venv/bin/python tools/demo/narrate.py --voice tools/demo/voice/reference.wav
```

This writes `tools/demo/out/audio/<scene>.wav`, about 20 seconds of generation per 10 seconds of speech. Listen with `afplay tools/demo/out/audio/01-open.wav`.

- **Change a line:** edit `tools/demo/script.md`, then render only those scenes again, for example `--only 02-home 11-answer`. A line that gets more than about a second longer or shorter means recording again, because the walkthrough held its scene for the old length.
- **Figures said aloud** (the low before payday, the holiday answer) move with the day and time of a recording. Check them against each new video and render those lines again.
- **Mispronounced word:** spell it the way it sounds in the script (for example "Fore-sight") and render that scene again.
- **Delivery:** the defaults are the "calmer" settings chosen on 25 Oct 2026 (`--exaggeration 0.4 --cfg 0.3`). Raise `--exaggeration` (up to about 0.7) for more expression. Raise `--cfg` (0.5 is Chatterbox's default) for faster, tighter speech.

Every clip carries Chatterbox's inaudible watermark, so it can be identified as generated.

## 3. Record the walkthrough (about $0.10)

```bash
cd frontend
WALKTHROUGH=1 npx playwright test -c playwright.walkthrough.config.ts --reporter=line | tee ../tools/demo/out/walkthrough.log
cd ..
```

The video lands in `frontend/test-results/walkthrough/walkthrough-Foresight-walkthrough/video.webm`. It takes about 5 minutes: each scene lasts as long as its line. The log has a `MARK <seconds> scene <name>` line for each scene and `wait-start`/`wait-end` lines around the two agent waits. Set `BASE_URL` to record another deployment.

## 4. Build the video

```bash
tools/demo/.venv/bin/python tools/demo/build.py --log tools/demo/out/walkthrough.log
open tools/demo/out/foresight-demo.mp4
```

What the build does:
- **Agent waits** play at their real speed, labelled "Agents working · real time, N s", when the line explaining them is at least as long. A longer wait is sped up just enough to fit, labelled "Agents working · sped up N×" (with a decimal, so even 1.1× is said). They are never cut or faked. The script narrates about 30 s and 20 s for the two waits. `--real-time` keeps every wait at its real speed, leaving silence where a wait outlasts its line.
- **Short scenes:** a scene shorter than its line (rare, since the spec holds each scene for its line) plays up to 2× slower, then holds its last frame.
- **Captions:** every frame carries "AI-narrated in my voice · Demo data is fictional". Keep that caption whenever the voice is cloned.

To check the scene times by eye, write a contact sheet (one frame every 2 seconds) with `build.py --sheet`. For a recording made before the spec printed scene marks, pass hand-read times as JSON with `--timings` (`{"scenes": [{"name", "start", "end", "wait"}]}`).

## Updating the voice later

| You want to | Do |
|---|---|
| Re-record your reference (new microphone, different tone) | Step 1, then steps 2 and 4. No new walkthrough recording, so no model spend. |
| Use your own voice, not a clone | Record each scene's line to `tools/demo/out/audio/<scene>.wav` (24 kHz mono WAV) instead of step 2, then step 4. Change the caption in `build.py` (`NOTE`) to "Demo data is fictional". |
| Use a stock voice | Any engine works, as long as it writes the same per-scene WAV files. Kokoro (Apache 2.0) and macOS Premium voices (`say -v "Jamie (Premium)"`) were tried on 25 Oct 2026. Change `NOTE` to "AI narration · Demo data is fictional". |
| Change what's said | Edit `script.md`, then steps 2 (`--only` the changed scenes) and 4. |
| Show a newer version of the app | Steps 3 and 4. If the walkthrough's steps change, keep its `mark("scene …")` names in line with the `## <scene>` headings in `script.md`. A live run can approve or reject the holiday advice: check what it did and keep `07-answer` and the viewer notes true to it. |
| Change the stack card | Edit `tools/demo/stack.html` (1280×800), then steps 3 and 4. |

Keep every claim in the script, the stack card and the viewer notes true of the repository (numbers from the engine, five specialist agents, 20 Verifier rules, 17 evaluation suites, 500 simulated paths, fictional demo data). If one stops being true, change the line before publishing.
