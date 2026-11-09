"""Narration with Breeze TTS 2 on MLX (A2, A7).

Each voice is anchored to a reference clip generated once from a written voice description and
kept in data/voices/, so voices stay the same across episodes. Every piece is leveled to the same
loudness. The model loads on first use and is freed when the run process exits."""
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from ..llm.script import Script

MODEL = "mlx-community/Breeze-TTS-2-mlx"
SAMPLE_RATE = 24000
SEED = 7
MAX_CHUNK_CHARS = 420  # the model caps each generation, so long paragraphs are split by sentence
TARGET_LOUDNESS = 0.06  # RMS every spoken piece is leveled to
PARAGRAPH_GAP, CHUNK_GAP, MEDIA_GAP = 0.5, 0.12, 1.0

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


def chunks(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text at sentence ends into pieces under the model's limit. A single overlong sentence
    is split at commas, then at spaces."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        for part in _split_long(sentence, limit):
            if current and len(current) + len(part) + 1 > limit:
                pieces.append(current)
                current = part
            else:
                current = f"{current} {part}".strip()
    return pieces + [current] if current else pieces


def _split_long(sentence: str, limit: int) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    parts, current = [], ""
    for word in re.split(r"(?<=,)\s+|\s+", sentence):
        if current and len(current) + len(word) + 1 > limit:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    return parts + [current] if current else parts


def level(audio: np.ndarray, target: float = TARGET_LOUDNESS) -> np.ndarray:
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    if rms < 1e-5:
        return audio
    return np.clip(audio * (target / rms), -1.0, 1.0)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


class Narrator:
    def __init__(self, voices_dir: Path):
        self.voices_dir = voices_dir
        self._model = None
        self._refs: dict[str, str] = {}

    def _generate(self, **kwargs) -> np.ndarray:
        results = self._model.generate(cfg_scale=4, seed=SEED, split_pattern=None, verbose=False, **kwargs)
        return np.concatenate([np.array(r.audio, dtype=np.float32) for r in results])

    def _load(self) -> None:
        if self._model is not None:
            return
        from mlx_audio.tts.utils import load_model

        self._model = load_model(MODEL)
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        for tag, voice in VOICES.items():
            path = self.voices_dir / f"reference_{tag}.wav"
            if not path.exists():
                sf.write(path, self._generate(text=voice["reference"], instruct=voice["instruction"]), SAMPLE_RATE)
            self._refs[tag] = str(path)

    def speak(self, text: str, voice: str) -> np.ndarray:
        self._load()
        parts = []
        for piece in chunks(text):
            audio = self._generate(text=piece, ref_audio=self._refs[voice], ref_text=VOICES[voice]["reference"])
            parts += [level(audio), silence(CHUNK_GAP)]
        return np.concatenate(parts) if parts else silence(0)

    def render(self, script: Script, out: Path, media: np.ndarray | None = None, log=print) -> float:
        """Write the episode MP3 and return its length in seconds. Media audio, if any, plays after
        the first narrator paragraph (C3)."""
        parts = []
        for index, line in enumerate(script.lines):
            parts += [self.speak(line.text, line.voice), silence(PARAGRAPH_GAP)]
            if index == 0 and media is not None:
                parts += [silence(MEDIA_GAP), level(media), silence(MEDIA_GAP)]
            if (index + 1) % 10 == 0:
                log(f"  voiced {index + 1}/{len(script.lines)} paragraphs")
        audio = np.concatenate(parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".partial.mp3")
        sf.write(tmp, audio, SAMPLE_RATE, format="MP3")
        tmp.replace(out)
        return len(audio) / SAMPLE_RATE
