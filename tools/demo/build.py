"""Cut the walkthrough recording into scenes, fit each to its narration, caption it, and join it.

    python tools/demo/build.py --log out/walkthrough.log     # scene times from the run's MARK lines
    python tools/demo/build.py --timings times.json            # hand-read scene times
    python tools/demo/build.py --sheet                        # a contact sheet, one frame per 2 s

Per scene: an agent wait inside it is sped up and labelled on screen with the factor (never cut or
faked), or with --real-time kept at 1x and labelled with its real length; a scene shorter than its
narration is slowed up to 2x and then holds its last frame; the narration starts 0.3 s in.
Captions are PNGs drawn with Pillow, because the Homebrew ffmpeg build has no drawtext. Needs
ffmpeg and ffprobe on PATH. See docs/demo-video.md.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # noqa: S404 - runs ffmpeg/ffprobe with fixed arguments
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECORDING = (
    HERE.parents[1]
    / "frontend/test-results/walkthrough/walkthrough-Foresight-in-three-minutes/video.webm"
)
W, H, FPS = 1280, 800, 30
LEAD, TAIL = 0.3, 0.7  # silence before and after each narration line
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
NOTE = "AI-narrated in my voice  ·  Demo data is fictional"

Scene = tuple[str, float, float, "tuple[float, float] | None"]


def run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True)  # noqa: S603


def duration(path: Path) -> float:
    out = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def from_log(log: Path, video: Path) -> list[Scene]:
    """Scenes from the walkthrough's `MARK <seconds> scene <name>` lines, with the agent waits
    (`wait-start`/`wait-end`) placed in the scene they fall in."""
    marks = re.findall(r"MARK ([\d.]+) (.+)", log.read_text())
    starts = [(float(t), what.split(" ", 1)[1]) for t, what in marks if what.startswith("scene ")]
    waits: dict[str, float] = {what: float(t) for t, what in marks if what.startswith("wait-")}
    end = duration(video)
    scenes: list[Scene] = []
    for i, (start, name) in enumerate(starts):
        stop = starts[i + 1][0] if i + 1 < len(starts) else end
        wait = None
        for kind in ("proactive", "answer"):
            a, b = waits.get(f"wait-start {kind}"), waits.get(f"wait-end {kind}")
            if a is not None and b is not None and start <= a < stop:
                wait = (a, min(b, stop))
        scenes.append((name, start, stop, wait))
    return scenes


def from_json(path: Path) -> list[Scene]:
    rows = json.loads(path.read_text())["scenes"]
    return [(r["name"], r["start"], r["end"], tuple(r["wait"]) if r.get("wait") else None)
            for r in rows]  # fmt: skip


def pill(text: str, path: Path, size: int) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(FONT, size)
    x0, y0, x1, y1 = font.getbbox(text)
    pad_x, pad_y = 16, 9
    img = Image.new("RGBA", (int(x1 - x0) + 2 * pad_x, int(y1 - y0) + 2 * pad_y), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, img.width - 1, img.height - 1), radius=img.height // 2, fill=(20, 24, 40, 205)
    )
    draw.text((pad_x - x0, pad_y - y0), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)


def scene_clip(
    video: Path, audio: Path, work: Path, note: Path, scene: Scene, real_time: bool
) -> Path:
    name, start, end, wait = scene
    narration = audio / f"{name}.wav"
    target = duration(narration) + LEAD + TAIL
    label = None
    if wait:
        before, after = wait[0] - start, end - wait[1]
        factor = max(1.0, (wait[1] - wait[0]) / max(2.5, target - before - after))
        if real_time:
            factor = 1.0
        parts = [(start, wait[0], 1.0), (wait[0], wait[1], 1 / factor), (wait[1], end, 1.0)]
        if real_time:
            label = f"Agents working  ·  real time, {int(wait[1] - wait[0] + 0.5)} s"  # half up
        else:
            label = f"Agents working  ·  sped up {factor:.0f}×" if factor >= 1.5 else None
    else:
        parts = [(start, end, min(2.0, max(1.0, target / (end - start))))]
    pieces = []
    for i, (a, b, stretch) in enumerate(parts):
        if b - a < 0.05:
            continue
        piece = work / f"{name}-{i}.mp4"
        run("ffmpeg", "-y", "-hide_banner", "-ss", f"{a}", "-to", f"{b}", "-i", str(video),
            "-vf", f"setpts={stretch}*(PTS-STARTPTS),fps={FPS},scale={W}:{H}", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(piece))  # fmt: skip
        pieces.append(piece)
    listing = work / f"{name}.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in pieces))
    joined = work / f"{name}-joined.mp4"
    run("ffmpeg", "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", str(joined))  # fmt: skip
    hold = max(0.0, target - duration(joined))
    overlays = [note]
    graph = f"[0:v]tpad=stop_mode=clone:stop_duration={hold:.3f}[v0];"
    graph += "[v0][1:v]overlay=W-w-24:H-h-20[v1]"
    last = "v1"
    if label:
        badge = work / f"{name}-badge.png"
        pill(label, badge, 22)
        overlays.append(badge)
        t0 = parts[0][1] - parts[0][0]
        t1 = t0 + (parts[1][1] - parts[1][0]) * parts[1][2]
        graph += f";[v1][2:v]overlay=W-w-24:20:enable='between(t,{t0:.2f},{t1:.2f})'[v2]"
        last = "v2"
    inputs = ["-i", str(joined)]
    for image in overlays:
        inputs += ["-i", str(image)]
    inputs += ["-i", str(narration)]
    total = duration(joined) + hold
    clip = work / f"{name}-final.mp4"
    graph += f";[{1 + len(overlays)}:a]adelay={int(LEAD * 1000)}:all=1,apad[a]"
    run("ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", graph,
        "-map", f"[{last}]", "-map", "[a]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(clip))  # fmt: skip
    print(f"{name}: {total:.1f}s" + (f" ({label})" if label else ""), flush=True)
    return clip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, default=RECORDING)
    parser.add_argument("--audio", type=Path, default=HERE / "out" / "audio")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "foresight-demo.mp4")
    times = parser.add_mutually_exclusive_group(required=True)
    times.add_argument("--log", type=Path, help="the walkthrough run's output, with MARK lines")
    times.add_argument("--timings", type=Path, help="scene times as JSON (docs/demo-video.md)")
    times.add_argument("--sheet", action="store_true", help="only write a contact sheet")
    parser.add_argument(
        "--real-time", action="store_true", help="keep the agent waits at their real speed"
    )
    args = parser.parse_args()

    # ffmpeg's concat lists resolve relative paths against the list's folder: use absolute ones.
    args.out, args.video, args.audio = (p.resolve() for p in (args.out, args.video, args.audio))
    work = args.out.parent / "build"
    work.mkdir(parents=True, exist_ok=True)
    if args.sheet:
        frames = work / "frames"
        frames.mkdir(exist_ok=True)
        for old in frames.glob("*.png"):
            old.unlink()
        run("ffmpeg", "-hide_banner", "-i", str(args.video), "-vf", "fps=1/2,scale=320:-1",
            str(frames / "f%03d.png"))  # fmt: skip
        sheet = args.out.parent / "sheet.png"
        run("ffmpeg", "-y", "-hide_banner", "-i", str(frames / "f%03d.png"),
            "-vf", "tile=8x8:padding=4:color=black", "-frames:v", "1", str(sheet))  # fmt: skip
        print(f"wrote {sheet}: row by row, frame n is at {2}*(n-1) seconds")
        return

    scenes = from_log(args.log, args.video) if args.log else from_json(args.timings)
    note = work / "note.png"
    pill(NOTE, note, 20)
    clips = [scene_clip(args.video, args.audio, work, note, s, args.real_time) for s in scenes]
    listing = work / "all.txt"
    listing.write_text("".join(f"file '{c}'\n" for c in clips))
    run("ffmpeg", "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart", str(args.out))  # fmt: skip
    print(f"wrote {args.out} ({duration(args.out):.1f}s)")


if __name__ == "__main__":
    main()
