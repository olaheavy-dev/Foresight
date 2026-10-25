"""Render the demo's narration (tools/demo/script.md), one WAV per scene, in a cloned voice.

Uses Chatterbox (Resemble AI, MIT licence) locally: on Apple Silicon it runs on the GPU (MPS), and
neither the reference recording nor the text leaves the machine. Every output carries Resemble's
inaudible Perth watermark, so it can be identified as generated. See docs/demo-video.md.

    python tools/demo/narrate.py --voice tools/demo/voice/reference.wav    # every scene
    python tools/demo/narrate.py --voice ... --only 05-answer               # one scene again

Run it in the demo environment (tools/demo/requirements.txt), not the app's.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# The settings chosen on 25 Oct 2026 ("calmer"): less expressive and steadier than the defaults.
EXAGGERATION, CFG_WEIGHT = 0.4, 0.3
PAUSE_SECONDS = 0.45  # between paragraphs within a scene


def scenes(script: Path) -> dict[str, str]:
    """`## <name> (notes)` headings to their narration text."""
    found = re.findall(r"^## (\S+)[^\n]*\n(.+?)(?=^## |\Z)", script.read_text(), re.S | re.M)
    return {name: text.strip() for name, text in found}


def load_model() -> Any:
    import torch
    from chatterbox.tts import ChatterboxTTS

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    # The checkpoints were saved on CUDA: map them onto whatever this machine has.
    original = torch.load
    torch.load = lambda *a, **k: original(*a, **{**k, "map_location": torch.device(device)})
    try:
        return ChatterboxTTS.from_pretrained(device=device)
    finally:
        torch.load = original


def render(model: Any, text: str, voice: Path, out: Path, exaggeration: float, cfg: float) -> float:
    import torch
    import torchaudio

    pause = torch.zeros(1, int(model.sr * PAUSE_SECONDS))
    parts: list[Any] = []
    for paragraph in [p.strip() for p in text.split("\n\n") if p.strip()]:
        wav = model.generate(
            paragraph, audio_prompt_path=str(voice), exaggeration=exaggeration, cfg_weight=cfg
        )
        parts += [pause, wav.cpu()] if parts else [wav.cpu()]
    audio = torch.cat(parts, dim=1)
    torchaudio.save(str(out), audio, model.sr)
    return float(audio.shape[1] / model.sr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voice", type=Path, required=True, help="reference recording, 10–20 s")
    parser.add_argument("--script", type=Path, default=HERE / "script.md")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "audio")
    parser.add_argument("--only", nargs="*", help="scene names to render again (default: all)")
    parser.add_argument("--exaggeration", type=float, default=EXAGGERATION)
    parser.add_argument("--cfg", type=float, default=CFG_WEIGHT)
    args = parser.parse_args()

    todo = scenes(args.script)
    if args.only:
        unknown = set(args.only) - set(todo)
        if unknown:
            parser.error(f"no such scene: {', '.join(sorted(unknown))}")
        todo = {name: todo[name] for name in args.only}
    args.out.mkdir(parents=True, exist_ok=True)
    model = load_model()
    for name, text in todo.items():
        seconds = render(model, text, args.voice, args.out / f"{name}.wav", args.exaggeration,
                         args.cfg)  # fmt: skip
        print(f"{name}: {seconds:.1f}s", flush=True)


if __name__ == "__main__":
    main()
