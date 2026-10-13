#!/usr/bin/env python3
"""Local speech-to-text for the devlog server: Whisper (faster-whisper) on this PC; no audio leaves it.

- Model: DEVLOG_WHISPER_MODEL (default large-v3-turbo), downloaded once from Hugging Face into the HF cache.
- Device: the GPU (float16) when CUDA works, else the CPU (int8). The NVIDIA cuBLAS/cuDNN pip wheels supply the DLLs.
- Loaded on first use (or when a mic button is pressed), unloaded after DEVLOG_WHISPER_IDLE seconds idle (default 300)
  so it does not hold VRAM that ComfyUI wants.
- Language: DEVLOG_WHISPER_LANG (default en; "auto" to detect).

Install: python -m pip install --user faster-whisper nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
Try it:  python devlog_stt.py <audio file>
"""
import gc
import io
import os
import site
import sys
import threading
import time
from pathlib import Path

MODEL = os.environ.get("DEVLOG_WHISPER_MODEL", "large-v3-turbo")
LANGUAGE = os.environ.get("DEVLOG_WHISPER_LANG", "en")
IDLE_S = int(os.environ.get("DEVLOG_WHISPER_IDLE", "300"))

_lock = threading.RLock()
_state = {"model": None, "device": None, "last": 0.0, "loading": False, "error": ""}


def _cuda_dlls():
    """Make the pip-installed CUDA libraries findable (ctranslate2 loads cuBLAS/cuDNN by name at first use)."""
    dirs = []
    for base in list(site.getsitepackages()) + [site.getusersitepackages()]:
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_nvrtc/bin"):
            d = Path(base) / sub
            if d.is_dir():
                dirs.append(str(d))
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except (OSError, AttributeError):
            pass
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def status():
    return {"available": available(), "model": MODEL, "device": _state["device"], "loaded": _state["model"] is not None,
            "loading": _state["loading"], "language": LANGUAGE, "error": _state["error"]}


def _load(device):
    from faster_whisper import WhisperModel
    compute = "float16" if device == "cuda" else "int8"
    threads = max(4, (os.cpu_count() or 8) - 2) if device == "cpu" else 0
    return WhisperModel(MODEL, device=device, compute_type=compute, cpu_threads=threads)


def _ensure(prefer="cuda"):
    with _lock:
        if _state["model"] is not None:
            return _state["model"]
        _state.update(loading=True, error="")
        try:
            _cuda_dlls()
            try:
                if prefer != "cuda":
                    raise RuntimeError("cpu requested")
                import ctranslate2
                if not ctranslate2.get_cuda_device_count():
                    raise RuntimeError("no CUDA device")
                _state.update(model=_load("cuda"), device="cuda")
            except Exception:  # CUDA missing or broken: the CPU still works, just slower
                _state.update(model=_load("cpu"), device="cpu")
            _state["last"] = time.time()
            return _state["model"]
        except Exception as e:
            _state["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            _state["loading"] = False


def warm():
    """Start loading in the background (called when recording starts, so the load overlaps the speaking)."""
    if _state["model"] is None and not _state["loading"] and available():
        threading.Thread(target=lambda: _safe(_ensure), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


def transcribe(data, prompt=""):
    """Audio bytes (webm/opus, wav, mp3, ...: anything PyAV decodes) to text."""
    if not available():
        raise RuntimeError("faster-whisper is not installed")
    t0 = time.time()
    with _lock:
        model = _ensure()
        kw = dict(beam_size=5, vad_filter=True, condition_on_previous_text=False,
                  initial_prompt=(prompt or None) and prompt[:800], language=None if LANGUAGE == "auto" else LANGUAGE)
        try:
            segments, info = model.transcribe(io.BytesIO(data), **kw)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            if _state["device"] != "cuda":
                raise
            # A CUDA failure at run time (a missing DLL, an unsupported GPU): retry once on the CPU.
            _state.update(model=None, device=None, error=f"GPU failed ({type(e).__name__}: {e}); using the CPU")
            model = _ensure("cpu")
            segments, info = model.transcribe(io.BytesIO(data), **kw)
            text = " ".join(s.text.strip() for s in segments).strip()
        _state["last"] = time.time()
    return {"text": text, "seconds": round(time.time() - t0, 2), "audio_seconds": round(info.duration, 2),
            "device": _state["device"], "model": MODEL, "language": info.language}


def _reaper():
    while True:
        time.sleep(30)
        with _lock:
            if _state["model"] is not None and time.time() - _state["last"] > IDLE_S:
                _state.update(model=None, device=None)
                gc.collect()


threading.Thread(target=_reaper, daemon=True).start()

if __name__ == "__main__":
    data = Path(sys.argv[1]).read_bytes()
    for i in range(2):  # the second run shows the warm speed
        r = transcribe(data, " ".join(sys.argv[2:]))
        print(r)
