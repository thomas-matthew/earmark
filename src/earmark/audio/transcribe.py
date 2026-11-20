"""Local speech-to-text for spoken media (C3): Whisper large-v3-turbo on MLX.

The writer retells a video or podcast from its transcript instead of playing the recording. The
model runs in a child process, so its memory is handed back as soon as the transcript is written,
before the voice model loads. Shared models live in HF_HOME, like the voice model."""
import subprocess
import sys
from pathlib import Path

MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"  # includes the tokenizer files mlx-audio needs
SAMPLE_RATE = 16000
PARAGRAPH_SECONDS = 60  # a time mark and a new paragraph about once a minute, so the writer can find its way
TIMEOUT_SECONDS = 3 * 3600
MLX_CACHE_BYTES = 1 << 30


class TranscriptionFailed(Exception):
    pass


def transcribe(audio: Path) -> str:
    """Transcript of an audio file, as paragraphs that each start with a [minutes:seconds] mark."""
    out = audio.with_suffix(".transcript.txt")
    done = subprocess.run([sys.executable, "-m", "earmark.audio.transcribe", str(audio), str(out)],
                          capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    if done.returncode != 0 or not out.exists():
        last = (done.stderr or done.stdout).strip().splitlines()[-1:]
        raise TranscriptionFailed(last[0] if last else "no transcript was written")
    return out.read_text(encoding="utf-8")


def paragraphs(segments: list[dict], seconds: int = PARAGRAPH_SECONDS) -> str:
    groups: list[tuple[float, list[str]]] = []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        if not groups or segment["start"] - groups[-1][0] >= seconds:
            groups.append((segment["start"], []))
        groups[-1][1].append(text)
    return "\n\n".join(f"[{int(start // 60)}:{int(start % 60):02d}] {' '.join(words)}" for start, words in groups)


def _main(audio: str, out: str) -> None:
    from .. import config  # noqa: F401  sets HF_HOME before the model loads
    import mlx.core as mx
    from mlx_audio.stt.utils import load_model

    from ..content.media import decode

    mx.set_cache_limit(MLX_CACHE_BYTES)
    model = load_model(MODEL)
    result = model.generate(mx.array(decode(Path(audio), SAMPLE_RATE)), language="en", verbose=False,
                            condition_on_previous_text=False)  # stops one misheard stretch from repeating
    text = paragraphs(result.segments or []) or (result.text or "").strip()
    Path(out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    _main(sys.argv[1], sys.argv[2])
