"""Detect what this machine can actually run, and recommend settings to match.

Recommendations are deliberately conservative: transcription and a local LLM share
one GPU, so the Whisper budget is whatever is left after the translation model.
"""
import os
import re
import shutil
import subprocess

from live_translator.processing.whisper_models import WHISPER_MODELS, estimated_vram_mb

# Headroom for the CUDA context, cuDNN workspaces and fragmentation.
SAFETY_MARGIN_MB = 512
# Approximate resemblyzer speaker-encoder footprint.
DIARIZATION_MB = 400

DIARIZATION_MIN_FREE_MB = 1024


def _run(command, timeout=10):
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _cpu_cores():
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def _total_ram_gb():
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return None


def _compute_types():
    """Compute types ctranslate2 actually supports here, keyed by device."""
    try:
        import ctranslate2
    except ImportError:
        return {}, 0
    supported = {}
    for device in ("cpu", "cuda"):
        try:
            supported[device] = set(ctranslate2.get_supported_compute_types(device))
        except Exception:
            supported[device] = set()
    try:
        devices = ctranslate2.get_cuda_device_count()
    except Exception:
        devices = 0
    return supported, devices


def detect_hardware():
    """Snapshot of CPU, RAM and GPU capability. Never raises."""
    compute_types, cuda_devices = _compute_types()
    hardware = {
        "cpu_cores": _cpu_cores(),
        "total_ram_gb": _total_ram_gb(),
        "cuda_devices": cuda_devices,
        "compute_types": compute_types,
        "gpu_name": None,
        "vram_total_mb": None,
        "vram_free_mb": None,
    }
    if not shutil.which("nvidia-smi"):
        return hardware
    output = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                   "--format=csv,noheader,nounits"])
    if not output or not output.strip():
        return hardware
    fields = [field.strip() for field in output.strip().splitlines()[0].split(",")]
    if len(fields) == 3:
        hardware["gpu_name"] = fields[0]
        for key, value in (("vram_total_mb", fields[1]), ("vram_free_mb", fields[2])):
            if re.fullmatch(r"\d+", value):
                hardware[key] = int(value)
    return hardware


def describe_hardware(hardware):
    """One-line human summary for the settings UI."""
    parts = [f"{hardware['cpu_cores']} CPU cores"]
    if hardware.get("total_ram_gb"):
        parts.append(f"{hardware['total_ram_gb']:g} GB RAM")
    if hardware.get("gpu_name") and hardware.get("vram_total_mb"):
        free = hardware.get("vram_free_mb")
        vram = f"{hardware['gpu_name']} {hardware['vram_total_mb'] / 1024:.1f} GB VRAM"
        if free is not None:
            vram += f" ({free / 1024:.1f} GB free now)"
        parts.append(vram)
    elif hardware.get("cuda_devices"):
        parts.append("CUDA available")
    else:
        parts.append("no CUDA GPU detected")
    return " · ".join(parts)


def local_llm_footprint_mb(provider, model, profile=None):
    """VRAM a local translation model needs, so Whisper does not claim it.

    Returns 0 for remote or disabled providers. Network failures return 0 rather
    than blocking a recommendation.
    """
    if provider not in ("ollama", "lmstudio") or not model:
        return 0
    try:
        from live_translator.ai.providers import create_adapter
        adapter = create_adapter(provider, **(profile or {}))
        if provider == "lmstudio":
            for entry in adapter.model_details():
                if entry.get("key") == model and entry.get("size_bytes"):
                    return int(entry["size_bytes"] / 1024 / 1024)
        else:
            for entry in adapter.request("/api/tags").get("models", []):
                if (entry.get("name") or entry.get("model")) == model and entry.get("size"):
                    return int(entry["size"] / 1024 / 1024)
    except Exception:
        return 0
    return 0


# Poor fits for live translation regardless of size: code and embedding models, and
# reasoning models, which emit a <think> block before answering. Measured on a 4070:
# qwen3 averaged 26.9s per sentence against 1.5s for mistral:7b.
_AVOID = ("code", "embed", "-r1", "reasoner", "reasoning", "qwq", "thinking", "qwen3:")
# A translation model smaller than this is not worth the VRAM it costs.
MIN_USEFUL_LLM_MB = 2048
# Ollama reports file size; runtime adds a KV cache and runner overhead.
OLLAMA_RUNTIME_FACTOR = 1.2
# large-* is accurate but too slow for live captions on consumer GPUs.
LIVE_MODEL_ORDER = ["medium", "small", "base", "tiny"]
# Sharing a GPU: below `small` the GPU buys little, so prefer CPU transcription
# and give the card to the translation model.
SHARED_GPU_MODEL_ORDER = ["medium", "small"]
# Slack beyond SAFETY_MARGIN_MB before calling a two-model plan viable. Both figures
# are estimates, so a plan that only just fits will not survive a real load.
MIN_SLACK_MB = 512


