"""Spoken media (C3): when a saved item links to a video or a podcast episode, the episode uses its
original audio track. yt-dlp downloads the audio; macOS's built-in afconvert decodes it."""
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

import numpy as np
import soundfile as sf

MEDIA_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "vimeo.com", "www.vimeo.com"}


def is_media_link(url: str | None) -> bool:
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in MEDIA_HOSTS:
        return False
    if host.endswith("youtube.com"):
        return parsed.path.startswith(("/watch", "/shorts/", "/live/"))
    return bool(parsed.path.strip("/"))


def describe(url: str) -> dict:
    """Title, channel and length of a video, without downloading it."""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return {"title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
            "seconds": info.get("duration"), "description": (info.get("description") or "")[:3000]}


def download_audio(url: str, folder: Path) -> Path:
    """Download the best audio-only stream that needs no re-encoding."""
    import yt_dlp

    folder.mkdir(parents=True, exist_ok=True)
    options = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio[ext=mp3]",
        "outtmpl": str(folder / "source.%(ext)s"),
    }
    if Path(urllib.parse.urlparse(url).path).suffix.lower() in {".mp3", ".m4a", ".aac", ".wav"}:
        options.pop("format")  # a direct audio file, such as a Substack podcast episode
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))


def decode(path: Path, sample_rate: int) -> np.ndarray:
    """Decode any audio file macOS understands to mono float samples at the given rate."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "decoded.wav"
        subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", f"LEI16@{sample_rate}", "-c", "1", str(path), str(wav)],
                       check=True, capture_output=True)
        audio, _ = sf.read(wav, dtype="float32")
    return audio
