"""'Ideal' reference audio, synthesised with the espeak-ng CLI.

espeak-ng is a formant synthesiser: the output is robotic but *phonetically exact*,
which is what a pronunciation model wants -- the learner hears the target phones,
including at half speed, with no natural-speech reduction blurring the contrast.
`neural_tts.speech` (OmniVoice) is the natural-sounding alternative when its
server is up; this module stays the fallback, and the contract is the same either
way -- text in, WAV bytes out.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from .config import find_espeak_data, find_espeak_exe, settings


def _data_args() -> list[str]:
    data = find_espeak_data()
    return [f"--path={data}"] if data else []


class TTSUnavailable(RuntimeError):
    pass


def _cache_path(key: str) -> Path:
    d = settings.cache_dir / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.wav"


def synthesize(text: str, voice: str | None = None, speed: int | None = None,
               pitch: int = 50, word_gap: int = 0) -> bytes:
    """Render `text` to WAV bytes. Results are cached on disk."""
    voice = voice or settings.espeak_voice
    speed = speed or settings.tts_speed_normal

    key = hashlib.sha1(
        f"{text}|{voice}|{speed}|{pitch}|{word_gap}".encode("utf-8")
    ).hexdigest()
    cached = _cache_path(key)
    if cached.exists():
        return cached.read_bytes()

    exe = find_espeak_exe()
    if exe is None:
        raise TTSUnavailable(
            "espeak-ng CLI not found. Install espeak-ng or set ESPEAK_NG_BINARY. "
            "See scripts/setup_windows.ps1."
        )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.wav"
        cmd = [
            str(exe),
            *_data_args(),
            "-v", voice,
            "-s", str(speed),
            "-p", str(pitch),
            "-g", str(word_gap),
            "-w", str(out),
            "--", text,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode != 0 or not out.exists():
            raise TTSUnavailable(
                f"espeak-ng failed ({proc.returncode}): "
                f"{proc.stderr.decode('utf-8', 'replace').strip()}"
            )
        data = out.read_bytes()

    cached.write_bytes(data)
    return data


def phonemes_via_cli(text: str, voice: str | None = None) -> str:
    """espeak's own IPA rendering (`-x --ipa`). Handy for cross-checking phonemizer."""
    exe = find_espeak_exe()
    if exe is None:
        raise TTSUnavailable("espeak-ng CLI not found.")
    proc = subprocess.run(
        [str(exe), *_data_args(), "-v", voice or settings.espeak_voice,
         "-q", "--ipa", "--", text],
        capture_output=True, timeout=15,
    )
    return proc.stdout.decode("utf-8", "replace").strip()
