"""Deterministic tests for the parts of the pipeline this project actually owns.

`selftest.py` exercises the whole stack but has to feed it synthesised audio, which
makes it a smoke test with a soft pass bar. The alignment and scoring logic deserves
a hard gate, so here the acoustic model is replaced by hand-built CTC posteriors:
no audio, no download, no espeak, fully deterministic.

Run:  python tools/test_scoring.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.align import edit_align, forced_align  # noqa: E402
from app.phones import phone_similarity, substitution_cost  # noqa: E402
from app.scoring import gop_quality  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}"
          + (f"   {detail}" if detail else ""))
    if not condition:
        FAILURES.append(name)


# --------------------------------------------------------------------------- fixtures


def make_logp(frames: list[int], vocab_size: int = 6, blank: int = 0,
              confidence: float = 0.9) -> np.ndarray:
    """CTC log-posteriors that put `confidence` on the given token at each frame."""
    T = len(frames)
    probs = np.full((T, vocab_size), (1.0 - confidence) / (vocab_size - 1))
    probs[np.arange(T), frames] = confidence
    return np.log(probs)


# --------------------------------------------------------------------------- tests


def test_forced_align_recovers_spans() -> None:
    print("\nforced alignment")
    # tokens 1,2,3 spoken over frames, separated by blanks
    frames = [0, 1, 1, 1, 0, 2, 2, 0, 3, 3, 3, 3, 0]
    spans = forced_align(make_logp(frames), [1, 2, 3], blank_id=0)

    check("returns one span per target", spans is not None and len(spans) == 3)
    assert spans is not None
    check("span 1 covers frames 1-4", (spans[0].start_frame, spans[0].end_frame) == (1, 4),
          f"got {(spans[0].start_frame, spans[0].end_frame)}")
    check("span 2 covers frames 5-7", (spans[1].start_frame, spans[1].end_frame) == (5, 7),
          f"got {(spans[1].start_frame, spans[1].end_frame)}")
    check("span 3 covers frames 8-12", (spans[2].start_frame, spans[2].end_frame) == (8, 12),
          f"got {(spans[2].start_frame, spans[2].end_frame)}")
    check("posteriors are high for well-supported phones",
          all(s.posterior > 0.8 for s in spans),
          f"got {[round(s.posterior, 2) for s in spans]}")

    # Spans must stay in order and never overlap - a broken backtrace shows up here.
    ordered = all(spans[i].end_frame <= spans[i + 1].start_frame for i in range(2))
    check("spans are ordered and disjoint", ordered)


def test_forced_align_low_confidence() -> None:
    frames = [0, 1, 1, 0, 2, 2, 0]
    strong = forced_align(make_logp(frames, confidence=0.95), [1, 2])
    weak = forced_align(make_logp(frames, confidence=0.30), [1, 2])
    assert strong and weak
    check("weak audio yields lower posteriors than strong",
          weak[0].posterior < strong[0].posterior,
          f"{weak[0].posterior:.2f} < {strong[0].posterior:.2f}")


def test_forced_align_too_short() -> None:
    # Two frames cannot contain five phones.
    check("returns None when audio is shorter than the phone sequence",
          forced_align(make_logp([0, 1]), [1, 2, 3, 4, 5]) is None)


def test_edit_align_substitution() -> None:
    print("\nedit alignment")
    # /θɪŋk/ heard as /sɪŋk/ - one substitution, not a delete+insert pair.
    ops = edit_align(["θ", "ɪ", "ŋ", "k"], ["s", "ɪ", "ŋ", "k"])
    kinds = [o.op for o in ops]
    check("θ->s aligns as a single substitution", kinds == ["sub", "match", "match", "match"],
          str(kinds))
    check("substitution records what was heard", ops[0].hyp_phone == "s")


def test_edit_align_deletion_and_insertion() -> None:
    ops = edit_align(["s", "t", "ɹ", "iː", "t"], ["s", "t", "ɹ", "iː"])
    check("dropped final consonant is a deletion",
          [o.op for o in ops][-1] == "del")

    ops = edit_align(["s", "t"], ["s", "ə", "t"])   # epenthetic vowel
    check("inserted vowel is an insertion",
          any(o.op == "ins" and o.hyp_phone == "ə" for o in ops))


def test_similarity_ordering() -> None:
    print("\nphonetic similarity")
    check("identical phones score 1.0", phone_similarity("s", "s") == 1.0)
    check("vowel length difference beats an unrelated swap",
          phone_similarity("iː", "i") > phone_similarity("iː", "k"))
    check("known L2 confusion beats an unrelated swap",
          phone_similarity("θ", "s") > phone_similarity("θ", "k"),
          f"{phone_similarity('θ', 's')} > {phone_similarity('θ', 'k')}")
    check("vowel/consonant swap is the worst case",
          phone_similarity("iː", "k") <= 0.2)
    check("substitution_cost is the complement of similarity",
          abs(substitution_cost("θ", "s") + phone_similarity("θ", "s") - 1.0) < 1e-9)


def test_gop_curve() -> None:
    print("\nGOP curve")
    check("is monotonic", all(gop_quality(p) <= gop_quality(p + 0.05)
                              for p in np.arange(0.0, 0.9, 0.05)))
    check("bottoms out at 0 for no acoustic support", gop_quality(0.0) == 0.0)
    check("saturates at 1 for strong support", gop_quality(0.95) == 1.0)
    check("a mediocre posterior lands mid-range", 0.3 < gop_quality(0.3) < 0.85,
          f"{gop_quality(0.3):.2f}")


def test_word_aggregation_penalises_one_bad_phone() -> None:
    """The property that made 'sink' pass as 'think' before it was fixed."""
    print("\nword aggregation")
    from app.scoring import WORD_MEAN_WEIGHT

    def word_score(vals: list[int]) -> float:
        return WORD_MEAN_WEIGHT * float(np.mean(vals)) + (1 - WORD_MEAN_WEIGHT) * min(vals)

    ruined = word_score([5, 95, 95, 95])     # one phone destroyed, rest perfect
    uniform = word_score([88, 92, 90, 95])   # genuinely good word

    check("one ruined phone drags the word under 'fair'", ruined < 60,
          f"got {ruined:.0f}")
    check("a uniformly good word is barely affected", uniform > 85,
          f"got {uniform:.0f}")
    check("plain mean would have hidden the error", float(np.mean([5, 95, 95, 95])) > 60,
          "mean=72 -> a pass, which is the bug")


def main() -> int:
    print("deterministic scoring tests (no audio, no model)")
    test_forced_align_recovers_spans()
    test_forced_align_low_confidence()
    test_forced_align_too_short()
    test_edit_align_substitution()
    test_edit_align_deletion_and_insertion()
    test_similarity_ordering()
    test_gop_curve()
    test_word_aggregation_penalises_one_bad_phone()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
