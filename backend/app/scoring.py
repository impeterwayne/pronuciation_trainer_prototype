"""Turn (reference phones, acoustic posteriors, edit alignment) into scores.

Design notes
------------
* A phone's score has two independent inputs: *acoustic support* (GOP, continuous)
  and *identity* (did the recogniser hear this phone, a confusable one, or nothing).
  Multiplying them means a phone can only score well if the audio supports it AND
  it was heard as the right sound.
* A phone the recogniser matched never drops below ~50: it was intelligible, just weak.
  A substitution is capped well under the "fair" threshold, because intelligible-but-wrong
  is exactly what a pronunciation trainer must flag.
* Every constant below is a tuning knob and lives here, not scattered through the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .align import EditOp, PhoneSpan, edit_align, forced_align
from .asr import AsrResult, phone_to_id
from .config import settings
from .g2p import Reference
from .phones import hint_for, is_vowel, normalize_phone

# --- tuning ---------------------------------------------------------------------
GOP_FLOOR, GOP_CEIL = 0.10, 0.85   # sqrt-posterior mapped from this range onto 0..1
MATCH_BASE = 0.50                  # a correctly-heard phone starts at 50%
SUB_BASE, SUB_SIM_GAIN = 0.25, 0.35
DEL_FACTOR = 0.20
INSERTION_PENALTY = 4.0            # points per extra sound inside a word, capped
INSERTION_CAP = 12.0
NEUTRAL_GOP = 0.62                 # used when forced alignment is unavailable
COMFORTABLE_RATE = (8.0, 14.0)     # phones per second
LONG_PAUSE_MS = 300.0
W_ACCURACY, W_COMPLETENESS, W_FLUENCY = 0.75, 0.10, 0.15
ATTEMPTED_WORD_SCORE = 30          # below this, the word counts as not attempted

# A word's score is *not* the plain mean of its phones. In a minimal pair the whole
# word turns on one phone: "sink" for "think" is three perfect phones and one ruined
# one, and a mean would report ~74 -- a pass. Blending in the worst phone keeps that
# honest while barely touching words that are uniformly good.
WORD_MEAN_WEIGHT = 0.6


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def gop_quality(posterior: float) -> float:
    """Map a mean CTC posterior onto a 0..1 quality value."""
    return _clamp((np.sqrt(max(posterior, 0.0)) - GOP_FLOOR) / (GOP_CEIL - GOP_FLOOR))


@dataclass
class PhoneScore:
    index: int
    phone: str            # as displayed, stress marks intact
    norm: str
    status: str           # 'good' | 'sub' | 'missing'
    score: int
    heard: str | None     # what the recogniser heard instead
    start_ms: float | None
    end_ms: float | None
    posterior: float
    hint: str | None = None


@dataclass
class WordScore:
    index: int
    text: str
    ipa: str
    score: int
    phones: list[PhoneScore] = field(default_factory=list)
    extra_sounds: list[str] = field(default_factory=list)
    start_ms: float | None = None
    end_ms: float | None = None

    @property
    def attempted(self) -> bool:
        return self.score >= ATTEMPTED_WORD_SCORE


@dataclass
class Assessment:
    text: str
    reference_ipa: str
    recognized_ipa: str
    overall: int
    accuracy: int
    completeness: int
    fluency: int
    words: list[WordScore]
    duration_s: float
    speech_rate: float
    feedback: list[str] = field(default_factory=list)
    forced_aligned: bool = True


# --------------------------------------------------------------------------- core


def _build_targets(ref: Reference) -> tuple[list[int], list[int]]:
    """Map reference phones to model vocab ids, skipping anything out of vocabulary.

    Returns (target_ids, ref_index_per_target).
    """
    ids: list[int] = []
    ref_idx: list[int] = []
    for i, p in enumerate(ref.norm):
        tid = phone_to_id(p)
        if tid is None:
            # try without the length mark, e.g. 'ɑː' -> 'ɑ'
            tid = phone_to_id(p.replace("ː", ""))
        if tid is not None:
            ids.append(tid)
            ref_idx.append(i)
    return ids, ref_idx


def _status_by_ref(ops: list[EditOp], n_ref: int) -> tuple[list[EditOp | None], list[list[str]]]:
    """Per reference index: the op that consumed it, plus insertions sitting after it."""
    by_ref: list[EditOp | None] = [None] * n_ref
    inserts: list[list[str]] = [[] for _ in range(n_ref + 1)]
    cursor = 0
    for op in ops:
        if op.op in ("match", "sub", "del"):
            by_ref[op.ref_index] = op
            cursor = op.ref_index + 1
        elif op.op == "ins":
            inserts[min(cursor, n_ref)].append(op.hyp_phone or "")
    return by_ref, inserts


def _fluency(ref: Reference, words: list[WordScore], duration_s: float) -> tuple[int, float]:
    n_phones = len(ref.norm)
    rate = n_phones / duration_s if duration_s > 0 else 0.0

    lo, hi = COMFORTABLE_RATE
    if rate <= 0:
        rate_score = 0.0
    elif lo <= rate <= hi:
        rate_score = 100.0
    elif rate < lo:
        rate_score = 100.0 * _clamp(rate / lo) ** 0.7
    else:
        rate_score = 100.0 * _clamp(1.0 - (rate - hi) / hi)

    timed = [w for w in words if w.start_ms is not None and w.end_ms is not None]
    pause_ms = 0.0
    for a, b in zip(timed, timed[1:]):
        gap = (b.start_ms or 0) - (a.end_ms or 0)
        if gap > LONG_PAUSE_MS:
            pause_ms += gap - LONG_PAUSE_MS
    pause_penalty = min(35.0, 100.0 * pause_ms / (duration_s * 1000.0)) if duration_s else 0.0

    return int(round(_clamp(rate_score - pause_penalty, 0, 100))), rate


def assess(ref: Reference, asr: AsrResult) -> Assessment:
    n_ref = len(ref.norm)
    if n_ref == 0:
        raise ValueError("reference text produced no phonemes")

    hyp = [normalize_phone(p) for p in asr.phones]
    ops = edit_align(ref.norm, hyp)
    by_ref, inserts = _status_by_ref(ops, n_ref)

    # --- acoustic support per reference phone
    target_ids, target_ref_idx = _build_targets(ref)
    spans = forced_align(asr.logp, target_ids) if target_ids else None
    forced_ok = spans is not None

    posterior = [0.0] * n_ref
    start_ms: list[float | None] = [None] * n_ref
    end_ms: list[float | None] = [None] * n_ref
    quality = [NEUTRAL_GOP] * n_ref

    if forced_ok:
        for span, ri in zip(spans, target_ref_idx):
            posterior[ri] = span.posterior
            quality[ri] = gop_quality(span.posterior)
            if span.start_frame >= 0:
                start_ms[ri] = span.start_frame * asr.frame_ms
                end_ms[ri] = span.end_frame * asr.frame_ms

    # --- per-phone scores
    phone_scores: list[PhoneScore] = []
    for i in range(n_ref):
        op = by_ref[i]
        q = quality[i]
        if op is None or op.op == "del":
            status, heard = "missing", None
            value = 100.0 * q * DEL_FACTOR
        elif op.op == "match":
            status, heard = "good", op.hyp_phone
            value = 100.0 * (MATCH_BASE + (1.0 - MATCH_BASE) * q)
        else:
            status, heard = "sub", op.hyp_phone
            value = 100.0 * q * (SUB_BASE + SUB_SIM_GAIN * op.similarity)

        score = int(round(_clamp(value, 0, 100)))
        phone_scores.append(PhoneScore(
            index=i,
            phone=ref.phones[i],
            norm=ref.norm[i],
            status=status,
            score=score,
            heard=heard,
            start_ms=start_ms[i],
            end_ms=end_ms[i],
            posterior=round(posterior[i], 4),
            hint=hint_for(ref.norm[i]) if score < settings.fair_threshold else None,
        ))

    # --- roll up to words
    words: list[WordScore] = []
    offset = 0
    for wi, rw in enumerate(ref.words):
        n = len(rw.phones)
        ps = [phone_scores[k] for k in range(offset, offset + n)]
        # A word owns the insertions that fall inside it or right after its last
        # phone; leading insertions before the very first phone go to word 0.
        extra = list(inserts[0]) if wi == 0 else []
        extra += [x for k in range(offset + 1, offset + n + 1) for x in inserts[k]]

        if ps:
            vals = [p.score for p in ps]
            base = (WORD_MEAN_WEIGHT * float(np.mean(vals))
                    + (1.0 - WORD_MEAN_WEIGHT) * float(min(vals)))
        else:
            base = 0.0
        base -= min(INSERTION_CAP, INSERTION_PENALTY * len(extra))

        starts = [p.start_ms for p in ps if p.start_ms is not None]
        ends = [p.end_ms for p in ps if p.end_ms is not None]
        words.append(WordScore(
            index=wi,
            text=rw.text,
            ipa=rw.ipa,
            score=int(round(_clamp(base, 0, 100))),
            phones=ps,
            extra_sounds=extra,
            start_ms=min(starts) if starts else None,
            end_ms=max(ends) if ends else None,
        ))
        offset += n

    # --- aggregates
    weights = [max(len(w.phones), 1) for w in words]
    accuracy = int(round(float(np.average([w.score for w in words], weights=weights))))
    completeness = int(round(100.0 * sum(w.attempted for w in words) / max(len(words), 1)))
    fluency, rate = _fluency(ref, words, asr.duration_s)
    if len(words) > 1:
        overall = (W_ACCURACY * accuracy + W_COMPLETENESS * completeness
                   + W_FLUENCY * fluency)
    else:
        # Rhythm and pausing are undefined for a single word; folding a
        # speech-rate guess into the score would just add noise.
        scale = W_ACCURACY + W_FLUENCY
        overall = scale * accuracy + W_COMPLETENESS * completeness
    overall = int(round(overall))

    return Assessment(
        text=ref.text,
        reference_ipa=ref.ipa,
        recognized_ipa=" ".join(asr.phones),
        overall=overall,
        accuracy=accuracy,
        completeness=completeness,
        fluency=fluency,
        words=words,
        duration_s=round(asr.duration_s, 2),
        speech_rate=round(rate, 1),
        feedback=_feedback(words, completeness, fluency),
        forced_aligned=forced_ok,
    )


def _feedback(words: list[WordScore], completeness: int, fluency: int) -> list[str]:
    msgs: list[str] = []

    owner = {p.index: w.text for w in words for p in w.phones}
    worst = sorted(
        (p for w in words for p in w.phones if p.score < settings.fair_threshold),
        key=lambda p: p.score,
    )[:3]
    for p in worst:
        word = owner[p.index]
        if p.status == "missing":
            msgs.append(f"You dropped /{p.norm}/ in “{word}”. {p.hint or ''}".strip())
        elif p.heard:
            msgs.append(
                f"In “{word}” you said /{p.heard}/ where /{p.norm}/ belongs. "
                f"{p.hint or ''}".strip()
            )
        else:
            msgs.append(f"/{p.norm}/ in “{word}” was unclear. {p.hint or ''}".strip())

    if completeness < 100:
        missed = [w.text for w in words if not w.attempted]
        if missed:
            msgs.append("Not detected at all: " + ", ".join(missed) + ".")
    if fluency < 60:
        msgs.append("Work on pacing - keep an even rhythm and avoid long pauses mid-phrase.")
    if not msgs:
        msgs.append("Clean pronunciation across every phoneme. Try a longer sentence.")
    return msgs


def vowel_consonant_breakdown(words: list[WordScore]) -> dict[str, int]:
    """Aggregate accuracy split by vowels vs consonants - useful progress signal."""
    vs = [p.score for w in words for p in w.phones if is_vowel(p.norm)]
    cs = [p.score for w in words for p in w.phones if not is_vowel(p.norm)]
    return {
        "vowels": int(round(float(np.mean(vs)))) if vs else 0,
        "consonants": int(round(float(np.mean(cs)))) if cs else 0,
    }
