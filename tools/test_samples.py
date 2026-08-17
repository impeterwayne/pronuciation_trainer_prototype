"""Evaluate the downloaded sample audio files through the scoring pipeline."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Reconfigure stdout for utf-8 on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from app import asr, config  # noqa: E402
from app.audio import load_audio  # noqa: E402
from app.g2p import en_inventory, phonemize  # noqa: E402
from app.scoring import assess  # noqa: E402

SAMPLES_DIR = ROOT / "samples"
MANIFEST_PATH = SAMPLES_DIR / "manifest.json"


def main():
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found at {MANIFEST_PATH}. Run `python tools/fetch_samples.py` first.")
        sys.exit(1)

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        samples = json.load(f)

    print("=" * 105)
    print("Pronunciation Trainer - Sample Audio Evaluation Benchmark")
    print("=" * 105)

    # Initialize ASR model
    print("\nLoading wav2vec2 CTC model...")
    try:
        asr._load()
    except Exception as e:
        print(f"Note on eager loading: {e}")
    print("Model ready.\n")

    header = f"{'Category':<17} {'Audio File':<32} {'Target Text':<22} {'Overall':<8} {'Acc':<6} {'Grade':<6} {'Ref IPA / Recognized IPA'}"
    print(header)
    print("-" * 125)

    scores: list[int] = []

    for item in samples:
        rel_path = item["file"]
        audio_path = SAMPLES_DIR / rel_path
        if not audio_path.exists():
            continue

        text = item["text"]
        category = item.get("category", "")

        try:
            # 1. Load audio
            raw_bytes = audio_path.read_bytes()
            audio_arr = load_audio(raw_bytes)

            # 2. Reference phonemes
            ref = phonemize(text)
            allowed = en_inventory(config.settings.lang) | set(ref.norm)

            # 3. Model emission & ASR recognition
            result = asr.recognize(audio_arr, config.settings.sample_rate, allowed=allowed)

            # 4. Assess
            assessment = assess(ref, result)

            overall_score = assessment.overall
            accuracy_score = assessment.accuracy
            scores.append(overall_score)

            grade = (
                "GOOD" if overall_score >= config.settings.good_threshold
                else ("FAIR" if overall_score >= config.settings.fair_threshold else "POOR")
            )
            ref_ipa = assessment.reference_ipa
            heard_ipa = assessment.recognized_ipa

            print(
                f"{category:<17} {Path(rel_path).name:<32} {text:<22} {overall_score:<8} {accuracy_score:<6} {grade:<6} /{ref_ipa}/ -> [{heard_ipa}]"
            )
        except Exception as e:
            print(f"{category:<17} {Path(rel_path).name:<32} {text:<22} ERROR: {e}")

    avg_score = sum(scores) / len(scores) if scores else 0.0
    print("-" * 125)
    print(f"Total Evaluated Samples: {len(scores)} | Average Score: {avg_score:.1f}/100")
    print("=" * 105)


if __name__ == "__main__":
    main()
