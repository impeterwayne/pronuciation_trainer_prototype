"""Neural 'ideal' audio from a local OmniVoice server.

`tts.py` (espeak-ng) is phonetically exact but unmistakably robotic - a formant
synthesiser with no recorded human speech in it anywhere. That is the right
*phonetic* reference and the wrong *imitation* model: a learner cannot copy rhythm,
vowel colour or intonation from it. OmniVoice fills that second role.

This talks to `omnivoice-server`, which wraps the Apache-2.0 `k2-fsa/OmniVoice`
model in an OpenAI-compatible `POST /v1/audio/speech`. It runs on localhost, so the
project keeps its "everything runs locally, no API keys" promise:

    pip install omnivoice-server        # torch must already be installed
    omnivoice-server                    # 127.0.0.1:8880, --device cuda if you have one

Nothing here is required. If the server is not running, `/api/tts` serves espeak and
the app behaves exactly as it did before.

Uses `urllib` rather than an SDK so this adds no dependency to `requirements.txt`.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import settings

TIMEOUT_S = 180  # CPU real-time factor is ~5x; a long sentence genuinely takes a while
PROBE_TIMEOUT_S = 1.5
PROBE_TTL_S = 15.0

# Voice presets omnivoice-server accepts when `instructions` is absent. Most overlap
# with the OpenAI names; cedar/marin/verse are OmniVoice's own.
VOICES = ["alloy", "ash", "ballad", "cedar", "coral", "echo", "fable",
          "marin", "nova", "onyx", "sage", "shimmer", "verse"]


class NeuralTTSUnavailable(RuntimeError):
    """The OmniVoice server is missing or refused the request, already readable."""


def _url(path: str) -> str:
    return settings.omnivoice_url.rstrip("/") + path


def _headers() -> dict[str, str]:
    # omnivoice-server is keyless by default; --api-key turns on bearer auth.
    h = {"Content-Type": "application/json"}
    if settings.omnivoice_api_key:
        h["Authorization"] = f"Bearer {settings.omnivoice_api_key}"
    return h


# --------------------------------------------------------------------------- probe

_probe: tuple[float, bool] = (0.0, False)


def available(force: bool = False) -> bool:
    """Is the server up? Cached briefly so the health pill cannot stall the UI."""
    global _probe
    now = time.monotonic()
    if not force and now - _probe[0] < PROBE_TTL_S:
        return _probe[1]

    try:
        # /health sits outside the /v1 prefix, so it hangs off the origin.
        origin = settings.omnivoice_url.rsplit("/v1", 1)[0].rstrip("/")
        req = urllib.request.Request(origin + "/health", headers=_headers())
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            ok = resp.status == 200
    except Exception:  # noqa: BLE001 - any failure means "not usable right now"
        ok = False

    _probe = (now, ok)
    return ok


# --------------------------------------------------------------------------- cache

def _cache_path(digest: str) -> Path:
    d = settings.cache_dir / "tts-omnivoice"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{digest}.wav"


# --------------------------------------------------------------------------- speech

def speech(text: str, *, voice: str | None = None, speed: str = "normal",
           description: str | None = None) -> bytes:
    """Render `text` to WAV bytes. Cached on disk - CPU synthesis is slow.

    `description` is OmniVoice's voice *design* string: comma-separated attributes
    like "female, british accent, young adult". It maps to the server's
    `instructions` field, which outranks the `voice` preset when both are sent.
    Note this is not free prose: OmniVoice reads attributes, not delivery notes,
    which is why slow speech is the numeric `speed` below rather than an
    instruction to speak slowly.
    """
    voice = (voice or settings.omnivoice_voice).strip()
    description = (description if description is not None else settings.omnivoice_description).strip()
    rate = settings.omnivoice_slow_speed if speed == "slow" else 1.0

    digest = hashlib.sha1(
        f"{text}|{voice}|{description}|{rate}|{settings.omnivoice_model}".encode("utf-8")
    ).hexdigest()
    cached = _cache_path(digest)
    if cached.exists():
        return cached.read_bytes()

    payload: dict = {
        "model": settings.omnivoice_model,
        "input": text,
        "response_format": "wav",
        "speed": rate,
    }
    if description:
        payload["instructions"] = description
    else:
        payload["voice"] = voice

    req = urllib.request.Request(
        _url("/audio/speech"),
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail") or json.loads(detail)["error"]["message"]
        except Exception:  # noqa: BLE001 - detail is best-effort
            detail = detail[:300]
        raise NeuralTTSUnavailable(f"OmniVoice error {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise NeuralTTSUnavailable(
            f"no OmniVoice server at {settings.omnivoice_url} ({exc.reason}). "
            "Start it with `omnivoice-server`, or set PT_OMNIVOICE_URL."
        ) from None
    except TimeoutError:
        raise NeuralTTSUnavailable(
            f"OmniVoice timed out after {TIMEOUT_S}s - CPU synthesis of a long "
            "phrase is slow; try --device cuda or a shorter phrase."
        ) from None

    if not audio.startswith(b"RIFF"):
        raise NeuralTTSUnavailable("OmniVoice returned audio that is not WAV")

    cached.write_bytes(audio)
    return audio


def voices() -> list[str]:
    """Preset names, from the server when it answers, else the documented list."""
    try:
        req = urllib.request.Request(_url("/voices"), headers=_headers())
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - the static list is a fine answer
        return VOICES

    # The endpoint's exact shape is undocumented; accept the obvious candidates.
    if isinstance(data, dict):
        for field in ("voices", "data"):
            if isinstance(data.get(field), list):
                data = data[field]
                break
    if not isinstance(data, list):
        return VOICES

    names = [v if isinstance(v, str) else (v or {}).get("id") or (v or {}).get("name")
             for v in data]
    return [n for n in names if isinstance(n, str)] or VOICES
