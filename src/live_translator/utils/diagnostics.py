"""Preflight checks: is this machine configured to run the app, and do the saved
settings actually suit it?

Every check reports OK, WARN or FAIL. FAIL means the feature cannot work as
configured; WARN means it works but something is degraded or optional is missing.
Each result carries a concrete fix so the user is never told only that it is broken.
"""
import os
import shutil
import subprocess
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"


class Check:
    def __init__(self, name, status, detail, fix=""):
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix

    def __repr__(self):
        return f"<Check {self.name} {self.status}>"

    def line(self):
        icon = {OK: "PASS", WARN: "WARN", FAIL: "FAIL"}[self.status]
        text = f"[{icon}] {self.name}: {self.detail}"
        return f"{text}\n       fix: {self.fix}" if self.fix and self.status != OK else text


def _import(module):
    try:
        __import__(module)
        return True
    except Exception:
        return False


def check_dependencies():
    """Python packages the app needs, and the optional ones."""
    results = []
    required = [("faster_whisper", "pip install -e ."),
                ("ctranslate2", "pip install -e ."),
                ("numpy", "pip install -e .")]
    for module, fix in required:
        present = _import(module)
        results.append(Check(f"Python package: {module}",
                             OK if present else FAIL,
                             "installed" if present else "missing", "" if present else fix))

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        results.append(Check("GTK 4",
                             OK, f"{Gtk.get_major_version()}.{Gtk.get_minor_version()} available"))
    except Exception as exc:
        results.append(Check("GTK 4", FAIL, f"unavailable ({exc})",
                             "sudo apt-get install gir1.2-gtk-4.0 libgirepository-2.0-dev"))

    optional = [("resemblyzer", "speaker diarization", 'pip install "live-translator[diarization]"'),
                ("anthropic", "the Anthropic provider", 'pip install "live-translator[anthropic]"')]
    for module, purpose, fix in optional:
        present = _import(module)
        results.append(Check(f"Optional: {module}", OK if present else WARN,
                             "installed" if present else f"missing — {purpose} unavailable",
                             "" if present else fix))
    return results


def check_audio():
    """Capture backend and a usable system-audio source."""
    results = []
    recorder = next((tool for tool in ("pw-record", "parec") if shutil.which(tool)), None)
    results.append(Check("Audio capture backend",
                         OK if recorder else FAIL,
                         f"{recorder} found" if recorder else "neither pw-record nor parec found",
                         "" if recorder else "Install pipewire-utils (or pulseaudio-utils)."))

    lister = next((tool for tool in ("pw-dump", "pactl") if shutil.which(tool)), None)
    results.append(Check("Audio device listing", OK if lister else WARN,
                         f"{lister} found" if lister else "no pw-dump or pactl",
                         "" if lister else "Install pipewire-utils; without it the microphone "
                                           "list in Settings stays empty."))

    if shutil.which("wpctl"):
        try:
            output = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                                    capture_output=True, text=True, timeout=10)
            found = output.returncode == 0 and "node.name" in output.stdout
        except (OSError, subprocess.TimeoutExpired):
            found = False
        results.append(Check("System audio monitor", OK if found else WARN,
                             "default sink detected" if found else "no default sink reported",
                             "" if found else "Start playback and ensure PipeWire is running; "
                                              "without a monitor there is nothing to transcribe."))
    return results


def check_gpu(settings):
    """CUDA availability, and whether the configured device/compute type work."""
    results = []
    device = settings.get("transcription", "device", "cpu")
    compute = settings.get("transcription", "compute_type", "int8")
    try:
        import ctranslate2
        devices = ctranslate2.get_cuda_device_count()
        supported = set(ctranslate2.get_supported_compute_types(device))
    except Exception as exc:
        results.append(Check("CUDA runtime", WARN, f"could not query ctranslate2 ({exc})",
                             "Reinstall faster-whisper."))
        return results

    if device == "cuda":
        results.append(Check("CUDA device", OK if devices else FAIL,
                             f"{devices} device(s)" if devices else "transcription is set to cuda "
                                                                   "but no CUDA device is usable",
                             "" if devices else "Install CUDA and cuDNN, or set Device to cpu "
                                                "in Settings -> Transcription."))
        if devices and not _cudnn_present():
            results.append(Check("cuDNN libraries", WARN,
                                 "cuDNN not found on the library path",
                                 "faster-whisper needs cuDNN for CUDA. start.sh adds the bundled "
                                 "copy; if loading fails, pip install nvidia-cudnn-cu12."))
    else:
        results.append(Check("CUDA device", OK,
                             f"{devices} device(s) available, transcription set to cpu"
                             if devices else "running on cpu"))

    results.append(Check(f"Compute type '{compute}' on {device}",
                         OK if compute in supported else FAIL,
                         "supported" if compute in supported else
                         f"not supported; this device offers {', '.join(sorted(supported))}",
                         "" if compute in supported else
                         "Change Compute Type in Settings -> Transcription."))
    return results


def _cudnn_present():
    if any("cudnn" in name.lower() for name in os.environ.get("LD_LIBRARY_PATH", "").split(":")):
        return True
    for root in (Path(__file__).resolve().parents[3] / "venv/lib", Path("/usr/lib"),
                 Path("/usr/local/lib")):
        try:
            if root.is_dir() and any(root.rglob("libcudnn*.so*")):
                return True
        except OSError:
            continue
    return False


