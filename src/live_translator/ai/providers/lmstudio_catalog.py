"""Suggested LM Studio models for translation, and the lms commands to set them up.

Entries are SEARCH TERMS for `lms get`, not exact repository ids: LM Studio resolves a
term to the quantization that suits the machine. Sizes are approximate for a 4-bit GGUF
build and are only used to shortlist candidates -- `lms load --estimate-only` gives the
authoritative figure for a downloaded model, including the KV cache for a context length.
"""

# (search term, parameters, approx 4-bit GB, note)
TRANSLATION_MODELS = [
    ("qwen2.5-3b-instruct", "3B", 2.0,
     "Smallest solid multilingual option. Leaves the most room for Whisper."),
    ("qwen3-4b", "4B", 2.5,
     "Recent small multilingual model. Good latency for live captions."),
    ("mistral-7b-instruct", "7B", 4.4,
     "Fast and reliable general translator."),
    ("qwen2.5-7b-instruct", "7B", 4.7,
     "Strong multilingual quality, including Russian and Ukrainian."),
    ("llama-3.1-8b-instruct", "8B", 4.9,
     "Higher accuracy, noticeably slower than a 3-4B model."),
    ("aya-expanse-8b", "8B", 5.1,
     "Purpose-built for multilingual work across 23 languages."),
    ("gemma-2-9b-it", "9B", 5.8,
     "Best quality here, but needs a GPU with room to spare."),
]

# Live captions send short prompts; a large context mostly inflates the KV cache.
RECOMMENDED_CONTEXT = 8192


def fitting_models(budget_mb):
    """Catalog entries whose approximate size fits the budget, largest first."""
    if not budget_mb or budget_mb <= 0:
        return []
    return [entry for entry in sorted(TRANSLATION_MODELS, key=lambda e: -e[2])
            if entry[2] * 1024 <= budget_mb]


def describe_catalog(budget_mb=None):
    """Rendered suggestion list, annotated against the available budget."""
    lines = []
    for term, parameters, size, note in TRANSLATION_MODELS:
        marker = ""
        if budget_mb:
            marker = "  ✓ fits" if size * 1024 <= budget_mb else "  ✗ too large"
        lines.append(f"{term} ({parameters}, ~{size:.1f} GB){marker}\n    {note}")
    return "\n".join(lines)


def setup_commands(model=None, context_length=RECOMMENDED_CONTEXT, gpu="max"):
    """(command, explanation) pairs for setting up LM Studio from a terminal."""
    target = model or "<model>"
    commands = [
        ("lms ls", "List models already downloaded, with their sizes."),
        ("lms ps", "Show which models are loaded and at what context length."),
        (f"lms get {target}", "Search and download a model. Add -y to accept the "
                              "variant chosen for your hardware."),
        (f"lms load {target} --context-length {context_length} --estimate-only",
         "Report the VRAM this model needs at that context WITHOUT loading it. "
         "Check this before loading when the GPU is shared with Whisper."),
        ("lms server start", "Start the local server on port 1234."),
        (f"lms load {target} --context-length {context_length} --gpu {gpu}",
         f"Load the model. A smaller context costs less VRAM; {context_length} is ample "
         "for live captions, which send short prompts."),
        ("lms unload --all", "Free the GPU. Run this before loading a different model, "
                             "otherwise the second load competes for VRAM and fails."),
        ("lms server stop", "Stop the server. This also cuts off other apps using it."),
    ]
    return commands


def describe_commands(model=None, context_length=RECOMMENDED_CONTEXT):
    return "\n".join(f"$ {command}\n    {explanation}"
                     for command, explanation in setup_commands(model, context_length))
