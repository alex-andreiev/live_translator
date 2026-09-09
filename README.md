# Live Translator

Real-time speech-to-text translation application for Linux. Captures system audio, transcribes it using Whisper, and translates to your target language using local LLMs (Ollama or LM Studio) or external APIs such as DeepSeek.

## Features

- **Real-time audio capture** from system audio (PipeWire/PulseAudio)
- **Speech-to-text** using Faster-Whisper (local, offline, CPU/CUDA)
- **Translation** via optional Ollama, local LM Studio, DeepSeek, OpenAI, or Anthropic; transcription-only mode is also available
- **Speaker diarization** - detects and labels different speakers (local, no API key needed)
- **Auto language detection** - skips translation when audio is in expected languages
- **GTK4 overlay window** with scrollable translation history
- **Customizable appearance** (colors, fonts, opacity)
- **Custom translation prompts** for specialized terminology
- **Performance tuning** - adjust speed/accuracy tradeoff
- **Per-session logging** - separate log file for each session
- **AI Assistant** with question detection and contextual help
- **Settings saved** to config file for persistence

## Requirements

- Linux with PipeWire or PulseAudio
- Python 3.10+
- GTK4
- Optional translation backend: Ollama, LM Studio, or an external API account

## Installation

### 1. Install system dependencies

```bash
# Ubuntu/Debian
sudo apt-get install -y \
    libgirepository-2.0-dev \
    gcc \
    libcairo2-dev \
    pkg-config \
    python3-dev \
    gir1.2-gtk-4.0 \
    libpulse-dev \
    portaudio19-dev

# For PipeWire (usually pre-installed)
# Ensure wpctl, pw-record and pw-dump are available
# (pw-dump is used to enumerate microphones; pactl works as a PulseAudio fallback)
```

### 2. Create virtual environment and install Python dependencies

```bash
cd live_translator
python3 -m venv venv
source venv/bin/activate

# Install core dependencies
pip install -e .

# Optional: for CUDA support (GPU acceleration)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Optional: for speaker diarization
pip install pyannote.audio
```

To activate the virtual environment in future sessions:
```bash
source venv/bin/activate
```

Note: The `start.sh` script automatically uses the venv, so manual activation is only needed for development.

### 3. Choose a translation provider

Open **Settings → Translation**. Ollama remains the default for existing configurations, but is optional. Select **Disabled (transcription only)** to run without an LLM. No Ollama Python package is required.

For Ollama only:

```bash
# Install Ollama (https://ollama.com)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model for translation
ollama pull mistral:7b
```

## Usage

### Basic usage

```bash
./start.sh
```

### Command-line options

```
./start.sh [options]

Options:
  -w, --whisper-model    Whisper model: tiny, base, small, medium, large-v2, large-v3
                         (default: base)
  -p, --provider         Translation provider: none, ollama, lmstudio, deepseek,
                         openai, anthropic (default: ollama). "none" transcribes
                         without translating.
  -m, --model            Model ID for the selected provider (default: mistral:7b)
                         (--ollama-model is kept as a deprecated alias)
  -s, --source-language  Source language code (default: en)
  -t, --target-language  Target language name (default: Russian)
  -d, --device           Device for Whisper: cpu, cuda (default: cpu)
  --compute-type         Compute type: int8, float16, float32 (default: int8)
```

Any option you leave out falls back to your saved settings file, then to the default
shown above, so command-line flags override the GUI settings for that run only.
Server URLs, API keys and timeouts are configured in Settings, not on the command line.

### Examples

```bash
# Default (English to Russian, base model)
./start.sh

# Use smaller/faster model
./start.sh -w tiny

# Use larger model for better accuracy
./start.sh -w small

# Translate to German
./start.sh -t German

# Use GPU (requires CUDA and cuDNN)
./start.sh -d cuda

# Transcribe only, with no translation provider
./start.sh -p none

# Use DeepSeek (key comes from Settings or DEEPSEEK_API_KEY)
./start.sh -p deepseek -m deepseek-v4-flash

# Use a model already loaded in LM Studio
./start.sh -p lmstudio -m qwen2.5-7b-instruct
```

## Settings

Click the gear icon in the window header to open settings:

### Appearance
- Window opacity
- Background color
- Original/translated text colors
- Font sizes

### Transcription
- Recommend-for-this-machine button (see below)
- Whisper parameter count, estimated FP16 weight size, reference GPU memory, characteristics, and CPU/GPU recommendations
- Device (CPU/CUDA)
- Compute type
- Source language
- Speaker diarization (local, no API key needed)
- Performance tuning (beam size, silence duration, etc.)
- Auto language detection with expected languages list