def check_models(settings):
    """Whether the configured Whisper model is present and the settings fit the GPU."""
    from live_translator.processing.whisper_models import (
        WHISPER_MODELS, estimated_vram_mb, is_model_cached)
    from live_translator.utils.hardware import (
        detect_hardware, local_llm_footprint_mb, SAFETY_MARGIN_MB)

    results = []
    model = settings.get("transcription", "whisper_model", "base")
    compute = settings.get("transcription", "compute_type", "int8")
    device = settings.get("transcription", "device", "cpu")

    if model not in WHISPER_MODELS:
        results.append(Check("Whisper model", WARN, f"'{model}' is not a known model id",
                             "Pick a model in Settings -> Transcription."))
    cached = is_model_cached(model)
    results.append(Check("Whisper model downloaded", OK if cached else WARN,
                         f"'{model}' is cached" if cached else
                         f"'{model}' is not downloaded; first run fetches it (up to ~3 GB)",
                         "" if cached else "Start the app and wait, or choose a smaller model."))

    hardware = detect_hardware()
    total = hardware.get("vram_total_mb")
    if not total or device != "cuda":
        return results

    whisper_mb = estimated_vram_mb(model, compute) or 0
    provider = settings.get("translation", "provider", "ollama")
    profile = (settings.get("providers", provider, {}) or {})
    llm_mb = local_llm_footprint_mb(provider, settings.get("translation", "model", ""), profile)
    needed = whisper_mb + llm_mb + SAFETY_MARGIN_MB
    if llm_mb:
        detail = (f"Whisper ~{whisper_mb / 1024:.1f} GB + translation ~{llm_mb / 1024:.1f} GB "
                  f"+ {SAFETY_MARGIN_MB / 1024:.1f} GB headroom = {needed / 1024:.1f} GB "
                  f"of {total / 1024:.1f} GB")
    else:
        detail = (f"Whisper ~{whisper_mb / 1024:.1f} GB of {total / 1024:.1f} GB "
                  "(translation model not local or not measurable)")
    results.append(Check("VRAM budget", OK if needed <= total else FAIL, detail,
                         "" if needed <= total else
                         "Use a smaller Whisper model or translation model, or move Whisper to "
                         "cpu. Settings -> Transcription -> Recommend for this machine does this."))
    return results


def check_translation(settings):
    """Whether the configured translation provider is reachable and has the model."""
    from live_translator.ai.providers import create_adapter, ProviderError
    provider = settings.get("translation", "provider", "ollama")
    model = settings.get("translation", "model", "")
    if provider == "none":
        return [Check("Translation provider", OK,
                      "disabled — transcription only, no translation will be produced")]
    if not model:
        return [Check("Translation provider", FAIL, f"{provider} selected but no model set",
                      "Pick a model in Settings -> Translation.")]

    profile = (settings.get("providers", provider, {}) or {})
    try:
        adapter = create_adapter(provider, **profile)
        models = adapter.list_models()
    except ProviderError as exc:
        return [Check("Translation provider", FAIL, f"{provider}: {exc}",
                      "Check the server is running and the connection settings in "
                      "Settings -> Translation (Refresh / test).")]
    except Exception:
        return [Check("Translation provider", FAIL, f"{provider}: could not be queried",
                      "Check the server and connection settings.")]

    known = model in models
    return [Check("Translation provider", OK, f"{provider} reachable, {len(models)} models"),
            Check("Translation model", OK if known else WARN,
                  f"'{model}' is available" if known else
                  f"'{model}' was not in the provider's list",
                  "" if known else "Refresh / test in Settings -> Translation and pick a "
                                   "listed model, or download it in the provider.")]


def check_logging(settings):
    path = Path(os.path.expanduser(settings.get("logging", "log_path",
                                                "~/.local/share/live-translator/logs")))
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("")
        probe.unlink()
        return [Check("Log directory", OK, f"writable ({path})")]
    except OSError as exc:
        return [Check("Log directory", WARN, f"not writable: {exc}",
                      "Choose another directory in Settings -> Logging.")]


def run_checks(settings=None):
    """Every check, in the order a user would want to fix them."""
    if settings is None:
        from live_translator.utils.settings import get_settings
        settings = get_settings()
    results = []
    for group in (check_dependencies, check_audio):
        results.extend(group())
    for group in (check_gpu, check_models, check_translation, check_logging):
        try:
            results.extend(group(settings))
        except Exception as exc:  # a broken check must not hide the others
            name = getattr(group, "__name__", "check")
            results.append(Check(name, WARN, f"check failed to run: {exc}"))
    return results


def summarize(results):
    failed = sum(r.status == FAIL for r in results)
    warned = sum(r.status == WARN for r in results)
    if failed:
        return (f"{failed} problem(s) will stop the app working as configured, "
                f"{warned} warning(s).")
    if warned:
        return f"No blocking problems. {warned} warning(s) — some features may be degraded."
    return "All checks passed. The system is configured correctly."


def render(results):
    return "\n".join(r.line() for r in results) + "\n\n" + summarize(results)
