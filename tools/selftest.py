"""End-to-end check with no microphone required.

The trick: use espeak-ng's own synthesis as stand-in "user audio".

  * Synthesising "sheep" and scoring it against the text "sheep" should score high.
    That is a positive control -- if it fails, G2P, ASR, alignment or scoring is broken.

  * Synthesising "sheep" and scoring it against the text "ship" should score low,
    and the report should say the /iː/ was heard as /ɪ/. That is the negative control,
    and it is the one that actually tells you the scorer discriminates rather than
    just rubber-stamping whatever it hears.

Run:  python tools/selftest.py            (full suite)
      python tools/selftest.py --quick    (G2P + TTS only, no model download)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The Windows console defaults to cp1252, which cannot render IPA.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config  # noqa: E402  (must run bootstrap_espeak first)
from app import tts  # noqa: E402
from app.g2p import phonemize  # noqa: E402

PASS, FAIL = "  PASS", "  FAIL"

# Minimal pairs: the two members differ by exactly one phone, so the score
# difference isolates that phone and nothing else.
PAIRS = [
    ("three", "tree"),    # θ / t
    ("thin", "sin"),      # θ / s
    ("rice", "lice"),     # ɹ / l
    ("very", "berry"),    # v / b
    ("wine", "vine"),     # w / v
    ("feel", "fill"),     # iː / ɪ
    ("sheep", "ship"),    # iː / ɪ
]

SENTENCES = [
    ("she sells seashells by the seashore", "he tells wet shells by the way"),
    ("I would like a cup of coffee", "I would fight a cup of toffee"),
]

# Absolute scores are NOT the assertion here -- see the note in main().
# What must hold is that the correct text outscores the wrong text.
MARGIN = 12                 # a clear win
NOISE = 3                   # a wrong text may never beat the correct one by more
DISCRIMINATION_TARGET = 0.7  # fraction of *informative* cases that must win clearly
FLAGGED_BELOW = 60          # the swapped phone must land under "fair"
TEST_SPEED = 130            # espeak wpm; 150 slurs badly for a recogniser

# A case only tests the scorer if the recogniser heard the correct word in the first
# place. espeak renders /θ/ as something the model hears as /s/ or /f/, and its short
# vowels are unstable, so a handful of clips carry no usable contrast at all. Scoring
# those measures the synthesiser, not this code, so they are reported and skipped
# rather than quietly dragging the pass rate around.
INFORMATIVE_MIN = 40


def check_environment() -> bool:
    lib = config.find_espeak_library()
    exe = config.find_espeak_exe()
    data = config.find_espeak_data()
    print("environment")
    print(f"  espeak library : {lib}")
    print(f"  espeak binary  : {exe}")
    print(f"  espeak data    : {data}")
    if not lib or not exe:
        print(FAIL, "espeak-ng not found - run scripts/setup_windows.ps1")
        return False
    return True


def check_g2p() -> bool:
    print("\ng2p (phonemizer + espeak)")
    ok = True
    cases = {
        "sheep": "ʃ",
        "think": "θ",
        "this": "ð",
        "right": "ɹ",
        "very": "v",
    }
    for word, expect in cases.items():
        ref = phonemize(word)
        ipa = ref.ipa
        hit = expect in "".join(ref.norm)
        print(f"  {word:<20} /{ipa}/   {'ok' if hit else 'missing ' + expect}")
        ok = ok and hit

    sent = phonemize("she sells seashells by the seashore")
    print(f"  per-word split       {[w.text for w in sent.words]}")
    print(f"                       {[w.ipa for w in sent.words]}")
    ok = ok and len(sent.words) == 6
    return ok


def check_tts() -> bool:
    print("\ntts (espeak-ng CLI)")
    try:
        wav = tts.synthesize("sheep")
        slow = tts.synthesize("sheep", speed=85)
    except tts.TTSUnavailable as exc:
        print(FAIL, exc)
        return False
    print(f"  normal speed   {len(wav):>7} bytes")
    print(f"  slow speed     {len(slow):>7} bytes  (should be larger)")
    print(f"  espeak --ipa   {tts.phonemes_via_cli('she sells seashells')}")
    return len(wav) > 1000 and len(slow) > len(wav)


def _score(spoken_wav_cache: dict, spoken: str, target: str):
    from app.asr import recognize
    from app.audio import load_audio
    from app.g2p import en_inventory
    from app.scoring import assess

    ref = phonemize(target)
    # Same constraint the API applies. Note it depends on the *target* text, so the
    # recognition is cached per (spoken, target) pair rather than per audio clip.
    allowed = en_inventory() | set(ref.norm)
    key = (spoken, frozenset(allowed))
    if key not in spoken_wav_cache:
        spoken_wav_cache[key] = recognize(
            load_audio(tts.synthesize(spoken, speed=TEST_SPEED)), allowed=allowed)
    return assess(ref, spoken_wav_cache[key])


def check_scoring() -> bool:
    print("\nscoring (wav2vec2 CTC + forced alignment)")
    print("  loading model (first run downloads ~1.2 GB)...")
    print(f"  assertion: correct text must beat wrong text by >= {MARGIN} points\n")

    cache: dict = {}
    gaps: list[tuple[str, int]] = []
    skipped: list[str] = []

    def run(spoken: str, other: str, label: str) -> None:
        same = _score(cache, spoken, spoken)
        cross = _score(cache, spoken, other)
        gap = same.overall - cross.overall

        worst = min((p for w in cross.words for p in w.phones),
                    key=lambda p: p.score, default=None)
        flagged = worst is not None and worst.score < FLAGGED_BELOW

        if same.overall < INFORMATIVE_MIN:
            verdict = "skip"
            skipped.append(spoken)
        else:
            gaps.append((spoken, gap))
            if gap >= MARGIN and flagged:
                verdict = "ok  "
            elif gap < -NOISE:
                verdict = "BAD "     # wrong text actually won - a real defect
            else:
                verdict = "weak"     # no clear separation

        print(f"  [{verdict}] {label}: '{spoken}'")
        print(f"         vs correct text  {same.overall:>3}"
              f"   vs '{other}'  {cross.overall:>3}   gap {gap:>+4}")
        print(f"         heard /{same.recognized_ipa}/")
        if verdict == "skip":
            print("         <-- espeak's rendering is unrecognisable; case carries "
                  "no contrast")
            return
        if worst is not None:
            heard = f"heard /{worst.heard}/" if worst.heard else "dropped"
            print(f"         flagged /{worst.norm}/ at {worst.score} ({heard})"
                  + ("" if flagged else "   <-- not flagged hard enough"))

    for a, b in PAIRS:
        run(a, b, "minimal pair")
        run(b, a, "minimal pair")
    for a, b in SENTENCES:
        run(a, b, "sentence")

    total = len(gaps)
    clear = sum(1 for _, g in gaps if g >= MARGIN)
    inverted = [w for w, g in gaps if g < -NOISE]
    rate = clear / total if total else 0.0

    print(f"\n  informative cases {total}"
          + (f"   (skipped {len(skipped)}: {skipped})" if skipped else ""))
    print(f"  clear wins        {clear}/{total}  ({rate:.0%}, "
          f"need {DISCRIMINATION_TARGET:.0%})")
    print(f"  inverted results  {len(inverted)}"
          + (f"  {inverted}" if inverted else "   (none - required)"))

    return rate >= DISCRIMINATION_TARGET and not inverted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="skip the ASR stage (no model download)")
    args = ap.parse_args()

    results = {"environment": check_environment()}
    if not results["environment"]:
        return 1
    results["g2p"] = check_g2p()
    results["tts"] = check_tts()
    if not args.quick:
        results["scoring"] = check_scoring()

    print("\nsummary")
    for name, ok in results.items():
        print(f"  {name:<14} {'PASS' if ok else 'FAIL'}")
    if not args.quick:
        print("\n  Note: the stand-in audio is espeak's formant synthesis, which is")
        print("  out of domain for a model trained on human CommonVoice speech.")
        print("  Absolute scores here run low and are not a calibration - the")
        print("  margin between correct and wrong text is the meaningful signal.")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
