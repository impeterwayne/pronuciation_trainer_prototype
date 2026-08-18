"""Runtime configuration + espeak-ng discovery.

espeak-ng is used twice in this project:
  * as a shared library (libespeak-ng.dll / .so) driven by `phonemizer` -> reference IPA
  * as a CLI binary (espeak-ng.exe)                                    -> "ideal" reference audio

On Windows neither is on PATH by default, so we probe the usual install dirs and
export PHONEMIZER_ESPEAK_LIBRARY ourselves before phonemizer is imported.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# --------------------------------------------------------------------------- paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# A portable copy extracted with `msiexec /a` (see scripts/setup_windows.ps1)
# takes priority: it needs no admin rights and pins the version.
VENDOR_ESPEAK = PROJECT_ROOT / "vendor" / "eSpeak NG"

_WINDOWS_ESPEAK_DIRS = [
    VENDOR_ESPEAK,
    Path(r"C:\Program Files\eSpeak NG"),
    Path(r"C:\Program Files (x86)\eSpeak NG"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "eSpeak NG",
]

_POSIX_LIB_CANDIDATES = [
    Path("/usr/lib/x86_64-linux-gnu/libespeak-ng.so.1"),
    Path("/usr/lib/libespeak-ng.so.1"),
    Path("/usr/local/lib/libespeak-ng.dylib"),
    Path("/opt/homebrew/lib/libespeak-ng.dylib"),
]


def find_espeak_library() -> Path | None:
    """Absolute path to the espeak-ng shared library, or None."""
    env = os.environ.get("PHONEMIZER_ESPEAK_LIBRARY")
    if env and Path(env).exists():
        return Path(env)

    if sys.platform == "win32":
        for d in _WINDOWS_ESPEAK_DIRS:
            for name in ("libespeak-ng.dll", "espeak-ng.dll"):
                if (d / name).exists():
                    return d / name
        return None

    for p in _POSIX_LIB_CANDIDATES:
        if p.exists():
            return p
    return None


def find_espeak_exe() -> Path | None:
    """Absolute path to the espeak-ng CLI binary, or None."""
    env = os.environ.get("ESPEAK_NG_BINARY")
    if env and Path(env).exists():
        return Path(env)

    which = shutil.which("espeak-ng") or shutil.which("espeak")
    if which:
        return Path(which)

    if sys.platform == "win32":
        for d in _WINDOWS_ESPEAK_DIRS:
            if (d / "espeak-ng.exe").exists():
                return d / "espeak-ng.exe"
    return None


def find_espeak_data() -> Path | None:
    """Directory holding `espeak-ng-data`, or None to let espeak use its default.

    A registry-installed espeak finds its own data. A portable extraction does not,
    so both the shared library and the CLI have to be told explicitly.
    """
    env = os.environ.get("ESPEAK_DATA_PATH")
    if env and (Path(env) / "espeak-ng-data").is_dir():
        return Path(env)
    for d in (find_espeak_library(), find_espeak_exe()):
        if d and (d.parent / "espeak-ng-data").is_dir():
            return d.parent
    return None


def bootstrap_espeak() -> None:
    """Make espeak discoverable by phonemizer. Call before importing phonemizer."""
    lib = find_espeak_library()
    if lib:
        os.environ.setdefault("PHONEMIZER_ESPEAK_LIBRARY", str(lib))
        if sys.platform == "win32":
            # espeak-ng.dll has sibling DLL deps; add its folder to the DLL search path.
            try:
                os.add_dll_directory(str(lib.parent))
            except (AttributeError, OSError):
                pass

    data = find_espeak_data()
    if data:
        # espeak_Initialize(path=NULL) falls back to this variable, which is how
        # the vendored copy gets its dictionaries without a registry entry.
        os.environ.setdefault("ESPEAK_DATA_PATH", str(data))


# --------------------------------------------------------------------------- settings


class Settings:
    # G2P / TTS
    lang: str = os.environ.get("PT_LANG", "en-us")
    espeak_voice: str = os.environ.get("PT_ESPEAK_VOICE", "en-us")
    tts_speed_normal: int = int(os.environ.get("PT_TTS_SPEED", "150"))
    tts_speed_slow: int = int(os.environ.get("PT_TTS_SPEED_SLOW", "85"))

    # Phoneme ASR
    model_id: str = os.environ.get("PT_MODEL_ID", "facebook/wav2vec2-lv-60-espeak-cv-ft")
    device: str = os.environ.get("PT_DEVICE", "cpu")
    sample_rate: int = 16_000
    # wav2vec2 stride: 20ms per output frame at 16kHz
    frame_ms: float = 20.0
    # Load the ASR model at startup instead of on first request.
    eager_load: bool = os.environ.get("PT_EAGER_LOAD", "0") == "1"

    # Optional neural reference audio: a local OmniVoice server (`omnivoice-server`,
    # OpenAI-compatible /v1/audio/speech). Keyless and offline by default, so the
    # espeak fallback is the only thing standing between this and no dependency.
    omnivoice_url: str = os.environ.get("PT_OMNIVOICE_URL", "http://127.0.0.1:8880/v1")
    omnivoice_model: str = os.environ.get("PT_OMNIVOICE_MODEL", "omnivoice")
    omnivoice_voice: str = os.environ.get("PT_OMNIVOICE_VOICE", "nova")
    # OmniVoice's voice *design* string - comma-separated attributes, e.g.
    # "female, us accent, young adult". Outranks the voice preset when set.
    omnivoice_description: str = os.environ.get("PT_OMNIVOICE_DESCRIPTION", "")
    omnivoice_slow_speed: float = float(os.environ.get("PT_OMNIVOICE_SLOW_SPEED", "0.7"))
    # Only needed if the server was started with --api-key.
    omnivoice_api_key: str = os.environ.get("OMNIVOICE_API_KEY", "")

    # Optional LLM coaching. The key is normally supplied per-request from the UI;
    # this env var is the fallback for headless use and is never sent to the browser.
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_chat_model: str = os.environ.get("PT_OPENAI_CHAT_MODEL", "gpt-4o-mini")

    # Scoring thresholds (also used by the frontend for colouring)
    good_threshold: int = 80
    fair_threshold: int = 60

    cache_dir: Path = Path(os.environ.get("PT_CACHE_DIR", Path(__file__).parent.parent / ".cache"))


settings = Settings()
settings.cache_dir.mkdir(parents=True, exist_ok=True)