### Translation
- Provider (Disabled, Ollama, LM Studio, DeepSeek, OpenAI, Anthropic)
- Editable model ID; the model list loads automatically when you open Settings or
  switch provider, and again shortly after you edit the server URL or API key — no
  Refresh needed. If the saved model is not on the server, it says so and lists what
  is available, without overwriting the id (it may be served another way).
- Provider-specific server URL, masked API key, and request timeout
- LM Studio server start/stop/status and model load/unload
- Target language
- Custom prompt template

### Recommended settings for this machine

Both the **Transcription** and **Translation** tabs have a **Recommend for this machine**
button. It detects CPU cores, RAM, GPU and VRAM (via `ctranslate2` and `nvidia-smi`),
lists the models actually installed in Ollama and LM Studio, then plans Whisper and the
translation model *together* — they share one GPU, so the Whisper budget is whatever the
translation model leaves. It shows its reasoning and every figure it used, and changes
nothing until you press Apply or Save.

The planner deliberately keeps slack: both figures are estimates, so a plan that only
just fits is rejected rather than recommended. If no installed model fits alongside
Whisper it says so and suggests smaller ones instead of silently degrading Whisper.

The Translation tab also has an **LM Studio setup** section listing the `lms` commands
for the full lifecycle (`ls`, `ps`, `get`, `load --estimate-only`, `server start`,
`load`, `unload --all`, `server stop`) with an explanation of each, plus suggested
translation models marked as fitting or too large for your budget.

Note `lms load <model> --context-length N --estimate-only`: it reports the VRAM a model
needs at a given context *without* loading it, including the KV cache. Context length
dominates on a small card — on an 8 GB GPU a 7.5B model can need 6.4 GB at 4k context
but 8.0 GB at 32k, which leaves nothing for Whisper. Check the estimate before loading
whenever the GPU is shared, and run `lms unload --all` before loading a different model:
a second load competes with the first for VRAM and fails with `Exit code: null`.

### System Check

A **System Check** tab verifies the machine is configured and the current settings can
actually run on it, before you discover otherwise mid-session. It reports PASS / WARN /
FAIL with a concrete fix for anything that is not passing, and covers:

- Required Python packages and GTK 4; optional ones (diarization, Anthropic) as warnings
- Audio capture backend (`pw-record`/`parec`), device listing (`pw-dump`/`pactl`), and
  whether a default sink monitor exists to capture from
- CUDA device availability, cuDNN presence, and whether the selected compute type is
  supported on the selected device
- Whether the selected Whisper model is downloaded
- Whether Whisper plus the translation model actually fit in VRAM together
- Whether the translation provider is reachable and offers the configured model
- Whether the log directory is writable

It checks the settings **as currently edited**, not only what was last saved. The same
report is available headless:

```bash
./start.sh --check     # prints the report; exit status 1 if anything is blocking
```

### LM Studio model manager

The Translation tab lists LM Studio models — those already downloaded (with real sizes,
loaded state, and a measured VRAM requirement from `lms load --estimate-only`) alongside
suggested models you can download. Each row is marked ✓ fits / ! tight / ✗ too large
against the VRAM left once the selected Whisper model loads, so the verdict tracks your
transcription settings as you edit them. Buttons download (with progress and cancel),
load, unload, and set a model as the translation model.

### Logging
- Enable/disable translation logging
- Custom log directory
- Log original and translated text separately

### AI Assistant
- Enable/disable AI assistant
- Auto-detect and answer questions from transcription
- Context-based summaries and learning help

Settings are saved to `~/.config/live-translator/settings.json`

## Recommended Models

### Transcription (Whisper)

For optimal performance with different VRAM constraints:

- **tiny** (39M) - Fastest, lowest quality, ~1GB
- **base** (74M) - Good balance, ~2GB - **RECOMMENDED for CPU**
- **small** (244M) - Better accuracy, ~2.5GB
- **medium** (769M) - High accuracy, ~4GB - **RECOMMENDED for CUDA**
- **large-v3** (1.5B) - Best accuracy, ~8GB - **For CUDA with 8GB+ VRAM**

### Translation providers

| Provider | Runs | Needs a key | Notes |
|----------|------|-------------|-------|
| **Disabled** | — | No | Transcription only; no text leaves the machine |
| **Ollama** | Local | No | Optional; pull models with `ollama pull` |
| **LM Studio** | Local | No | Server and model load/unload managed from Settings |
| **DeepSeek** | External API | Yes | `deepseek-v4-flash` is the low-latency default |
| **OpenAI** | External API | Yes | Standard chat completions endpoint |
| **Anthropic** | External API | Yes | Needs `pip install 'live-translator[anthropic]'` |

