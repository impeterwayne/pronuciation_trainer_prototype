"""IPA phone utilities shared by the G2P side and the ASR side.

Both sides speak *espeak IPA*: `phonemizer` drives espeak-ng directly, and the ASR
model (facebook/wav2vec2-lv-60-espeak-cv-ft) was fine-tuned on espeak-phonemized
CommonVoice, so its output vocabulary is the same alphabet. That is the whole
reason this pairing works -- no phone-set conversion table is needed, only
normalisation of stress/length decorations.
"""

from __future__ import annotations

import unicodedata

STRESS_MARKS = "ˈˌˑ͜͡"  # ˈ ˌ ˑ + tie bars
LENGTH_MARK = "ː"  # ː


def normalize_phone(p: str) -> str:
    """Strip stress marks and normalise unicode so reference and hypothesis match."""
    p = unicodedata.normalize("NFC", p)
    p = "".join(ch for ch in p if ch not in STRESS_MARKS)
    # espeak occasionally emits ASCII 'g'; the model vocab uses IPA U+0261
    p = p.replace("g", "ɡ")
    return p.strip()


def has_stress(p: str) -> bool:
    return "ˈ" in p


def strip_length(p: str) -> str:
    return p.replace(LENGTH_MARK, "")


# --------------------------------------------------------------------------- classes

VOWELS = set("iɪeɛæaɑɒɔoʊuʌɜəɐɚɝᵻʏøœyɵɤɯ")

# Broad articulatory buckets. Substituting inside a bucket is a "near miss"
# (partial credit); across buckets it is a hard error.
_CLASSES: dict[str, tuple[str, ...]] = {
    "plosive_vl": ("p", "t", "k", "ʔ"),
    "plosive_vd": ("b", "d", "ɡ"),
    "affricate": ("tʃ", "dʒ"),
    "fricative_vl": ("f", "θ", "s", "ʃ", "h", "x"),
    "fricative_vd": ("v", "ð", "z", "ʒ"),
    "nasal": ("m", "n", "ŋ"),
    "liquid": ("l", "ɹ", "ɾ", "r", "ɫ"),
    "glide": ("w", "j"),
    "vowel_front_high": ("i", "iː", "ɪ", "ᵻ", "y"),
    "vowel_front_mid": ("e", "eɪ", "ɛ", "æ"),
    "vowel_central": ("ə", "ʌ", "ɐ", "ɜ", "ɜː", "ɚ", "ɝ"),
    "vowel_back_high": ("u", "uː", "ʊ"),
    "vowel_back_mid": ("o", "oʊ", "ɔ", "ɔː", "ɒ", "ɑ", "ɑː"),
    "diphthong": ("aɪ", "aʊ", "ɔɪ", "eɪ", "oʊ", "ɪə", "eə", "ʊə"),
}

_PHONE_CLASS: dict[str, str] = {}
for _cls, _members in _CLASSES.items():
    for _m in _members:
        _PHONE_CLASS.setdefault(_m, _cls)

# Confusions that are extremely common for L2 English learners. Treated as
# "close" so the learner is told *which* contrast to fix rather than just "wrong".
COMMON_CONFUSIONS: set[frozenset[str]] = {
    frozenset(x)
    for x in [
        ("θ", "s"), ("θ", "t"), ("θ", "f"),
        ("ð", "d"), ("ð", "z"), ("ð", "v"),
        ("ɹ", "l"), ("ɹ", "w"),
        ("v", "w"), ("v", "b"), ("v", "f"),
        ("ʃ", "s"), ("ʒ", "z"), ("dʒ", "j"), ("tʃ", "ʃ"),
        ("z", "s"), ("ŋ", "n"), ("n", "l"),
        ("iː", "ɪ"), ("uː", "ʊ"), ("æ", "ɛ"), ("æ", "e"),
        ("ɑː", "ʌ"), ("ɔː", "oʊ"), ("ə", "ʌ"), ("ɜː", "ɚ"),
    ]
}


