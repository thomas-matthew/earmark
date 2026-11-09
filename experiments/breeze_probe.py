"""Render the opening of a saved script with Breeze TTS 2 and measure speed and memory.

Usage (from experiments/): uv run python breeze_probe.py STORY_ID [MAX_CHARS]
"""
import resource
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

import bookcast  # noqa: F401  (points the model cache at the shared folder)
from mlx_audio.tts.utils import load_model

MODEL = "mlx-community/Breeze-TTS-2-mlx"
SAMPLE_RATE = 24000
SEED = 7
INSTRUCTION = (
    "A warm, thoughtful narrator explaining something interesting to a curious friend. "
    "Natural conversational pacing, clear and engaged, never theatrical."
)
DATA = Path(__file__).resolve().parent / "data"


def main() -> None:
    story_id = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1400
    paragraphs, total = [], 0
    for line in (DATA / f"script_{story_id}_agent.txt").read_text().splitlines():
        text = line[3:].strip()
        if not text or (paragraphs and total + len(text) > limit):
            break
        paragraphs.append(text)
        total += len(text)
    print(f"{len(paragraphs)} paragraphs, {total} chars", flush=True)

    start = time.time()
    model = load_model(MODEL)
    print(f"loaded in {time.time() - start:.0f}s", flush=True)

    gap = np.zeros(int(SAMPLE_RATE * 0.45))
    parts, begin = [], time.time()
    for paragraph in paragraphs:
        for result in model.generate(
            text=paragraph, instruct=INSTRUCTION, cfg_scale=4, seed=SEED, split_pattern=None, verbose=False,
        ):
            parts += [np.array(result.audio), gap]
    elapsed = time.time() - begin
    audio = np.concatenate(parts)
    out = DATA / f"episode_{story_id}_breeze.mp3"
    sf.write(out, audio, SAMPLE_RATE, format="MP3")
    seconds = len(audio) / SAMPLE_RATE
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 3
    print(f"wrote {out}: {seconds:.0f}s of audio in {elapsed:.0f}s "
          f"({seconds / elapsed:.1f}x realtime), peak process memory {peak:.1f} GB, peak level {np.abs(audio).max():.2f}")


if __name__ == "__main__":
    main()
