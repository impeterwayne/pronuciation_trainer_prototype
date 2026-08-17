"""Grapheme -> phoneme: the *reference* pronunciation, via phonemizer + espeak-ng."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache

from .config import bootstrap_espeak, find_espeak_library, settings
from .phones import normalize_phone

_backend = None
_backend_lock = threading.Lock()

_WORD_SEP = " ǀ "  # U+01C0, cannot occur in espeak IPA output
_PUNCT_RE = re.compile(r"[^\w'\-À-ɏ]+", re.UNICODE)


class G2PUnavailable(RuntimeError):
    pass


def _get_backend(lang: str):
    global _backend
    with _backend_lock:
        if _backend is not None and _backend[0] == lang:
            return _backend[1]

        bootstrap_espeak()
        if find_espeak_library() is None:
            raise G2PUnavailable(
                "espeak-ng shared library not found. Install espeak-ng and/or set "
                "PHONEMIZER_ESPEAK_LIBRARY to the absolute path of libespeak-ng.dll. "
                "See scripts/setup_windows.ps1."
            )
        try:
            from phonemizer.backend import EspeakBackend
            from phonemizer.backend.espeak.wrapper import EspeakWrapper

            EspeakWrapper.set_library(str(find_espeak_library()))
            backend = EspeakBackend(
                lang,
                preserve_punctuation=False,
                with_stress=True,
                words_mismatch="ignore",
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the API as a 503
            raise G2PUnavailable(f"could not initialise espeak backend: {exc}") from exc

        _backend = (lang, backend)
        return backend


@dataclass
class RefWord:
    text: str
    phones: list[str] = field(default_factory=list)  # with stress marks, for display
    norm: list[str] = field(default_factory=list)  # stress-stripped, for matching

    @property
    def ipa(self) -> str:
        return "".join(self.phones)


@dataclass
class Reference:
    text: str
    words: list[RefWord]

    @property
    def phones(self) -> list[str]:
        return [p for w in self.words for p in w.phones]

    @property
    def norm(self) -> list[str]:
        return [p for w in self.words for p in w.norm]

    def word_index_of_phone(self) -> list[int]:
        """For each flat phone index, which word it belongs to."""
        out: list[int] = []
        for i, w in enumerate(self.words):
            out.extend([i] * len(w.phones))
        return out

    @property
    def ipa(self) -> str:
        return " ".join(w.ipa for w in self.words)


def tokenize(text: str) -> list[str]:
    return [t for t in _PUNCT_RE.split(text.strip()) if t]


def _phonemize_raw(backend, chunks: list[str]) -> list[str]:
    from phonemizer.separator import Separator

    sep = Separator(phone=" ", word=_WORD_SEP, syllable="")
    return backend.phonemize(chunks, separator=sep, strip=True, njobs=1)


def phonemize(text: str, lang: str | None = None) -> Reference:
    """Return per-word IPA phones for `text`.

    The whole utterance is phonemized in one shot so espeak applies sentence-level
    reductions ("the" -> ðə vs ðiː). If espeak collapses or drops words and the
    count no longer lines up, we fall back to phonemizing each word alone.
    """
    lang = lang or settings.lang
    backend = _get_backend(lang)
    words = tokenize(text)
    if not words:
        return Reference(text=text, words=[])

    per_word: list[list[str]] | None = None
    try:
        joined = _phonemize_raw(backend, [" ".join(words)])[0]
        chunks = [c.strip() for c in joined.split(_WORD_SEP.strip()) if c.strip()]
        if len(chunks) == len(words):
            per_word = [c.split() for c in chunks]
    except Exception:  # noqa: BLE001 - fall through to per-word mode
        per_word = None

    if per_word is None:
        outs = _phonemize_raw(backend, words)
        per_word = [o.replace(_WORD_SEP.strip(), " ").split() for o in outs]

    ref_words = []
    for w, phs in zip(words, per_word):
        phs = [p for p in phs if p]
        ref_words.append(
            RefWord(text=w, phones=phs, norm=[normalize_phone(p) for p in phs])
        )
    return Reference(text=text, words=ref_words)


# --------------------------------------------------------------------------- inventory

# Words chosen to cover the full English phone inventory (a "phonemic pangram" set)
# plus the highest-frequency function words, whose reduced forms carry phones the
# citation forms never show (ðə, ənd, əv).
_INVENTORY_SEEDS = (
    # consonants
    "pat bat tap dad cat gag chin judge fan van thin this sun zoo ship measure "
    "hat man nun sing lull red wet yes butter bottle little water teacher doctor "
    "nation question vision danger "
    # vowels and diphthongs
    "bead bid bed bad bard body bought book boot but bird about bay buy boy boat "
    "bout beer bear tour hurry marry merry sorry "
    # frequent function words (reduced forms)
    "the a of to and is was are you I he she it we they for on with as at by from "
    "have has had not but what all were when there can an your which their said if "
    "do will each how up out them then these so some her would make like him into "
    "time look two more write go see number no way could people my than first been "
    "call who oil its now find long down day did get come made may part"
)


@lru_cache(maxsize=4)
def en_inventory(lang: str | None = None) -> frozenset[str]:
    """The set of normalised phones espeak actually emits for this language.

    Used to constrain the multilingual recogniser. Without it the zero-shot model
    happily decodes English audio into Mandarin tone phones (`i5`, `ei5`, `ɕ`),
    which wrecks both the transcript and the posteriors behind every GOP score.
    """
    ref = phonemize(_INVENTORY_SEEDS, lang)
    return frozenset(p for p in ref.norm if p)
