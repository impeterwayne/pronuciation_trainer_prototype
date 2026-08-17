# Pronunciation Trainer

Pronunciation scoring from open-source parts: **phonemizer + espeak-ng** produce the
reference pronunciation and the ideal audio, a **wav2vec2 phoneme CTC** model reads the
learner's audio, and forced alignment turns the two into a per-phoneme score.

Everything runs locally. No API keys, no per-request cost.

---

## What each library actually does

`phonemizer` and `espeak-ng` cannot score pronunciation on their own — neither one
listens to audio. They give you the *target*. A third component has to read the
learner's speech, and a fourth has to compare the two:

| Stage | Component | Output |
|---|---|---|
| Reference phonemes | `phonemizer` driving `espeak-ng` | `sheep` → `/ʃˈiːp/` |
| Ideal audio | `espeak-ng` CLI (`-w out.wav`) | reference WAV, normal + half speed |
| Learner phonemes | `facebook/wav2vec2-lv-60-espeak-cv-ft`, decoding masked to the en-us inventory | `/ʃ ɪ p/` + frame posteriors |
| Where each phone is | CTC forced alignment | per-phone time span in the recording |
| Score | GOP × edit alignment | per-phone / per-word / overall |

The pairing is deliberate: that wav2vec2 checkpoint was fine-tuned on
espeak-phonemized CommonVoice, so **its output alphabet is the same espeak IPA that
phonemizer emits**. No phone-set conversion table, no ARPAbet↔IPA mapping — the two
sides line up directly, which is what makes the alignment trustworthy.

---

## Setup

### 1. espeak-ng

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

This extracts a portable espeak-ng into `vendor\eSpeak NG` using `msiexec /a`
(no admin rights, no registry entry). The backend probes `vendor\` first, then
`Program Files\eSpeak NG`, so an existing system-wide install works too.

Linux/macOS: `sudo apt install espeak-ng` or `brew install espeak-ng`.

### 2. Python dependencies

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only wheel
pip install -r backend/requirements.txt
```

### 3. Verify before touching a microphone

```bash
python tools/test_scoring.py         # deterministic unit tests, ~1 s, no model needed
python tools/selftest.py --quick     # espeak + phonemizer, instant
python tools/selftest.py             # full pipeline, downloads ~1.2 GB on first run
```

Two layers, deliberately:

* **`test_scoring.py`** replaces the acoustic model with hand-built CTC posteriors and
  asserts exact behaviour of the code in this repo — that forced alignment recovers
  known frame spans in order, that /θ/→/s/ aligns as one substitution rather than a
  delete+insert pair, that the GOP curve is monotonic, that one ruined phone drags a
  word below "fair". Deterministic, fast, and the actual regression gate.
* **`selftest.py`** runs the whole stack on espeak-synthesised audio (see below).

### 4. Run

```bash
python backend/run.py --reload
```

→ <http://127.0.0.1:8000>. The first `/api/assess` call loads the model (~30 s);
set `PT_EAGER_LOAD=1` to pay that at startup instead.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | espeak paths, model status, thresholds |
| `POST` | `/api/phonemize` | `{text}` → reference IPA, per word |
| `GET` | `/api/tts?text=&speed=normal\|slow` | ideal audio (WAV) |
| `POST` | `/api/assess` | multipart `audio` + `text` → full assessment |
| `GET` | `/api/recording/{id}` | the scored recording, for word-level playback |
| `GET` | `/api/lessons`, `/api/lessons/{id}` | practice content (`?with_ipa=1` for IPA) |
| `GET` | `/api/samples` | list sample audio test library (52 items) |
| `GET` | `/api/samples/audio/{path}` | stream sample WAV audio file |

Interactive docs at `/docs`.

### `POST /api/assess`

```bash
curl -X POST http://127.0.0.1:8000/api/assess \
  -F "text=she sells seashells" \
  -F "audio=@recording.wav"
```