Local providers keep audio-derived text on your machine. External providers receive the
transcribed text and are billed by that provider. Use **Refresh / test** in Settings to
confirm a connection and list the model IDs your account or install actually offers.

### Translation models (Ollama)

**For CUDA with 8GB VRAM:**

| Model | Size | Speed | Accuracy | Notes |
|-------|------|-------|----------|-------|
| **mistral:7b** | 4.4GB | ⚡⚡⚡ | ⭐⭐⭐ | ✅ BEST - Fast & reliable |
| **neural-chat:7b** | 4.1GB | ⚡⚡⚡ | ⭐⭐⭐ | ✅ Optimized for chat |
| **llama2:7b** | 3.8GB | ⚡⚡⚡ | ⭐⭐⭐ | ✅ Good alternative |
| **llama3:8b** | 4.7GB | ⚡⚡ | ⭐⭐⭐⭐ | ✅ Better accuracy |
| **openhermes-2.5:7b** | 4.0GB | ⚡⚡⚡ | ⭐⭐⭐ | ✅ EXCELLENT |

**For CPU (slower, but works):**
- mistral:7b (4.4GB) - Best for CPU
- llama2:7b (3.8GB) - Good alternative, smaller

**Download recommended models:**
```bash
# Best for translation - fastest and reliable
ollama pull mistral:7b

# Alternatives with good quality
ollama pull neural-chat:7b
ollama pull llama3:8b
ollama pull llama2:7b
```

**Models NOT recommended:**
- ❌ codellama:* - Specialized for code, not translation
- ❌ Models > 8GB - Will not fit in 8GB VRAM
- ❌ deepseek-r1:7b - Slow, oriented to reasoning not translation


## Project Structure

```
live_translator/
├── src/live_translator/
│   ├── app.py                    # Application entry point and CLI
│   ├── audio/
│   │   ├── capture.py            # System audio capture (PipeWire/PulseAudio)
│   │   ├── mic.py                # Microphone capture and source enumeration
│   │   └── virtual_output.py     # Virtual audio output for TTS
│   ├── processing/
│   │   ├── transcriber.py        # Speech-to-text with Faster-Whisper
│   │   ├── translator.py         # Translation through the selected provider
│   │   ├── tts_engine.py         # Text-to-speech synthesis
│   │   └── whisper_models.py     # Whisper size/characteristic reference data
│   ├── ai/
│   │   ├── api_client.py         # Provider-agnostic generation facade
│   │   ├── qa_assistant.py       # AI assistant for Q&A
│   │   └── providers/            # One adapter per integration
│   │       ├── base.py           # Shared HTTP transport and error mapping
│   │       ├── ollama.py         # Ollama native API
│   │       ├── lmstudio.py       # LM Studio chat, model and server lifecycle
│   │       ├── deepseek.py       # DeepSeek API
│   │       ├── openai.py         # OpenAI API
│   │       └── anthropic.py      # Anthropic API (optional SDK)
│   ├── modes/reverse_mode.py     # Reverse translation (speech-to-speech)
│   ├── ui/
│   │   ├── overlay.py            # GTK4 overlay window
│   │   ├── settings_dialog.py    # Settings UI dialog
│   │   └── provider_settings.py  # Reusable provider/model selector widget
│   └── utils/
│       ├── logger.py             # Session logging
│       └── settings.py           # Settings management
├── tests/                        # Adapter, settings and wiring regression tests
└── start.sh                      # Launch script
```

Each provider integration lives in its own adapter under `ai/providers/`, sharing only
the transport and error handling in `base.py`. Adding a provider means adding one
module there and one entry in the `PROVIDERS` registry; nothing else in the app needs
to know which provider is active.

## Troubleshooting

### No audio capture
- Ensure PipeWire or PulseAudio is running
- Check that `pw-record` or `parec` is available
- Verify audio is playing from a source

### Whisper model download
First run will download the Whisper model (~150MB for base). This may take a few minutes.

### CUDA memory errors
If you see "CUDA out of memory" errors:

1. **Reduce model size:**
   ```bash
   ./start.sh -w base -d cuda
   ```

2. **Switch to CPU:**
   ```bash
   ./start.sh -d cpu
   ```

3. **Use smaller translation model:**
   - In Settings → Translation, select a smaller model (4-5GB)
   - Recommended: `neural-chat:7b` or `mistral:7b`

4. **Disable speaker diarization:**
   - In Settings → Transcription, turn off "Enable Speaker Detection"
   - Diarization requires extra VRAM

5. **Reduce compute precision:**
   - In Settings → Transcription
   - Change "Compute Type" to `int8` (uses less memory)