def recommend_transcription(hardware, llm_reserve_mb=0):
    """Recommended transcription settings plus the reasoning behind them."""
    cores = hardware["cpu_cores"]
    total = hardware.get("vram_total_mb")
    cuda = bool(hardware.get("cuda_devices")) and total is not None
    reasons = []

    if not cuda:
        model = "small" if cores >= 12 else "base" if cores >= 6 else "tiny"
        reasons.append(f"No usable CUDA GPU, so Whisper runs on {cores} CPU cores.")
        reasons.append(f"{model} + int8 balances accuracy and latency for this CPU.")
        reasons.append("Speaker diarization off: it costs CPU time needed for captions.")
        return {"whisper_model": model, "device": "cpu", "compute_type": "int8",
                "enable_diarization": False,
                "beam_size": 1 if cores < 6 else 2 if cores < 12 else 3}, reasons

    # Plan against total capacity, not what happens to be free: a recommendation
    # should describe the setup to run, and say what to unload to get there.
    budget = total - SAFETY_MARGIN_MB - llm_reserve_mb
    if llm_reserve_mb:
        reasons.append(f"Reserved {llm_reserve_mb / 1024:.1f} GB for the translation model "
                       "sharing this GPU.")
    reasons.append(f"Whisper budget: {max(budget, 0) / 1024:.1f} GB of "
                   f"{total / 1024:.1f} GB total.")

    supported = hardware.get("compute_types", {}).get("cuda", set())
    for compute_type in ("float16", "int8"):
        if compute_type not in supported:
            continue
        for model in LIVE_MODEL_ORDER:
            need = estimated_vram_mb(model, compute_type)
            if need > budget:
                continue
            diarization = budget - need >= DIARIZATION_MB
            reasons.append(f"{model} + {compute_type} is the largest live-capable model "
                           f"that fits (~{need / 1024:.1f} GB).")
            reasons.append("Speaker diarization on: enough VRAM remains." if diarization
                           else "Speaker diarization off: no VRAM left after Whisper.")
            return {"whisper_model": model, "device": "cuda", "compute_type": compute_type,
                    "enable_diarization": diarization,
                    "beam_size": 3 if compute_type == "float16" else 2}, reasons

    reasons.append("The translation model leaves too little VRAM for GPU transcription, "
                   "so Whisper runs on CPU. Use a smaller translation model to free the GPU.")
    return {"whisper_model": "base" if cores >= 6 else "tiny", "device": "cpu",
            "compute_type": "int8", "enable_diarization": False, "beam_size": 2}, reasons


def _installed_local_models(profiles=None):
    """(provider, model, estimated runtime MB) for every reachable local provider."""
    profiles = profiles or {}
    from live_translator.ai.providers import create_adapter
    found = []
    for provider in ("lmstudio", "ollama"):
        try:
            adapter = create_adapter(provider, **(profiles.get(provider) or {}))
            if provider == "lmstudio":
                for entry in adapter.model_details():
                    size = int((entry.get("size_bytes") or 0) / 1024 / 1024)
                    found.append((provider, entry["key"], size))
            else:
                for entry in adapter.request("/api/tags").get("models", []):
                    name = entry.get("name") or entry.get("model")
                    if name:
                        found.append((provider, name,
                                      int((entry.get("size") or 0) / 1024 / 1024
                                          * OLLAMA_RUNTIME_FACTOR)))
        except Exception:
            continue
    return found


def _refine_lmstudio(candidates, profiles, context_length):
    """Replace disk sizes with lms load --estimate-only figures where available."""
    from live_translator.ai.providers import create_adapter
    try:
        adapter = create_adapter("lmstudio", **((profiles or {}).get("lmstudio") or {}))
    except Exception:
        return candidates
    refined = []
    for provider, model, size in candidates:
        if provider == "lmstudio":
            estimate = adapter.estimate_load_mb(model, context_length)
            if estimate:
                size = estimate
        refined.append((provider, model, size))
    return refined


