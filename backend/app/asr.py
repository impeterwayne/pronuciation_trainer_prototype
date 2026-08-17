"""Phoneme-level ASR: the user's audio -> IPA phones + CTC posteriors.

Model: facebook/wav2vec2-lv-60-espeak-cv-ft
It is fine-tuned on espeak-phonemized CommonVoice, so its output alphabet *is*
espeak IPA -- the same alphabet phonemizer produces on the reference side.

We deliberately load the feature extractor + raw vocab.json rather than
Wav2Vec2Processor: the phoneme tokenizer in that checkpoint is brittle across
transformers versions, and greedy CTC decoding is four lines anyway.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass

import numpy as np

from .config import settings

_lock = threading.Lock()
_state: dict = {}


class AsrUnavailable(RuntimeError):
    pass


@dataclass
class AsrResult:
    logp: np.ndarray          # [T, vocab] log-softmax over CTC labels
    phones: list[str]         # greedy-decoded phone sequence
    frame_ms: float           # ms of audio per output frame
    duration_s: float


def _load():
    """Lazily build the model singleton. First call downloads ~1.2 GB."""
    if _state:
        return _state
    with _lock:
        if _state:
            return _state
        try:
            import torch
            from huggingface_hub import hf_hub_download
            from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC
        except ImportError as exc:
            raise AsrUnavailable(
                f"missing dependency for phoneme ASR: {exc}. "
                "pip install torch transformers huggingface_hub"
            ) from exc

        model_id = settings.model_id
        extractor = Wav2Vec2FeatureExtractor.from_pretrained(model_id)
        model = Wav2Vec2ForCTC.from_pretrained(model_id)
        model.eval()
        model.to(settings.device)

        with open(hf_hub_download(model_id, "vocab.json"), encoding="utf-8") as fh:
            vocab: dict[str, int] = json.load(fh)

        id_to_phone = {v: k for k, v in vocab.items()}
        blank_id = model.config.pad_token_id
        if blank_id is None:
            blank_id = vocab.get("<pad>", 0)

        specials = {"<pad>", "<s>", "</s>", "<unk>", "|"}

        _state.update(
            torch=torch,
            extractor=extractor,
            model=model,
            vocab=vocab,
            id_to_phone=id_to_phone,
            blank_id=blank_id,
            specials=specials,
        )
        return _state


def is_loaded() -> bool:
    return bool(_state)


def phone_to_id(phone: str) -> int | None:
    return _load()["vocab"].get(phone)


def vocab_phones() -> set[str]:
    st = _load()
    return {p for p in st["vocab"] if p not in st["specials"]}


def allowed_mask(phones: set[str] | frozenset[str]) -> np.ndarray:
    """Boolean vocab mask keeping `phones` (plus blank). Cached per phone set."""
    st = _load()
    key = frozenset(phones)
    cache = st.setdefault("_mask_cache", {})
    if key in cache:
        return cache[key]

    vocab = st["vocab"]
    mask = np.zeros(len(vocab), dtype=bool)
    mask[st["blank_id"]] = True
    for p in key:
        tid = vocab.get(p)
        if tid is not None:
            mask[tid] = True
    cache[key] = mask
    return mask


def recognize(audio: np.ndarray, sample_rate: int = 16_000,
              allowed: set[str] | frozenset[str] | None = None) -> AsrResult:
    """Run the phoneme recogniser over mono float32 audio in [-1, 1].

    `allowed` restricts decoding to a phone inventory. The checkpoint is
    multilingual and zero-shot, so on accented or noisy input it will otherwise
    wander into other languages' phones - Mandarin tone-marked vowels turning up in
    English audio is the common failure. Masking before the softmax also
    renormalises the posteriors over the plausible set, which is what the GOP
    scores are read off.
    """
    st = _load()
    torch = st["torch"]

    if audio.ndim != 1:
        audio = audio.reshape(-1)
    if audio.size < sample_rate // 10:
        raise ValueError("recording is too short (<0.1 s)")

    inputs = st["extractor"](
        audio, sampling_rate=sample_rate, return_tensors="pt", padding=False
    )
    inputs = {k: v.to(settings.device) for k, v in inputs.items()}

    with torch.inference_mode():
        logits = st["model"](**inputs).logits[0].float()   # [T, vocab]
        if allowed:
            keep = torch.from_numpy(allowed_mask(allowed)).to(logits.device)
            logits = logits.masked_fill(~keep, float("-inf"))
        logp = torch.log_softmax(logits, dim=-1).cpu().numpy()
    # Masked entries come back as -inf; keep them finite so the alignment DP
    # stays in ordinary float arithmetic.
    logp = np.nan_to_num(logp, neginf=-1e30)

    ids = logp.argmax(axis=-1)
    phones = _greedy_decode(ids, st["blank_id"], st["id_to_phone"], st["specials"])

    duration_s = audio.size / sample_rate
    frame_ms = duration_s * 1000.0 / max(logp.shape[0], 1)
    return AsrResult(logp=logp, phones=phones, frame_ms=frame_ms, duration_s=duration_s)


def _greedy_decode(ids: np.ndarray, blank_id: int, id_to_phone: dict,
                   specials: set[str]) -> list[str]:
    out: list[str] = []
    prev = -1
    for i in ids.tolist():
        if i != prev and i != blank_id:
            tok = id_to_phone.get(i, "")
            if tok and tok not in specials:
                out.append(tok)
        prev = i
    return out
