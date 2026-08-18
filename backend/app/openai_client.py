"""Optional OpenAI integration: LLM coaching.

Opt-in and additive. Without a key the rule-based `scoring._feedback` tips stand on
their own; with one, `coach()` hands the per-phone findings this app *already
measured* to a model that rewrites them as articulation advice. The LLM never hears
the audio and is never asked to judge pronunciation - diagnosis stays acoustic.

Reference audio is not OpenAI's job: espeak (`tts.py`) is the phonetic reference and
OmniVoice (`neural_tts.py`) is the natural-sounding one, both local.

The key is never persisted server-side. It arrives per request in the
`X-OpenAI-Key` header, or comes from the `OPENAI_API_KEY` environment variable.

Uses `urllib` rather than the `openai` SDK so this optional feature adds no
dependency to `requirements.txt`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .config import settings

TIMEOUT_S = 60


class OpenAIError(RuntimeError):
    """Anything that went wrong talking to OpenAI, already made human-readable."""


# --------------------------------------------------------------------------- key

def resolve_key(header_key: str | None) -> str | None:
    """Per-request header wins over the environment; blank strings count as unset."""
    key = (header_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    return key or None


def _request(path: str, key: str, payload: dict | None = None,
             *, timeout: int = TIMEOUT_S) -> dict:
    headers = {"Authorization": f"Bearer {key}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        settings.openai_base_url.rstrip("/") + path, data=data, headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise OpenAIError(_http_message(exc)) from None
    except urllib.error.URLError as exc:
        raise OpenAIError(f"could not reach OpenAI: {exc.reason}") from None

    return json.loads(body.decode("utf-8"))


def _http_message(exc: urllib.error.HTTPError) -> str:
    """Human-readable failure. Never echoes the key back, not even partially."""
    if exc.code == 401:
        return "OpenAI rejected the key (401) - check for a typo or a revoked key."
    if exc.code == 429:
        return "OpenAI rate limit or quota exhausted (429)."
    detail = exc.read().decode("utf-8", "replace")
    try:
        detail = json.loads(detail)["error"]["message"]
    except Exception:  # noqa: BLE001 - detail is best-effort
        detail = detail[:300]
    return f"OpenAI API error {exc.code}: {detail}"


def verify(key: str) -> dict:
    """Cheapest possible credential check: list models."""
    data = _request("/models", key, timeout=15)
    assert isinstance(data, dict)
    ids = {m.get("id") for m in data.get("data", [])}
    return {
        "ok": True,
        "chat_model": settings.openai_chat_model,
        "chat_model_available": settings.openai_chat_model in ids,
    }


# --------------------------------------------------------------------------- coach

_COACH_SYSTEM = (
    "You are a phonetics coach for English learners. You are given the output of an "
    "acoustic pronunciation scorer: the target phrase, its reference IPA, what a "
    "phoneme recogniser actually heard, and a per-phone verdict scored out of 100.\n"
    "The measurements are already correct. Do not re-judge them, do not invent errors "
    "that are not in the data, and do not comment on phones that are not listed.\n"
    "For each problem phone, say in plain language what the mouth should do "
    "differently - tongue position, lip shape, voicing, airflow - and name a "
    "contrasting word where it helps.\n"
    'Reply as a JSON object: {"tips": ["...", "..."]}. At most 4 tips, one or two '
    "sentences each, worst problem first. If nothing needed work, return a single "
    "short line of specific praise."
)

MAX_TIPS = 4


def _problem_digest(payload: dict, fair: int) -> dict:
    """The smallest faithful summary of an assessment - no audio, no prose."""
    words = []
    for w in payload.get("words", []):
        problems = []
        for p in w.get("phones", []):
            if p.get("status") == "good" and p.get("score", 0) >= fair:
                continue
            entry = {"phone": p.get("norm"), "status": p.get("status"),
                     "score": p.get("score")}
            if p.get("heard"):
                entry["heard_instead"] = p["heard"]
            problems.append(entry)
        if problems or w.get("score", 100) < fair:
            words.append({"word": w.get("text"), "ipa": w.get("ipa"),
                          "score": w.get("score"), "problems": problems})
    return {
        "overall": payload.get("overall"),
        "reference_ipa": payload.get("reference_ipa"),
        "recognized_ipa": payload.get("recognized_ipa"),
        "fair_threshold": fair,
        "words_needing_work": words,
    }


def coach(payload: dict, key: str, *, model: str | None = None,
          fair_threshold: int | None = None) -> list[str]:
    """Turn a scored assessment into coaching tips."""
    fair = settings.fair_threshold if fair_threshold is None else fair_threshold

    body = _request("/chat/completions", key, {
        "model": (model or settings.openai_chat_model).strip(),
        "messages": [
            {"role": "system", "content": _COACH_SYSTEM},
            {"role": "user",
             "content": json.dumps(_problem_digest(payload, fair), ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
    })
    assert isinstance(body, dict)

    try:
        content = body["choices"][0]["message"]["content"]
        tips = json.loads(content).get("tips", [])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise OpenAIError("unexpected response shape from the chat model") from exc

    return [str(t).strip() for t in tips if str(t).strip()][:MAX_TIPS]