### CUDA not detected
Ensure CUDA and cuDNN are properly installed:
```bash
# Check CUDA installation
nvidia-smi

# Install CUDA (Ubuntu/Debian)
sudo apt-get install cuda-toolkit
```

### Translation not working

First open **Settings → Translation** and click **Refresh / test** — it reports the exact
failure (unreachable server, rejected key, unknown model) instead of failing silently.
The same message is shown in the overlay status bar when a live translation fails.

- Provider is **Disabled**: that is transcription-only mode by design; pick a provider
- Ollama: ensure it is running (`ollama serve`) and the model is pulled (`ollama list`)
- LM Studio: click **Start server**, then **Load model** for the model you selected
- External APIs: check the key (Settings, or the provider's environment variable) and
  that the model ID is one the **Refresh / test** listing returned
- Try a different model in Settings → Translation
- Check "Expected Languages" setting matches your content
- If auto-detect is on, it may skip translation if language matches target

### Performance optimization
- **For faster transcription:**
  - Settings → Transcription → Beam Size: reduce to 1-2
  - Settings → Transcription → Min Silence Duration: reduce to 200ms
  - Whisper model: use `base` instead of `small`

- **For better accuracy:**
  - Increase Beam Size (3-5)
  - Use larger Whisper model (`small` or `medium`)
  - Use better translation model (`llama3:8b` instead of `mistral:7b`)

## License

MIT License

## LM Studio and external APIs

After a successful **Refresh / test**, the model field is filled in automatically when it
was empty, and a details line shows the selected model's display name, parameter count,
on-disk size, quantization, context length, whether it is currently loaded, and vision
support. Failed operations report the server's own message (for example
"Model X not found in downloaded models") rather than a bare status code.

For local LM Studio, install LM Studio and download a chat model there first. Keep LM Studio or its headless daemon running and make its `lms` CLI available on PATH (the app also checks `~/.lmstudio/bin/lms`). In **Settings → Translation**, select **LM Studio**, use `http://localhost:1234`, click **Start server**, then **Refresh / test**. Select a downloaded model and click **Load model**. **Unload model** releases its loaded instances; **Stop server** stops the shared server, including access by other applications. These controls run immediately; Apply/Save controls configuration persistence. Model management requires LM Studio's native `/api/v1/models` API. Models are downloaded through LM Studio, not this app.

For DeepSeek, select **DeepSeek API**, enter your key (or launch with `DEEPSEEK_API_KEY` set), and click **Refresh / test** to discover your account's available model IDs. The initial suggestion is `deepseek-v4-flash`; custom IDs are supported. Translation uses non-thinking mode for v4 models. External providers receive the text being translated and any assistant context sent to them; API usage is billed by the provider.

Connection profiles are shared with the AI Assistant and reverse translation. To configure a separate assistant provider, set its connection in the Translation selector first, then choose that provider/model under **AI Assistant** with **Use Translation Model** off. Switching the Translation selector retains edited connection profiles. **Use Translation Model** follows both the provider and model. Reverse translation always follows the Translation provider/model.

API key environment fallbacks: `DEEPSEEK_API_KEY`, `LM_STUDIO_API_KEY`, `OPENAI_API_KEY`, and `ANTHROPIC_API_KEY`. Keys entered in the interface are saved as plaintext in `~/.config/live-translator/settings.json`, atomically replaced with owner-only permissions (`0600`). Leave the field blank to use the environment instead. Anthropic requires `pip install 'live-translator[anthropic]'`; other adapters use Python's standard HTTP library.

Transcription changes now apply on Apply/Save without restarting: the model reloads in a
background thread and the status bar reports when it is ready. If the new model fails to
load (out of memory, for example) the previous one keeps running and the error is shown.
A model's first use downloads 100 MB - 3 GB from Hugging Face; the status bar says so
before the download starts, since it otherwise looks like the app has hung. An
interrupted download leaves an `.incomplete` blob and is correctly treated as not cached.

Whisper details show approximate weight sizes, not exact downloads or measured faster-whisper memory consumption. INT8, hardware, and audio length affect actual usage. CPU users can start with base/int8; adjust the model after checking live caption latency. Transcription setting changes require restarting the session; provider settings apply immediately.

Integration references: [LM Studio model lifecycle](https://lmstudio.ai/docs/developer/rest/load), [LM Studio CLI](https://lmstudio.ai/docs/cli), [DeepSeek API](https://api-docs.deepseek.com/), and [Whisper model reference](https://github.com/openai/whisper#available-models-and-languages).

Run adapter and settings regression tests with `PYTHONPATH=src python -m unittest discover -s tests -v`.
