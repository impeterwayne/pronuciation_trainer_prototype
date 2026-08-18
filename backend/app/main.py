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

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import asr, lessons, neural_tts, openai_client, tts
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
        "omnivoice": {
            "url": settings.omnivoice_url,
            "up": neural_tts.available(),
            "model": settings.omnivoice_model,
            "voices": neural_tts.VOICES,
            "default_voice": settings.omnivoice_voice,
            "default_description": settings.omnivoice_description,
        },
        "openai": {
            # Only ever reports *whether* a server-side key exists, never its value.
            "env_key": openai_client.resolve_key(None) is not None,
            "chat_model": settings.openai_chat_model,
        },
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
    engine: str = Query("auto", pattern="^(auto|espeak|omnivoice)$"),
    voice: str | None = None,
    description: str | None = Query(None, max_length=200),
) -> Response:
    """The 'ideal' audio for the target phrase, at full or half pace.

    Two engines, both local. `espeak` is the always-available formant synthesiser:
    phonetically exact and instant, but unmistakably robotic. `omnivoice` is the
    neural voice a learner can actually imitate for rhythm and vowel colour.
    `auto` (the default) uses OmniVoice when its server answers and falls back to
    espeak otherwise - including mid-request, so the button never dies.

    `voice` is interpreted by whichever engine runs: an espeak voice name
    ("en-us", "en-gb") or an OmniVoice preset ("nova", "onyx", ...). `description`
    is OmniVoice-only voice design ("female, british accent, young adult").
    """
    # `auto` gates on the cached /health probe first: a URL pointing at a host that
    # blackholes would otherwise burn the full synthesis timeout before falling back.
    # An explicit `omnivoice` always tries, so the caller sees the real error.
    if engine == "omnivoice" or (engine == "auto" and neural_tts.available()):
        try:
            wav = neural_tts.speech(text, voice=voice, speed=speed,
                                    description=description)
            return Response(content=wav, media_type="audio/wav", headers={
                "Cache-Control": "public, max-age=86400",
                "X-TTS-Engine": f"omnivoice:{settings.omnivoice_model}",
            })
        except neural_tts.NeuralTTSUnavailable as exc:
            if engine == "omnivoice":
                raise HTTPException(503, str(exc)) from exc
            # auto: degrade to espeak rather than leaving the learner with silence
            print(f"[tts] OmniVoice unavailable, falling back to espeak: {exc}")
            voice = None  # an OmniVoice preset name means nothing to espeak

    rate = settings.tts_speed_slow if speed == "slow" else settings.tts_speed_normal
    gap = 8 if speed == "slow" else 0
    try:
        wav = tts.synthesize(text, voice=voice, speed=rate, word_gap=gap)
    except tts.TTSUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=86400", "X-TTS-Engine": "espeak"},
    )


@app.get("/api/tts/voices")
def api_tts_voices() -> dict:
    """OmniVoice presets, asked of the server when it is up."""
    return {"up": neural_tts.available(), "voices": neural_tts.voices()}


@app.post("/api/openai/verify")
def api_openai_verify(x_openai_key: str | None = Header(None)) -> dict:
    """Check a key before the user commits to it. Nothing is stored server-side."""
    key = openai_client.resolve_key(x_openai_key)
    if not key:
        raise HTTPException(400, "no key supplied")
    try:
        return openai_client.verify(key)
    except openai_client.OpenAIError as exc:
        raise HTTPException(502, str(exc)) from exc


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
    coach: bool = Form(True),
    x_openai_key: str | None = Header(None),
) -> dict:
    """Score a recording against a target phrase.

    Scoring itself is entirely local. If a key is present and `coach` is on, the
    *already measured* per-phone verdicts are additionally sent to an LLM, which
    rewrites them as articulation advice under `coach_tips`. The rule-based
    `feedback` list is always present regardless, so the UI has something to show.
    """
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

    key = openai_client.resolve_key(x_openai_key) if coach else None
    if key:
        try:
            tips = await run_in_threadpool(openai_client.coach, payload, key)
            if tips:
                payload["coach_tips"] = tips
                payload["coach_model"] = settings.openai_chat_model
        except openai_client.OpenAIError as exc:
            # A coaching failure must never sink an otherwise valid assessment.
            payload["coach_error"] = str(exc)

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