def recommend_setup(hardware, profiles=None, context_length=8192, refine=True):
    """Plan transcription and translation together for one shared GPU."""
    from live_translator.ai.providers.lmstudio_catalog import fitting_models

    total = hardware.get("vram_total_mb")
    cuda = bool(hardware.get("cuda_devices")) and total is not None
    installed = _installed_local_models(profiles)
    if cuda and refine:
        installed = _refine_lmstudio(installed, profiles, context_length)
    installed = [c for c in installed
                 if c[1] and not any(t in c[1].lower() for t in _AVOID) and c[2]]

    if not cuda:
        transcription, reasons = recommend_transcription(hardware, 0)
        ram_budget = int((hardware.get("total_ram_gb") or 8) * 1024 * 0.4)
        fits = [c for c in installed if c[2] <= ram_budget]
        translation = min(fits, key=lambda c: c[2]) if fits else None
        reasons.append(f"No GPU: the translation model runs in RAM, budget "
                       f"{ram_budget / 1024:.1f} GB.")
        if translation:
            reasons.append(f"{translation[1]} on {translation[0]} is the lightest installed "
                           f"model, which matters most without a GPU.")
        return _result(transcription, translation, reasons, [], hardware)

    usable = total - SAFETY_MARGIN_MB
    supported = hardware.get("compute_types", {}).get("cuda", set())
    best = None
    for compute_type in ("float16", "int8"):
        if compute_type not in supported:
            continue
        for model in SHARED_GPU_MODEL_ORDER:
            whisper_mb = estimated_vram_mb(model, compute_type)
            llm_budget = usable - whisper_mb
            if llm_budget < MIN_USEFUL_LLM_MB:
                continue
            # Keep real slack: both numbers are estimates, not measurements.
            fits = [c for c in installed if c[2] + MIN_SLACK_MB <= llm_budget]
            if fits and best is None:
                best = (model, compute_type, whisper_mb, llm_budget,
                        max(fits, key=lambda c: c[2]))
                break
        if best:
            break

    if best:
        model, compute_type, whisper_mb, llm_budget, translation = best
        diarization = llm_budget - translation[2] >= DIARIZATION_MB
        reasons = [
            f"{total / 1024:.1f} GB VRAM total, {usable / 1024:.1f} GB usable after headroom.",
            f"Whisper {model} + {compute_type}: ~{whisper_mb / 1024:.1f} GB.",
            f"Leaves {llm_budget / 1024:.1f} GB for translation; {translation[1]} on "
            f"{translation[0]} needs ~{translation[2] / 1024:.1f} GB.",
            "Speaker diarization on: VRAM remains." if diarization
            else "Speaker diarization off: no VRAM left once both models load.",
        ]
        transcription = {"whisper_model": model, "device": "cuda",
                         "compute_type": compute_type, "enable_diarization": diarization,
                         "beam_size": 3 if compute_type == "float16" else 2}
        return _result(transcription, translation, reasons, [], hardware)

    # Nothing installed fits alongside Whisper: recommend CPU-safe transcription
    # and suggest models small enough to change that.
    smallest_whisper = estimated_vram_mb("small", "int8")
    llm_budget = usable - smallest_whisper - MIN_SLACK_MB
    suggestions = fitting_models(llm_budget)
    reasons = [
        f"{total / 1024:.1f} GB VRAM total, {usable / 1024:.1f} GB usable after headroom.",
        f"No installed translation model fits alongside Whisper "
        f"(budget {llm_budget / 1024:.1f} GB with the small model).",
    ]
    if installed:
        lightest = min(installed, key=lambda c: c[2])
        reasons.append(f"Lightest installed is {lightest[1]} on {lightest[0]} at "
                       f"~{lightest[2] / 1024:.1f} GB.")
    reasons.append("Download a smaller translation model, or run Whisper on CPU and give "
                   "the whole GPU to the translation model.")
    transcription = {"whisper_model": "small", "device": "cuda", "compute_type": "int8",
                     "enable_diarization": False, "beam_size": 2}
    return _result(transcription, None, reasons, suggestions, hardware)


def _result(transcription, translation, reasons, suggestions, hardware):
    return {
        "hardware": describe_hardware(hardware),
        "transcription": transcription,
        "translation": ({"provider": translation[0], "model": translation[1]}
                        if translation else None),
        "reasons": reasons,
        "suggestions": suggestions,
    }
