"""Render a whole script with Breeze TTS 2, anchoring each voice to one reference clip.

Usage (from experiments/): uv run python breeze_full.py STORY_ID
"""
import json
import re
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
MAX_CHUNK_CHARS = 420  # the model caps each generation, so long paragraphs are split by sentence
TARGET_LOUDNESS = 0.06  # every piece is leveled to this RMS so voices and paragraphs match
DATA = Path(__file__).resolve().parent / "data"

VOICES = {
    "N": {
        "instruction": "A warm, thoughtful narrator explaining something interesting to a curious friend. "
                       "Natural conversational pacing, clear and engaged, never theatrical.",
        "reference": "Thanks for listening. Today I want to walk you through something I found interesting, "
                     "and explain why I think it matters, one step at a time.",
    },
    "Q": {
        "instruction": "A relaxed, thoughtful man in his forties sharing his own opinion in a casual, "
                       "plain-spoken way. Clear and natural.",
        "reference": "Honestly, I have been using this for a while now, and my experience has been a little "
                     "different from what most people here seem to be describing.",
    },
}


def chunks(text: str) -> list[str]:
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) + 1 > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    return pieces + [current] if current else pieces


def collect(model, **kwargs) -> np.ndarray:
    results = model.generate(cfg_scale=4, seed=SEED, split_pattern=None, verbose=False, **kwargs)
    return np.concatenate([np.array(r.audio) for r in results])


def main() -> None:
    story_id = sys.argv[1]
    lines = [l for l in (DATA / f"script_{story_id}_agent.txt").read_text().splitlines() if l.strip()]
    model = load_model(MODEL)

    refs = {}
    for tag, voice in VOICES.items():
        path = DATA / f"breeze_reference_{tag}.wav"
        audio = collect(model, text=voice["reference"], instruct=voice["instruction"])
        sf.write(path, audio, SAMPLE_RATE)
        refs[tag] = str(path)
        print(f"reference {tag}: {len(audio) / SAMPLE_RATE:.1f}s", flush=True)

    begin = time.time()
    parts, stats = [], []
    paragraph_gap, chunk_gap = np.zeros(int(SAMPLE_RATE * 0.5)), np.zeros(int(SAMPLE_RATE * 0.12))
    for index, line in enumerate(lines):
        tag, text = line[0], line[3:].strip()
        for piece in chunks(text):
            audio = collect(model, text=piece, ref_audio=refs[tag], ref_text=VOICES[tag]["reference"])
            audio = np.clip(audio * (TARGET_LOUDNESS / np.sqrt(np.mean(audio ** 2))), -1.0, 1.0)
            seconds = len(audio) / SAMPLE_RATE
            stats.append({
                "line": index, "voice": tag, "chars": len(piece), "seconds": round(seconds, 1),
                "chars_per_second": round(len(piece) / seconds, 1),
                "loudness": round(float(np.sqrt(np.mean(audio ** 2))), 4),
                "start": piece[:50],
            })
            parts += [audio, chunk_gap]
        parts.append(paragraph_gap)
        print(f"line {index + 1}/{len(lines)} done, {time.time() - begin:.0f}s elapsed", flush=True)

    elapsed = time.time() - begin
    audio = np.concatenate(parts)
    out = DATA / f"episode_{story_id}_breeze_full.mp3"
    sf.write(out, audio, SAMPLE_RATE, format="MP3")
    (DATA / f"breeze_stats_{story_id}.json").write_text(json.dumps(stats, indent=1))
    total = len(audio) / SAMPLE_RATE
    print(f"\nwrote {out}\n{total / 60:.1f} min of audio in {elapsed / 60:.1f} min ({total / elapsed:.1f}x realtime), {len(stats)} chunks")

    for tag in VOICES:
        group = [s for s in stats if s["voice"] == tag]
        rates, loud = [s["chars_per_second"] for s in group], [s["loudness"] for s in group]
        print(f"voice {tag}: {len(group)} chunks, speech rate median {np.median(rates):.1f} chars/s "
              f"(range {min(rates)}-{max(rates)}), loudness range {min(loud)}-{max(loud)}")
        median = float(np.median(rates))
        for s in group:
            if s["chars_per_second"] > median * 1.35 or s["chars_per_second"] < median * 0.65:
                print(f"  OUTLIER line {s['line']}: {s['chars_per_second']} chars/s, {s['seconds']}s, \"{s['start']}\"")


if __name__ == "__main__":
    main()
