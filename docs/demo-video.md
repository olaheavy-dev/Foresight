# Demo video: recording, voice-over and updates

The two-minute narrated demo is made from three parts:

1. **The walkthrough recording.** `frontend/e2e/walkthrough.spec.ts` drives the live app on the fictional demo profile and records video. It asks one real question and runs one proactive check, so **each recording costs about $0.10 of OpenAI credit**.
2. **The narration.** `tools/demo/script.md`, one `## <scene>` section per scene, rendered by `tools/demo/narrate.py` in a cloned voice.
3. **The edit.** `tools/demo/build.py` fits each scene's video to its narration, speeds up the agent waits with an on-screen label, adds captions and writes an MP4.

Everything runs locally. The voice recording, the cloned audio and the video stay in `tools/demo/voice/` and `tools/demo/out/`, which git ignores. **Never commit a voice recording**: a short sample is enough for anyone to clone the voice.

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

> Hi, I'm Sunkanmi. I build products from idea to production, with AI built in. Foresight is a personal-finance workspace I designed and built myself. It forecasts where your money is heading, and every number has a receipt.

Check that it isn't silent (`mean_volume` around −30 dB is good, −91 dB means nothing was recorded), then trim the silence and even out the level:

```bash
ffmpeg -hide_banner -i tools/demo/voice/raw.wav -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
ffmpeg -y -hide_banner -loglevel error -i tools/demo/voice/raw.wav \
  -af "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,highpass=f=80,loudnorm=I=-18:TP=-2" \
  -ar 24000 -ac 1 tools/demo/voice/reference.wav
```

## 2. Render the narration

```bash
tools/demo/.venv/bin/python tools/demo/narrate.py --voice tools/demo/voice/reference.wav
```

This writes `tools/demo/out/audio/<scene>.wav`, about 20 seconds of generation per 10 seconds of speech. Listen with `afplay tools/demo/out/audio/01-intro.wav`.

- **Change a line:** edit `tools/demo/script.md`, then render only that scene again with `--only 05-answer`.
- **Mispronounced word:** spell it the way it sounds in the script (for example "Fore-sight") and render that scene again.
- **Delivery:** the defaults are the "calmer" settings chosen on 25 Oct 2026 (`--exaggeration 0.4 --cfg 0.3`). Raise `--exaggeration` (up to about 0.7) for more expression. Raise `--cfg` (0.5 is Chatterbox's default) for faster, tighter speech.

Every clip carries Chatterbox's inaudible watermark, so it can be identified as generated.

## 3. Record the walkthrough (about $0.10)

```bash
cd frontend
WALKTHROUGH=1 npx playwright test -c playwright.walkthrough.config.ts --reporter=line | tee ../tools/demo/out/walkthrough.log
cd ..
```

The video lands in `frontend/test-results/walkthrough/walkthrough-Foresight-in-three-minutes/video.webm`. The log has a `MARK <seconds> scene <name>` line for each scene and `wait-start`/`wait-end` lines around the two agent waits. Set `BASE_URL` to record another deployment.

## 4. Build the video

```bash
tools/demo/.venv/bin/python tools/demo/build.py --log tools/demo/out/walkthrough.log
open tools/demo/out/foresight-demo.mp4
```

What the build does:
- **Agent waits** are sped up just enough for the narration and labelled "Agents working · sped up N×". They are never cut or faked.
- **Short scenes:** a scene shorter than its narration plays up to 2× slower, then holds its last frame.
- **Captions:** every frame carries "AI-narrated in my voice · Demo data is fictional". Keep that caption whenever the voice is cloned.

To check the scene times by eye, write a contact sheet (one frame every 2 seconds) with `build.py --sheet`. For a recording made before the spec printed scene marks, pass hand-read times with `--timings tools/demo/timings.json` (the 25 Oct 2026 recording).

## Updating the voice later

| You want to | Do |
|---|---|
| Re-record your reference (new microphone, different tone) | Step 1, then steps 2 and 4. No new walkthrough recording, so no model spend. |
| Use your own voice, not a clone | Record each scene's line to `tools/demo/out/audio/<scene>.wav` (24 kHz mono WAV) instead of step 2, then step 4. Change the caption in `build.py` (`NOTE`) to "Demo data is fictional". |
| Use a stock voice | Any engine works, as long as it writes the same per-scene WAV files. Kokoro (Apache 2.0) and macOS Premium voices (`say -v "Jamie (Premium)"`) were tried on 25 Oct 2026. Change `NOTE` to "AI narration · Demo data is fictional". |
| Change what's said | Edit `script.md`, then steps 2 (`--only` the changed scenes) and 4. |
| Show a newer version of the app | Steps 3 and 4. If the walkthrough's steps change, keep its `mark("scene …")` names in line with the `## <scene>` headings in `script.md`. |

Keep every claim in the script true of the repository (numbers from the engine, 20 Verifier rules, 17 evaluation suites, fictional demo data). If one stops being true, change the line before publishing.
