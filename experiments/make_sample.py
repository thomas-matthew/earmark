"""Render a real long-form article with local Kokoro to judge narration quality."""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

import os
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path.home() / "Dev" / "labs" / "huggingface"))  # models are shared across projects

import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model

# Run from a short venv path (~/.cache/bookmark-audio/venv): espeak-ng falls back to a
# compiled-in data path when its real data path is too long for its fixed buffer.

TITLE = "Voyager_1"
MAX_CHARS = 9000
VOICE = sys.argv[1] if len(sys.argv) > 1 else "af_heart"
SAMPLE_RATE = 24000
MODEL = "mlx-community/Kokoro-82M-bf16"


def fetch_article(title: str) -> str:
    query = urllib.parse.urlencode({
        "action": "query", "prop": "extracts", "explaintext": 1,
        "titles": title, "format": "json", "redirects": 1,
    })
    req = urllib.request.Request(
        f"https://en.wikipedia.org/w/api.php?{query}",
        headers={"User-Agent": "bookmark-audio-prototype/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        pages = json.load(resp)["query"]["pages"]
    return next(iter(pages.values()))["extract"]


def clean_for_speech(text: str, limit: int) -> str:
    """Drop headings and blank lines; cut at a paragraph boundary near the limit."""
    paragraphs = []
    total = 0
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or line.startswith("=="):
            continue
        if line.startswith(("See also", "References", "External links")):
            break
        if total + len(line) > limit:
            break
        paragraphs.append(line)
        total += len(line)
    return "\n".join(paragraphs)


def main() -> None:
    text = clean_for_speech(fetch_article(TITLE), MAX_CHARS)
    with open(f"sample_{VOICE}.txt", "w") as f:
        f.write(text)
    print(f"characters: {len(text)}, words: {len(text.split())}", flush=True)

    model = load_model(MODEL)
    start = time.time()
    chunks = [
        np.array(result.audio)
        for result in model.generate(text=text, voice=VOICE, speed=1.0, lang_code="a", split_pattern=r"\n+")
    ]
    gap = np.zeros(int(SAMPLE_RATE * 0.5))
    audio = np.concatenate([part for chunk in chunks for part in (chunk, gap)])
    elapsed = time.time() - start

    out = f"sample_{VOICE}.wav"
    sf.write(out, audio, SAMPLE_RATE)
    duration = len(audio) / SAMPLE_RATE
    print(f"wrote {out}: {duration / 60:.1f} min audio in {elapsed:.0f}s "
          f"({duration / elapsed:.0f}x realtime), {len(chunks)} segments, "
          f"peak {np.abs(audio).max():.2f}")


if __name__ == "__main__":
    main()
