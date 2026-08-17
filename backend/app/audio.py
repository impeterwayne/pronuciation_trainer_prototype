"""Decode whatever the browser uploaded into 16 kHz mono float32."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

TARGET_SR = 16_000


class AudioError(ValueError):
    pass


def _to_mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def _resample(x: np.ndarray, src_sr: int, dst_sr: int = TARGET_SR) -> np.ndarray:
    if src_sr == dst_sr:
        return x
    # Anti-alias before decimating, otherwise high-frequency energy folds down and
    # the recogniser hears phantom fricatives.
    if src_sr > dst_sr:
        taps = max(3, int(round(src_sr / dst_sr)) | 1)
        kernel = np.hanning(taps + 2)[1:-1]
        kernel /= kernel.sum()
        x = np.convolve(x, kernel, mode="same")
    n_out = int(round(len(x) * dst_sr / src_sr))
    if n_out <= 1:
        raise AudioError("audio is too short after resampling")
    src_t = np.arange(len(x), dtype=np.float64)
    dst_t = np.linspace(0, len(x) - 1, n_out)
    return np.interp(dst_t, src_t, x).astype(np.float32)


def _decode_with_ffmpeg(data: bytes) -> tuple[np.ndarray, int]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioError(
            "unsupported audio container and ffmpeg is not installed. "
            "The bundled frontend uploads 16 kHz WAV, so this only happens with "
            "third-party clients sending webm/opus."
        )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.bin"
        dst = Path(tmp) / "out.wav"
        src.write_bytes(data)
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(src), "-ac", "1",
             "-ar", str(TARGET_SR), "-f", "wav", str(dst)],
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0 or not dst.exists():
            raise AudioError(
                f"ffmpeg could not decode the upload: "
                f"{proc.stderr.decode('utf-8', 'replace').strip()[:300]}"
            )
        import soundfile as sf

        x, sr = sf.read(str(dst), dtype="float32", always_2d=False)
    return _to_mono(np.asarray(x, dtype=np.float32)), sr


def load_audio(data: bytes) -> np.ndarray:
    """Bytes of any common audio file -> mono float32 @ 16 kHz, peak-normalised."""
    if not data:
        raise AudioError("empty upload")

    try:
        import soundfile as sf

        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
        x = _to_mono(np.asarray(x, dtype=np.float32))
    except Exception:  # noqa: BLE001 - libsndfile cannot read webm/opus containers
        x, sr = _decode_with_ffmpeg(data)

    x = _resample(x, sr)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < 1e-4:
        raise AudioError("the recording is silent - check your microphone")
    if peak > 0:
        x = x / peak * 0.95

    return trim_silence(x)


def trim_silence(x: np.ndarray, threshold_db: float = -45.0,
                 pad_ms: int = 60) -> np.ndarray:
    """Drop leading/trailing silence so speech-rate and duration stay meaningful."""
    if x.size == 0:
        return x
    win = TARGET_SR // 100  # 10 ms
    n = x.size // win
    if n < 2:
        return x
    frames = x[: n * win].reshape(n, win)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-12)
    voiced = np.flatnonzero(db > (db.max() + threshold_db))
    if voiced.size == 0:
        return x
    pad = pad_ms * TARGET_SR // 1000
    lo = max(0, int(voiced[0]) * win - pad)
    hi = min(x.size, (int(voiced[-1]) + 1) * win + pad)
    return x[lo:hi]


def to_wav_bytes(x: np.ndarray, sr: int = TARGET_SR) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()
