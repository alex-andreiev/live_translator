"""Whisper model guidance. Weight estimates are FP16 parameters, not download sizes.
Reference: https://github.com/openai/whisper#available-models-and-languages
"""
WHISPER_MODELS = {
    "tiny": (39, 1, "Fastest, lowest accuracy. Useful for testing and limited CPUs."),
    "base": (74, 1, "Fast, basic accuracy. Recommended starting point for CPU live captions."),
    "small": (244, 2, "Better accuracy with moderate latency. Try on a fast CPU or GPU."),
    "medium": (769, 5, "Higher accuracy, slower inference. Prefer a GPU for live speech."),
    "large-v2": (1550, 10, "High accuracy, high memory use. Older large multilingual model."),
    "large-v3": (1550, 10, "Strong multilingual accuracy. Prefer a GPU; latency may be high."),
}


def model_description(name, device="cpu"):
    if name not in WHISPER_MODELS:
        return "Custom model. Size and performance depend on its model files."
    parameters, vram, description = WHISPER_MODELS[name]
    weight_mb = parameters * 2
    weights = f"{weight_mb / 1000:.2f} GB" if weight_mb >= 1000 else f"{weight_mb} MB"
    return (f"{parameters:,} million parameters · ~{weights} FP16 weights\n"
            f"Reference GPU memory: ~{vram} GB (OpenAI Whisper).\n{description}\n"
            "Multilingual, including English, Ukrainian and Russian. Actual faster-whisper download size, "
            "RAM/VRAM and speed vary with quantization, hardware and audio. INT8 can reduce memory.\n"
            + ("CPU recommendation: start with base + int8; use tiny if captions lag."
               if device == "cpu" else "GPU recommendation: try small + float16, then larger models if memory and latency allow."))


# Rough runtime footprint: weights at the compute type's bytes-per-parameter, plus
# activations/encoder overhead. Not exact — see model_description's caveats.
_BYTES_PER_PARAM = {"int8": 1.1, "int8_float16": 1.1, "int8_float32": 1.1,
                    "int8_bfloat16": 1.1, "float16": 2.2, "bfloat16": 2.2, "float32": 4.4}
_OVERHEAD_MB = 300


def estimated_vram_mb(name, compute_type="int8"):
    """Approximate MB the model occupies at this compute type, or None if unknown."""
    if name not in WHISPER_MODELS:
        return None
    parameters = WHISPER_MODELS[name][0]
    return int(parameters * _BYTES_PER_PARAM.get(compute_type, 2.2) + _OVERHEAD_MB)


def is_model_cached(name):
    """Whether faster-whisper can load this model without downloading it.

    A first load pulls 100 MB - 3 GB with no progress in the UI, so callers warn
    before starting one. Unknown/custom ids return True: nothing useful to say.
    """
    if name not in WHISPER_MODELS:
        return True
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return True
    from pathlib import Path
    snapshots = Path(HF_HUB_CACHE) / f"models--Systran--faster-whisper-{name}" / "snapshots"
    if not snapshots.is_dir():
        return False
    # A cancelled download still leaves the small files and an .incomplete blob
    # behind, so require the weights themselves to be linked into a snapshot.
    return any((revision / "model.bin").exists()
               for revision in snapshots.iterdir() if revision.is_dir())
