# Live Translator

Real-time speech-to-text translation application for Linux. Captures system audio, transcribes it using Whisper, and translates to your target language using local LLMs (Ollama) or cloud APIs.

## Features

- **Real-time audio capture** from system audio (PipeWire/PulseAudio)
- **Speech-to-text** using Faster-Whisper (local, offline, CPU/CUDA)
- **Translation** via Ollama (local), OpenAI, or Anthropic
- **Transcription-only mode** - writes recognized speech to logs without translation
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
- Ollama (for local translation)

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
# Ensure wpctl and pw-record are available
```

### 2. Create virtual environment and install Python dependencies

```bash
cd live_translator
python3 -m venv venv
source venv/bin/activate

# Install core dependencies
pip install faster-whisper ollama PyGObject pyaudio

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

### 3. Install Ollama and a translation model

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
  -m, --ollama-model     Ollama model for translation (default: mistral:7b)
  -s, --source-language  Source language code (default: en)
  -t, --target-language  Target language name (default: Russian)
  -d, --device           Device for Whisper: cpu, cuda (default: cpu)
  --compute-type         Compute type: int8, float16, float32 (default: int8)
  --transcription-only   Transcribe and log without translation
```

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

# Log-only transcription mode (no translation)
./start.sh --transcription-only
```

### Analyze meeting/session logs

If one meeting produced several session logs (for example, app restarts), use:

```bash
# Analyze logs created in a 3-hour window from a meeting start time
live-translator-log-summary \
  --session-start "2026-02-03 14:00" \
  --window-minutes 180

# Or analyze latest N logs
live-translator-log-summary --latest 4
```

The report includes:
- What was done
- Important questions
- Important client remarks
- Open points and next steps

## Settings

Click the gear icon in the window header to open settings:

### Appearance
- Window opacity
- Background color
- Original/translated text colors
- Font sizes

### Transcription
- Whisper model size
- Device (CPU/CUDA)
- Compute type
- Source language
- Speaker diarization (local, no API key needed)
- Performance tuning (beam size, silence duration, etc.)
- Transcription-only mode (disable translation and keep logging)
- Auto language detection with expected languages list

### Translation
- Provider (Ollama, OpenAI, Anthropic)
- Model name
- Target language
- Custom prompt template

### Logging
- Enable/disable translation logging
- Custom log directory
- Log original and translated text separately

### AI Assistant
- Enable/disable AI assistant
- Auto-detect and answer questions from transcription
- Context-based summaries and learning help

Settings are saved to `~/.config/live-translator/settings.json`
Most settings and mode switches are applied immediately without restarting the app.

## Recommended Models

### Transcription (Whisper)

For optimal performance with different VRAM constraints:

- **tiny** (39M) - Fastest, lowest quality, ~1GB
- **base** (74M) - Good balance, ~2GB - **RECOMMENDED for CPU**
- **small** (244M) - Better accuracy, ~2.5GB
- **medium** (769M) - High accuracy, ~4GB - **RECOMMENDED for CUDA**
- **large-v3** (1.5B) - Best accuracy, ~8GB - **For CUDA with 8GB+ VRAM**

### Translation (Ollama)

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
├── main.py              # Main application entry point
├── overlay.py           # GTK4 overlay window
├── audio_capture.py     # System audio capture (PipeWire/PulseAudio)
├── mic_capture.py       # Microphone audio capture
├── transcriber.py       # Speech-to-text with Faster-Whisper
├── translator.py        # Translation via Ollama/OpenAI/Anthropic
├── tts_engine.py        # Text-to-speech synthesis
├── virtual_output.py    # Virtual audio output for TTS
├── reverse_mode.py      # Reverse translation mode (speech-to-speech)
├── qa_assistant.py      # AI assistant for Q&A
├── logger.py            # Session logging
├── settings.py          # Settings management
├── settings_dialog.py   # Settings UI dialog
└── start.sh             # Launch script
```

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
- Ensure Ollama is running: `ollama serve`
- Check the model is pulled: `ollama list`
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
