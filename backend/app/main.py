"""FastAPI surface for the pronunciation trainer."""

from __future__ import annotations

import json
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import asr, lessons, tts
from .audio import AudioError, load_audio, to_wav_bytes
from .config import find_espeak_exe, find_espeak_library, settings
from .g2p import G2PUnavailable, en_inventory, phonemize
from .scoring import assess, vowel_consonant_breakdown

@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.eager_load:
        try:
            asr._load()  # noqa: SLF001 - deliberate warm-up so the first request is fast
        except Exception as exc:  # noqa: BLE001
            print(f"[startup] ASR warm-up failed: {exc}")
    yield


app = FastAPI(
    title="Pronunciation Trainer API",
    version="1.0.0",
    description="espeak-ng + phonemizer for the reference, wav2vec2 phoneme CTC for the learner.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_TEXT_CHARS = 300
RECORDING_TTL_S = 30 * 60
RECORDING_CACHE_SIZE = 48

_recordings: "OrderedDict[str, tuple[float, bytes]]" = OrderedDict()
_rec_lock = Lock()


def _store_recording(wav: bytes) -> str:
    rec_id = uuid.uuid4().hex
    now = time.time()
    with _rec_lock:
        _recordings[rec_id] = (now, wav)
        while len(_recordings) > RECORDING_CACHE_SIZE:
            _recordings.popitem(last=False)
        for key in [k for k, (ts, _) in _recordings.items() if now - ts > RECORDING_TTL_S]:
            _recordings.pop(key, None)
    return rec_id


# --------------------------------------------------------------------------- models


class PhonemizeRequest(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_CHARS)
    lang: str | None = None


# --------------------------------------------------------------------------- routes


@app.get("/api/health")
def health() -> dict:
    lib, exe = find_espeak_library(), find_espeak_exe()
    return {
        "status": "ok" if lib and exe else "degraded",
        "espeak_library": str(lib) if lib else None,
        "espeak_binary": str(exe) if exe else None,
        "asr_model": settings.model_id,
        "asr_loaded": asr.is_loaded(),
        "lang": settings.lang,
        "device": settings.device,
        "thresholds": {"good": settings.good_threshold, "fair": settings.fair_threshold},
    }


@app.post("/api/phonemize")
def api_phonemize(req: PhonemizeRequest) -> dict:
    """Reference IPA for a piece of text - no audio involved."""
    try:
        ref = phonemize(req.text, req.lang)
    except G2PUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if not ref.words:
        raise HTTPException(400, "no pronounceable words in text")
    return {
        "text": ref.text,
        "ipa": ref.ipa,
        "words": [
            {"text": w.text, "ipa": w.ipa, "phones": w.phones, "norm": w.norm}
            for w in ref.words
        ],
    }


@app.get("/api/tts")
def api_tts(
    text: str = Query(..., max_length=MAX_TEXT_CHARS),
    speed: str = Query("normal", pattern="^(normal|slow)$"),
    voice: str | None = None,
) -> Response:
    """The 'ideal' audio: espeak-ng speaking the target, at full or half pace."""
    rate = settings.tts_speed_slow if speed == "slow" else settings.tts_speed_normal
    gap = 8 if speed == "slow" else 0
    try:
        wav = tts.synthesize(text, voice=voice, speed=rate, word_gap=gap)
    except tts.TTSUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/recording/{rec_id}")
def api_recording(rec_id: str) -> Response:
    """The learner's own audio, exactly as scored (mono 16 kHz, silence trimmed).

    The frontend plays word-level slices out of *this* file, so it must be the
    normalised copy - word timings come from alignment against these samples.
    """
    with _rec_lock:
        entry = _recordings.get(rec_id)
    if entry is None:
        raise HTTPException(404, "recording expired")
    return Response(content=entry[1], media_type="audio/wav",
                    headers={"Accept-Ranges": "bytes"})


@app.post("/api/assess")
async def api_assess(
    audio: UploadFile = File(...),
    text: str = Form(...),
    lang: str | None = Form(None),
) -> dict:
    """Score a recording against a target phrase."""
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(400, f"text longer than {MAX_TEXT_CHARS} characters")

    data = await audio.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "recording too large (max 12 MB)")

    try:
        ref = phonemize(text, lang)
    except G2PUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if not ref.words:
        raise HTTPException(400, "no pronounceable words in text")

    try:
        samples = load_audio(data)
    except AudioError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Constrain decoding to the target language's phones plus whatever this
    # particular phrase needs, so the multilingual model cannot wander off.
    allowed = en_inventory(lang) | set(ref.norm)

    try:
        result = asr.recognize(samples, settings.sample_rate, allowed=allowed)
    except asr.AsrUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    assessment = assess(ref, result)
    payload = asdict(assessment)
    payload["breakdown"] = vowel_consonant_breakdown(assessment.words)
    payload["recording_id"] = _store_recording(to_wav_bytes(samples))
    payload["thresholds"] = {
        "good": settings.good_threshold,
        "fair": settings.fair_threshold,
    }
    return payload


@app.get("/api/lessons")
def api_lessons() -> dict:
    return {"lessons": lessons.all_lessons()}


@app.get("/api/lessons/{lesson_id}")
def api_lesson(lesson_id: str, with_ipa: bool = True) -> dict:
    lesson = lessons.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(404, "unknown lesson")
    out = dict(lesson)
    if with_ipa:
        ipa: dict[str, str] = {}
        targets = list(lesson["items"]) + list(lesson["sentences"])
        targets += [w for pair in lesson["minimal_pairs"] for w in pair]
        for t in dict.fromkeys(targets):
            try:
                ipa[t] = phonemize(t).ipa
            except G2PUnavailable:
                break
        out["ipa"] = ipa
    return out


SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


@app.get("/api/samples")
def api_samples() -> dict:
    """Return all sample test audio files and metadata."""
    manifest_path = SAMPLES_DIR / "manifest.json"
    if not manifest_path.exists():
        return {"samples": []}
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"samples": data}
    except Exception as exc:
        raise HTTPException(500, f"could not load sample manifest: {exc}") from exc


@app.get("/api/samples/audio/{sample_path:path}")
def api_sample_audio(sample_path: str) -> FileResponse:
    """Serve a sample audio WAV file for preview or testing."""
    target_file = (SAMPLES_DIR / sample_path).resolve()
    # Path traversal protection
    if not str(target_file).startswith(str(SAMPLES_DIR.resolve())) or not target_file.is_file():
        raise HTTPException(404, "sample audio file not found")
    return FileResponse(target_file, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


# --------------------------------------------------------------------------- static

if SAMPLES_DIR.is_dir():
    app.mount("/samples", StaticFiles(directory=str(SAMPLES_DIR)), name="samples")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
