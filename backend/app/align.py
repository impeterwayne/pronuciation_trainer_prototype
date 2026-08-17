"""Two alignments, two different jobs.

1. `forced_align` -- CTC forced alignment of the *reference* phone sequence against
   the acoustic posteriors. Answers "how confidently does the audio support this
   exact phone, here?" -> a Goodness-of-Pronunciation score plus a time span per
   phone (which is also what lets the UI play back a single word the user said).

2. `edit_align` -- Needleman-Wunsch between the reference phones and what the
   recogniser actually heard. Answers "which phone did they say instead?" ->
   substitution / deletion / insertion diagnostics.

GOP alone cannot name the error; the edit alignment alone has no notion of degree.
The scorer combines them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .phones import substitution_cost

NEG = -1e30


# --------------------------------------------------------------- CTC forced alignment


@dataclass
class PhoneSpan:
    ref_index: int
    start_frame: int
    end_frame: int      # exclusive
    posterior: float    # mean P(phone | frame) over the span, 0..1


def forced_align(logp: np.ndarray, target_ids: list[int],
                 blank_id: int = 0) -> list[PhoneSpan] | None:
    """Viterbi-align `target_ids` to the CTC lattice `logp` ([T, vocab] log-softmax).

    Returns one span per target token, or None if the audio is too short to
    contain the sequence at all.
    """
    T = logp.shape[0]
    N = len(target_ids)
    if N == 0 or T < N:
        return None

    S = 2 * N + 1
    ext = np.full(S, blank_id, dtype=np.int64)
    ext[1::2] = np.asarray(target_ids, dtype=np.int64)

    # A jump of 2 is only legal into a non-blank state whose predecessor label differs.
    allow_skip = np.zeros(S, dtype=bool)
    allow_skip[2:] = (ext[2:] != blank_id) & (ext[2:] != ext[:-2])

    emit = logp[:, ext]                       # [T, S]
    alpha = np.full((T, S), NEG, dtype=np.float64)
    back = np.zeros((T, S), dtype=np.int8)    # how many states we came back from

    alpha[0, 0] = emit[0, 0]
    if S > 1:
        alpha[0, 1] = emit[0, 1]

    for t in range(1, T):
        prev = alpha[t - 1]
        stay = prev
        one = np.concatenate(([NEG], prev[:-1]))
        two = np.concatenate(([NEG, NEG], prev[:-2]))
        two = np.where(allow_skip, two, NEG)

        cand = np.stack((stay, one, two))     # [3, S]
        step = cand.argmax(axis=0)
        alpha[t] = cand[step, np.arange(S)] + emit[t]
        back[t] = step

    # Valid endings: last real token, or the trailing blank after it.
    s = S - 1 if alpha[T - 1, S - 1] >= alpha[T - 1, S - 2] else S - 2
    if alpha[T - 1, s] <= NEG / 2:
        return None

    path = np.zeros(T, dtype=np.int64)
    for t in range(T - 1, 0, -1):
        path[t] = s
        s -= int(back[t, s])
    path[0] = s

    probs = np.exp(logp)
    spans: list[PhoneSpan] = []
    for n in range(N):
        frames = np.flatnonzero(path == 2 * n + 1)
        if frames.size == 0:
            # Token was absorbed entirely by blanks -- no acoustic support at all.
            spans.append(PhoneSpan(n, -1, -1, 0.0))
            continue
        lo, hi = int(frames[0]), int(frames[-1]) + 1
        post = float(probs[frames, target_ids[n]].mean())
        spans.append(PhoneSpan(n, lo, hi, post))
    return spans


# ------------------------------------------------------------------- edit alignment


@dataclass
class EditOp:
    op: str                  # 'match' | 'sub' | 'del' | 'ins'
    ref_index: int | None
    hyp_index: int | None
    ref_phone: str | None
    hyp_phone: str | None
    similarity: float = 0.0


def edit_align(ref: list[str], hyp: list[str], gap_cost: float = 0.9) -> list[EditOp]:
    """Needleman-Wunsch with a phonetically weighted substitution cost.

    The weighting matters: /θ/ heard as /s/ should align as a substitution
    (a fixable contrast) rather than as a delete+insert pair, which would read
    as "you said a completely different word".
    """
    R, H = len(ref), len(hyp)
    d = np.zeros((R + 1, H + 1), dtype=np.float64)
    ptr = np.zeros((R + 1, H + 1), dtype=np.int8)  # 1=diag 2=up(del) 3=left(ins)

    d[:, 0] = np.arange(R + 1) * gap_cost
    d[0, :] = np.arange(H + 1) * gap_cost
    ptr[1:, 0] = 2
    ptr[0, 1:] = 3

    for i in range(1, R + 1):
        rp = ref[i - 1]
        for j in range(1, H + 1):
            sub = d[i - 1, j - 1] + substitution_cost(rp, hyp[j - 1])
            dele = d[i - 1, j] + gap_cost
            ins = d[i, j - 1] + gap_cost
            best = min(sub, dele, ins)
            d[i, j] = best
            ptr[i, j] = 1 if best == sub else (2 if best == dele else 3)

    ops: list[EditOp] = []
    i, j = R, H
    while i > 0 or j > 0:
        p = ptr[i, j]
        if p == 1:
            rp, hp = ref[i - 1], hyp[j - 1]
            sim = 1.0 - substitution_cost(rp, hp)
            ops.append(EditOp(
                "match" if rp == hp else "sub", i - 1, j - 1, rp, hp, sim))
            i, j = i - 1, j - 1
        elif p == 2:
            ops.append(EditOp("del", i - 1, None, ref[i - 1], None, 0.0))
            i -= 1
        else:
            ops.append(EditOp("ins", None, j - 1, None, hyp[j - 1], 0.0))
            j -= 1
    ops.reverse()
    return ops
