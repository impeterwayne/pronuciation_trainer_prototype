# Test Audio Samples

Curated 16 kHz Mono WAV audio samples for testing the Pronunciation Trainer scoring pipeline.

Total samples: **56**

## Directory Structure

* **`words/`**: Human native recordings of core English phoneme minimal pairs (`sheep`/`ship`, `three`/`tree`, `rice`/`lice`, `very`/`berry`, etc.).
* **`sentences/`**: Human recordings of full English sentences from CMU ARCTIC (US female, US male, Scottish male) and Wikimedia Commons.
* **`synthetic/`**: Reference speech synthesized with eSpeak-NG for deterministic regression testing.
* **`manifest.json`**: JSON index of all sample files with target text, category, and metadata.

## How to Test

### 1. Test Single File via API
```bash
curl -X POST http://127.0.0.1:8000/api/assess \
  -F "text=sheep" \
  -F "audio=@samples/words/sheep.wav"
```

### 2. Run Automated Sample Assessment
```bash
python tools/test_samples.py
```