def is_vowel(p: str) -> bool:
    p = normalize_phone(p)
    return bool(p) and p[0] in VOWELS


def phone_similarity(a: str, b: str) -> float:
    """0.0 (unrelated) .. 1.0 (identical). Drives partial credit on substitutions."""
    a, b = normalize_phone(a), normalize_phone(b)
    if a == b:
        return 1.0
    if strip_length(a) == strip_length(b):
        return 0.85  # only vowel length differs, e.g. iː vs i
    if frozenset((a, b)) in COMMON_CONFUSIONS:
        return 0.55
    ca, cb = _PHONE_CLASS.get(a), _PHONE_CLASS.get(b)
    if ca and ca == cb:
        return 0.5
    if is_vowel(a) == is_vowel(b):
        return 0.2  # both vowels or both consonants, but unrelated
    return 0.0


def substitution_cost(a: str, b: str) -> float:
    return 1.0 - phone_similarity(a, b)


# --------------------------------------------------------------------------- hints

# Short, actionable coaching per phone. Shown when a phone scores badly.
ARTICULATION_HINTS: dict[str, str] = {
    "θ": "Tongue tip lightly between the teeth, blow air — no voice. Not /s/, not /t/.",
    "ð": "Same tongue position as 'th' in think, but switch your voice on.",
    "ɹ": "Curl the tongue back without touching the roof of the mouth. Lips slightly rounded.",
    "l": "Tongue tip firmly on the ridge behind your top teeth, air flows round the sides.",
    "v": "Top teeth on the bottom lip, add voice. Do not close the lips like /b/ or /w/.",
    "f": "Top teeth on the bottom lip, blow — no voice.",
    "w": "Round the lips tight, no teeth contact.",
    "z": "Like /s/ but with the voice on — buzz it.",
    "s": "Narrow groove in the tongue, hiss — keep it voiceless.",
    "ʃ": "Pull the tongue back from /s/ and round the lips slightly.",
    "ʒ": "Like 'sh' but voiced, as in 'measure'.",
    "tʃ": "Stop then release into 'sh' — one single sound.",
    "dʒ": "Stop then release into 'zh' — one single sound, voiced.",
    "ŋ": "Back of the tongue against the soft palate; do not add a /ɡ/ at the end.",
    "n": "Tongue tip on the ridge behind the top teeth, air through the nose.",
    "iː": "Long and tense, lips spread wide — clearly longer than the /ɪ/ in 'ship'.",
    "ɪ": "Short and relaxed, jaw slightly lower than /iː/. Do not stretch it.",
    "uː": "Long, lips tightly rounded and pushed forward.",
    "ʊ": "Short and relaxed, looser lips than /uː/.",
    "æ": "Open the jaw wide and spread the lips — lower than /e/.",
    "ɛ": "Mid-open jaw, lips relaxed and spread.",
    "ʌ": "Central, short, relaxed — mouth barely open.",
    "ɑː": "Jaw dropped low, tongue back, long.",
    "ɔː": "Tongue back, lips rounded, long.",
    "ɜː": "Central and long, lips neutral — the vowel in 'bird'.",
    "ɚ": "Unstressed r-coloured vowel — the ending of 'teacher'.",
    "ə": "Weakest, shortest vowel. Do not give it a full clear value.",
    "eɪ": "Glide from /e/ up to /ɪ/ — two positions, one syllable.",
    "oʊ": "Glide from /o/ to /ʊ/, lips rounding as you go.",
    "aɪ": "Start with the jaw open, glide up to /ɪ/.",
    "aʊ": "Start with the jaw open, glide to rounded /ʊ/.",
    "ɔɪ": "Start rounded, glide up to /ɪ/.",
}


def hint_for(phone: str) -> str | None:
    p = normalize_phone(phone)
    return ARTICULATION_HINTS.get(p) or ARTICULATION_HINTS.get(strip_length(p))