```jsonc
{
  "overall": 74, "accuracy": 78, "completeness": 100, "fluency": 61,
  "reference_ipa": "ʃiː sˈɛlz sˈiːʃɛlz",
  "recognized_ipa": "s iː s ɛ l s s ɪ ʃ ɛ l s",
  "breakdown": { "vowels": 81, "consonants": 74 },
  "duration_s": 1.84, "speech_rate": 9.2,
  "recording_id": "8f0c…",           // GET /api/recording/8f0c… to play it back
  "words": [{
    "text": "she", "ipa": "ʃiː", "score": 52,
    "start_ms": 120.0, "end_ms": 410.0,   // slice of the learner's own audio
    "extra_sounds": [],
    "phones": [
      { "phone": "ʃ", "norm": "ʃ", "status": "sub", "score": 31,
        "heard": "s", "start_ms": 120.0, "end_ms": 260.0, "posterior": 0.19,
        "hint": "Pull the tongue back from /s/ and round the lips slightly." },
      { "phone": "iː", "norm": "iː", "status": "good", "score": 88, … }
    ]
  }],
  "feedback": ["In “she” you said /s/ where /ʃ/ belongs. Pull the tongue back…"]
}
```

`status` is `good` (heard correctly), `sub` (heard as something else — `heard` names
it) or `missing` (dropped). `start_ms`/`end_ms` index into `/api/recording/{id}`,
which is why the frontend can replay a single phoneme the learner produced.

---

## How the score is built

Two independent signals, multiplied — a phone scores well only if the audio supports
it *and* it was heard as the right sound.

**1. Goodness of Pronunciation (continuous).** The reference phone sequence is
Viterbi-aligned to the CTC lattice (`app/align.py:forced_align`). Each phone gets a
frame span and the mean posterior `P(phone | frame)` over it — how strongly the
acoustics back *this* phone *here*. Also yields the timings for word/phone playback.

**2. Edit alignment (categorical).** Needleman–Wunsch between reference and recognised
phones, with a **phonetically weighted** substitution cost (`app/phones.py`). The
weighting is what makes the diagnosis readable: /θ/ heard as /s/ aligns as a
substitution (one fixable contrast) instead of a delete+insert pair (which would read
as "you said a different word").

```
good phone   →  50 + 50·q          # intelligible; the rest is acoustic quality
substitution →  q · (25 + 35·sim)  # capped well below "fair" — intelligible but wrong
dropped      →  q · 20
```

**3. Word roll-up is not a plain mean.** `word = 0.6·mean + 0.4·worst`. In a minimal
pair the whole word turns on one phone: "sink" for "think" is three perfect phones and
one ruined one, and a mean reports ~72 — a pass. Blending in the worst phone puts it
at ~46 while leaving uniformly-good words essentially untouched. This was a real bug
caught by the minimal-pair harness, and `test_scoring.py` now pins the behaviour.

Rolled up: `accuracy` (phone-count-weighted mean of word scores), `completeness`
(words actually attempted), `fluency` (speech rate + long-pause penalty), then
`overall = 0.75·accuracy + 0.10·completeness + 0.15·fluency`. For a single-word
target, fluency is dropped and its weight folded into accuracy — rhythm and pausing
are undefined for one word, so scoring them would only add noise.

Every constant lives at the top of `backend/app/scoring.py`. **They are starting
values, not calibrated ones** — tune them against `tools/selftest.py` (see below).

---

## Tuning, and what `selftest.py` can and cannot tell you

Minimal pairs are the sharpest instrument available, because the two words differ by
exactly one phone. `selftest.py` synthesises each member, scores it against **both**
spellings, and checks the correct one wins:

```
[ok  ] minimal pair: 'wine'
       vs correct text   99   vs 'vine'   46   gap  +53
       heard /w aɪ n/
       flagged /v/ at 0 (heard /w/)
```

The assertion is the **gap**, not the absolute number. Absolute scores here run low
and are not a calibration: espeak is a formant synthesiser and the model was trained
on human CommonVoice speech, so the test audio is out of domain by construction.

That domain gap also breaks some cases outright, and the harness says so rather than
averaging it away. espeak renders /θ/ as something the recogniser hears as /s/ or /f/,
and its short vowels are unstable, so clips where the recogniser did not hear the
correct word at all (`same.overall < INFORMATIVE_MIN`) carry no contrast to measure.
They are reported and skipped — they would be testing espeak, not this code:

