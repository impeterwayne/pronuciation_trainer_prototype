"""Download and generate sample audio files for testing the Pronunciation Trainer.

Fetches human native and non-native recordings from Wikimedia Commons / CMU Arctic,
converts all files to standard 16 kHz mono WAV, and synthesises test pairs with eSpeak.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Add backend directory to sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import soundfile as sf  # noqa: E402
from app import tts  # noqa: E402
from app.audio import load_audio  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

USER_AGENT = "PronunciationTrainerTest/1.0 (tester@pronunciationtrain.org)"

SAMPLES_DIR = ROOT / "samples"
WORDS_DIR = SAMPLES_DIR / "words"
SENTENCES_DIR = SAMPLES_DIR / "sentences"
SYNTHETIC_DIR = SAMPLES_DIR / "synthetic"

# Curated list of human audio recordings from Wikimedia Commons
WIKIMEDIA_WORDS = [
    # Minimal pair: i: vs ɪ
    {"filename": "sheep.wav", "text": "sheep", "title": "File:En-us-sheep.ogg", "category": "minimal_pair", "focus": "iː"},
    {"filename": "ship.wav", "text": "ship", "title": "File:En-us-ship.ogg", "category": "minimal_pair", "focus": "ɪ"},
    {"filename": "feel.wav", "text": "feel", "title": "File:En-us-feel.ogg", "category": "minimal_pair", "focus": "iː"},
    {"filename": "fill.wav", "text": "fill", "title": "File:En-us-fill.ogg", "category": "minimal_pair", "focus": "ɪ"},
    {"filename": "beat.wav", "text": "beat", "title": "File:En-us-beat.ogg", "category": "minimal_pair", "focus": "iː"},
    {"filename": "bit.wav", "text": "bit", "title": "File:En-us-bit.ogg", "category": "minimal_pair", "focus": "ɪ"},
    # Minimal pair: θ vs t / s
    {"filename": "three.wav", "text": "three", "title": "File:En-us-three.ogg", "category": "minimal_pair", "focus": "θ"},
    {"filename": "tree.wav", "text": "tree", "title": "File:En-us-tree.ogg", "category": "minimal_pair", "focus": "t"},
    {"filename": "think.wav", "text": "think", "title": "File:En-us-think.ogg", "category": "minimal_pair", "focus": "θ"},
    {"filename": "sink.wav", "text": "sink", "title": "File:En-us-sink.ogg", "category": "minimal_pair", "focus": "s"},
    # Minimal pair: r vs l
    {"filename": "rice.wav", "text": "rice", "title": "File:En-us-rice.ogg", "category": "minimal_pair", "focus": "ɹ"},
    {"filename": "lice.wav", "text": "lice", "title": "File:LL-Q1860 (eng)-Vealhurl-lice.wav", "category": "minimal_pair", "focus": "l"},
    {"filename": "road.wav", "text": "road", "title": "File:En-us-road.ogg", "category": "minimal_pair", "focus": "ɹ"},
    {"filename": "load.wav", "text": "load", "title": "File:En-us-load.ogg", "category": "minimal_pair", "focus": "l"},
    {"filename": "right.wav", "text": "right", "title": "File:En-us-right.ogg", "category": "minimal_pair", "focus": "ɹ"},
    {"filename": "light.wav", "text": "light", "title": "File:En-us-light.ogg", "category": "minimal_pair", "focus": "l"},
    {"filename": "correct.wav", "text": "correct", "title": "File:En-us-correct.ogg", "category": "lesson_word", "focus": "ɹ"},
    {"filename": "collect.wav", "text": "collect", "title": "File:En-us-collect.ogg", "category": "lesson_word", "focus": "l"},
    # Minimal pair: v vs b / w
    {"filename": "very.wav", "text": "very", "title": "File:En-us-very.ogg", "category": "minimal_pair", "focus": "v"},
    {"filename": "berry.wav", "text": "berry", "title": "File:En-us-berry.ogg", "category": "minimal_pair", "focus": "b"},
    {"filename": "vine.wav", "text": "vine", "title": "File:En-us-vine.ogg", "category": "minimal_pair", "focus": "v"},
    {"filename": "wine.wav", "text": "wine", "title": "File:En-us-wine.ogg", "category": "minimal_pair", "focus": "w"},
    {"filename": "vest.wav", "text": "vest", "title": "File:En-us-vest.ogg", "category": "minimal_pair", "focus": "v"},
    {"filename": "west.wav", "text": "west", "title": "File:En-us-west.ogg", "category": "minimal_pair", "focus": "w"},
    # Core vocabulary & clusters
    {"filename": "mother.wav", "text": "mother", "title": "File:En-us-mother.ogg", "category": "lesson_word", "focus": "ð"},
    {"filename": "birthday.wav", "text": "birthday", "title": "File:En-us-birthday.ogg", "category": "lesson_word", "focus": "θ"},
    {"filename": "water.wav", "text": "water", "title": "File:En-us-water.ogg", "category": "lesson_word", "focus": "w"},
    {"filename": "street.wav", "text": "street", "title": "File:En-us-street.ogg", "category": "lesson_word", "focus": "str-"},
    {"filename": "strength.wav", "text": "strength", "title": "File:En-us-strength.ogg", "category": "lesson_word", "focus": "ŋθ"},
    {"filename": "beautiful.wav", "text": "beautiful", "title": "File:En-us-beautiful.ogg", "category": "lesson_word", "focus": "stress"},
]

# Sentences from CMU Arctic & Wikimedia
SENTENCE_SOURCES = [
    {
        "filename": "cmu_arctic_us_female_a0001.wav",
        "text": "Author of the danger trail, Philip Steels, etc.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_slt_arctic/wav/arctic_a0001.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (US Female - slt)",
    },
    {
        "filename": "cmu_arctic_us_male_a0001.wav",
        "text": "Author of the danger trail, Philip Steels, etc.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_bdl_arctic/wav/arctic_a0001.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (US Male - bdl)",
    },
    {
        "filename": "cmu_arctic_scottish_male_a0001.wav",
        "text": "Author of the danger trail, Philip Steels, etc.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_awb_arctic/wav/arctic_a0001.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (Scottish Male - awb)",
    },
    {
        "filename": "cmu_arctic_us_female_a0002.wav",
        "text": "Not at this particular case, Tom, apologized Whittemore.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_slt_arctic/wav/arctic_a0002.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (US Female - slt)",
    },
    {
        "filename": "cmu_arctic_us_male_a0003.wav",
        "text": "For the twentieth time that evening the two men shook hands.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_bdl_arctic/wav/arctic_a0003.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (US Male - bdl)",
    },
    {
        "filename": "cmu_arctic_us_female_a0004.wav",
        "text": "Lord, but I'm glad to see you again, Phil.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_slt_arctic/wav/arctic_a0004.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (US Female - slt)",
    },
    {
        "filename": "cmu_arctic_us_male_a0004.wav",
        "text": "Lord, but I'm glad to see you again, Phil.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_bdl_arctic/wav/arctic_a0004.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (US Male - bdl)",
    },
    {
        "filename": "cmu_arctic_us_female_a0005.wav",
        "text": "Will we ever forget it.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_slt_arctic/wav/arctic_a0005.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (US Female - slt)",
    },
    {
        "filename": "cmu_arctic_scottish_male_a0005.wav",
        "text": "Will we ever forget it.",
        "url": "http://www.festvox.org/cmu_arctic/cmu_arctic/cmu_us_awb_arctic/wav/arctic_a0005.wav",
        "category": "sentence",
        "speaker": "CMU Arctic (Scottish Male - awb)",
    },
    {
        "filename": "loose_lips_sink_ships.wav",
        "text": "Loose lips sink ships.",
        "title": "File:En-us-loose lips sink ships.ogg",
        "category": "sentence",
        "speaker": "Wikimedia Commons (US English)",
    },
]

# Synthetic minimal pairs to generate via eSpeak TTS
SYNTHETIC_ITEMS = [
    ("syn_sheep.wav", "sheep", "normal"),
    ("syn_ship.wav", "ship", "normal"),
    ("syn_three.wav", "three", "normal"),
    ("syn_tree.wav", "tree", "normal"),
    ("syn_thin.wav", "thin", "normal"),
    ("syn_sin.wav", "sin", "normal"),
    ("syn_rice.wav", "rice", "normal"),
    ("syn_lice.wav", "lice", "normal"),
    ("syn_very.wav", "very", "normal"),
    ("syn_berry.wav", "berry", "normal"),
    ("syn_wine.wav", "wine", "normal"),
    ("syn_vine.wav", "vine", "normal"),
    ("syn_feel.wav", "feel", "normal"),
    ("syn_fill.wav", "fill", "normal"),
    ("syn_she_sells_seashells.wav", "she sells seashells by the seashore", "normal"),
    ("syn_cup_of_coffee.wav", "I would like a cup of coffee", "normal"),
]


def resolve_wikimedia_urls(titles: list[str]) -> dict[str, str]:
    """Query Wikimedia Commons API to get direct media URLs for file titles."""
    result: dict[str, str] = {}
    chunk_size = 20
    for i in range(0, len(titles), chunk_size):
        chunk = titles[i : i + chunk_size]
        params = {
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for p in pages.values():
                title = p.get("title", "")
                infos = p.get("imageinfo", [])
                if infos and "url" in infos[0]:
                    clean_url = infos[0]["url"].split("?")[0]
                    result[title] = clean_url
                    result[title.replace(" ", "_")] = clean_url
        except Exception as e:
            logger.warning("Failed to resolve Wikimedia URLs for batch: %s", e)
        time.sleep(1.0)
    return result


def fetch_and_save_audio(url: str, out_path: Path) -> bool:
    """Download raw audio from url, decode/normalize to 16 kHz mono WAV, and save."""
    clean_url = url.split("?")[0]
    req = urllib.request.Request(
        clean_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "audio/*, */*",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw_bytes = resp.read()
            arr = load_audio(raw_bytes)
            sf.write(str(out_path), arr, 16000, subtype="PCM_16")
            return True
        except Exception as e:
            wait = 2.0 * (attempt + 1)
            logger.warning("Attempt %d failed downloading %s: %s (retrying in %.1fs)", attempt + 1, clean_url, e, wait)
            time.sleep(wait)
    return False


def main():
    WORDS_DIR.mkdir(parents=True, exist_ok=True)
    SENTENCES_DIR.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []

    # 1. Fetch sentence samples (PRIORITIZED FIRST)
    logger.info("Downloading sentence samples (Priority #1)...")
    for item in SENTENCE_SOURCES:
        dest = SENTENCES_DIR / item["filename"]
        if dest.exists() and dest.stat().st_size > 1000:
            logger.info("  Already present: %s", item["filename"])
            manifest.append({
                "file": f"sentences/{item['filename']}",
                "text": item["text"],
                "category": item["category"],
                "speaker": item.get("speaker", ""),
                "type": "human",
                "source": item.get("url") or item.get("title"),
            })
            continue

        url = item.get("url")
        if not url and "title" in item:
            title = item["title"]
            url = url_map.get(title) or url_map.get(title.replace(" ", "_"))
        if not url:
            logger.warning("No URL resolved for sentence %s", item["filename"])
            continue
        logger.info("  Fetching sentence %s", item["filename"])
        if fetch_and_save_audio(url, dest):
            manifest.append({
                "file": f"sentences/{item['filename']}",
                "text": item["text"],
                "category": item["category"],
                "speaker": item.get("speaker", ""),
                "type": "human",
                "source": url,
            })
        time.sleep(1.0)

    # 2. Fetch Wikimedia words
    wm_titles = [item["title"] for item in WIKIMEDIA_WORDS]
    wm_titles.extend([item["title"] for item in SENTENCE_SOURCES if "title" in item])

    logger.info("Resolving %d Wikimedia titles...", len(wm_titles))
    url_map = resolve_wikimedia_urls(wm_titles)

    logger.info("Downloading human word samples...")
    for item in WIKIMEDIA_WORDS:
        dest = WORDS_DIR / item["filename"]
        if dest.exists() and dest.stat().st_size > 1000:
            logger.info("  Already present: %s", item["filename"])
            manifest.append({
                "file": f"words/{item['filename']}",
                "text": item["text"],
                "category": item["category"],
                "focus": item.get("focus", ""),
                "type": "human_native",
                "source": item["title"],
            })
            continue

        title = item["title"]
        url = url_map.get(title) or url_map.get(title.replace(" ", "_"))
        if not url:
            logger.warning("No URL resolved for %s (%s)", item["filename"], title)
            continue
        logger.info("  Fetching %s -> %s", item["text"], item["filename"])
        if fetch_and_save_audio(url, dest):
            manifest.append({
                "file": f"words/{item['filename']}",
                "text": item["text"],
                "category": item["category"],
                "focus": item.get("focus", ""),
                "type": "human_native",
                "source": title,
            })
        time.sleep(1.8)  # Rate limit courtesy for Wikimedia

    # 3. Generate synthetic samples via eSpeak TTS
    logger.info("Generating synthetic samples via eSpeak TTS...")
    for filename, text, speed in SYNTHETIC_ITEMS:
        dest = SYNTHETIC_DIR / filename
        if not dest.exists() or dest.stat().st_size < 100:
            try:
                raw_wav = tts.synthesize(text, speed=speed)
                arr = load_audio(raw_wav)
                sf.write(str(dest), arr, 16000, subtype="PCM_16")
                logger.info("  Generated synthetic: %s -> '%s'", filename, text)
            except Exception as e:
                logger.warning("Failed to generate synthetic %s: %s", filename, e)

        manifest.append({
            "file": f"synthetic/{filename}",
            "text": text,
            "category": "synthetic_control",
            "type": "synthetic_espeak",
            "speed": speed,
        })

    # 4. Write manifest.json
    manifest_path = SAMPLES_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Wrote manifest to %s with %d total sample entries.", manifest_path, len(manifest))

    # 5. Write samples README
    readme_path = SAMPLES_DIR / "README.md"
    readme_content = f"""# Test Audio Samples

Curated 16 kHz Mono WAV audio samples for testing the Pronunciation Trainer scoring pipeline.

Total samples: **{len(manifest)}**

## Directory Structure

* **`words/`**: Human native recordings of core English phoneme minimal pairs (`sheep`/`ship`, `three`/`tree`, `rice`/`lice`, `very`/`berry`, etc.).
* **`sentences/`**: Human recordings of full English sentences from CMU ARCTIC (US female, US male, Scottish male) and Wikimedia Commons.
* **`synthetic/`**: Reference speech synthesized with eSpeak-NG for deterministic regression testing.
* **`manifest.json`**: JSON index of all sample files with target text, category, and metadata.

## How to Test

### 1. Test Single File via API
```bash
curl -X POST http://127.0.0.1:8000/api/assess \\
  -F "text=sheep" \\
  -F "audio=@samples/words/sheep.wav"
```

### 2. Run Automated Sample Assessment
```bash
python tools/test_samples.py
```
"""
    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info("Sample audio suite setup complete!")


if __name__ == "__main__":
    main()