```
informative cases 13   (skipped 3: ['thin', 'feel', 'fill'])
clear wins        10/13  (77%, need 70%)
inverted results  0   (none - required)
```

**So: `selftest.py` is a smoke test with a soft bar. `test_scoring.py` is the hard
gate.** If you tighten the scoring constants, tighten them against `test_scoring.py`
and real recordings — tuning against synthetic audio will mis-calibrate you.

For genuine calibration against human ratings the reference dataset is
**speechocean762** (CC-BY, 5000 utterances with expert phone-level scores), the
standard benchmark for this task.

### Known limits

* **espeak TTS is robotic.** Phonetically exact, which makes it a good *reference*,
  but not human. Swap `app/tts.py` for a neural TTS (Piper — which also uses espeak
  for its G2P) if you want natural ideal audio; the API contract does not change.
* **The wav2vec2 checkpoint is multilingual and zero-shot.** Left unconstrained it
  decodes English audio into other languages' phones — Mandarin tone-marked vowels
  (`i5`, `ei5`) and `ɕ` turned up regularly before this was fixed. `asr.recognize`
  now masks the logits to the espeak en-us inventory (derived at runtime in
  `g2p.en_inventory`) plus the current phrase's phones, which both cleans the
  transcript and renormalises the posteriors the GOP scores are read from.
* It is better at *which phone* than at *how good a phone*, so GOP values are noisier
  than a dedicated English acoustic model would give. Fine-tuning on L2 English speech
  is the upgrade path.

---

## Layout

```
backend/app/
  config.py    espeak discovery (portable vendor/ copy, data path) + settings
  g2p.py       phonemizer → per-word reference phones
  tts.py       espeak-ng CLI → ideal audio
  asr.py       wav2vec2 phoneme CTC → phones + posteriors
  align.py     CTC forced alignment + weighted Needleman-Wunsch
  scoring.py   GOP × edit alignment → phone/word/overall scores
  phones.py    IPA normalisation, phonetic similarity, articulation hints
  audio.py     upload → 16 kHz mono float32
  lessons.py   practice content
  main.py      FastAPI routes
frontend/      vanilla JS SPA, records 16 kHz WAV in-browser
tools/
  test_scoring.py  deterministic unit tests (no audio, no model) - the regression gate
  selftest.py      whole-stack smoke test on espeak-synthesised audio
scripts/       setup_windows.ps1
vendor/        portable espeak-ng (created by the setup script)
```

The frontend encodes WAV client-side via an `AudioWorklet`, so the server never
needs ffmpeg to unwrap a webm/opus container. (`app/audio.py` will still use ffmpeg
as a fallback if a third-party client sends one.)

---

## Prior art worth reading

* [pwenker/pronunciation_trainer](https://github.com/pwenker/pronunciation_trainer) —
  closest reference: phoneme-based trainer, wav2vec2, argues the phoneme-vs-grapheme case.
* [facebook/wav2vec2-lv-60-espeak-cv-ft](https://huggingface.co/facebook/wav2vec2-lv-60-espeak-cv-ft) —
  the model used here; ["Simple and Effective Zero-shot Cross-lingual Phoneme Recognition"](https://arxiv.org/abs/2109.11680).
* [speechocean762](https://arxiv.org/pdf/2104.01378) — open corpus with expert
  phone-level pronunciation scores; the benchmark to calibrate against.
* [kaldi GOP recipe](https://github.com/kaldi-asr/kaldi/tree/master/egs/gop) — the
  original Goodness-of-Pronunciation formulation this scorer is a modern restatement of.
* [ConPCO](https://github.com/bicheng1225/ConPCO) — ICASSP 2025, GOP features for
  automatic pronunciation assessment.
* [charsiu](https://github.com/lingjzhu/charsiu) — neural forced aligner, a stronger
  alternative to the CTC alignment in `align.py`.
* [Montreal Forced Aligner](https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner) —
  the classical HMM route to the same alignment.
