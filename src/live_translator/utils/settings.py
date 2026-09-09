"""
Settings management for Live Translator
"""
import json
from copy import deepcopy
import tempfile
import os
from pathlib import Path

DEFAULT_SETTINGS = {
    "providers": {},
    "appearance": {
        "background_color": "rgba(30, 30, 30, 0.95)",
        "original_text_color": "#ffffff",
        "translated_text_color": "#4fc3f7",
        "ai_response_color": "#a5d6a7",
        "original_font_size": 14,
        "translated_font_size": 16,
        "ai_font_size": 14,
        "opacity": 0.95
    },
    "transcription": {
        "whisper_model": "base",
        "device": "cpu",
        "compute_type": "int8",
        "source_language": "en",
        "enable_diarization": False,
        "num_speakers": 0,
        "min_audio_length": 0.5,
        "beam_size": 3,
        "min_silence_duration_ms": 300,
        "speech_pad_ms": 100,
        "no_speech_threshold": 0.4,
        "audio_chunk_duration": 0.25,
        "auto_detect_language": True,
        "expected_languages": ["Russian", "Ukrainian", "English"]
    },
    "speakers": {
        "speaker_1_color": "#ff6b6b",
        "speaker_2_color": "#4ecdc4",
        "speaker_3_color": "#ffe66d",
        "speaker_4_color": "#a29bfe",
        "speaker_5_color": "#fd79a8",
        "speaker_6_color": "#81ecec",
        "unknown_speaker_color": "#b2bec3"
    },
    "translation": {
        "provider": "ollama",
        "model": "mistral:7b",
        "target_language": "Russian",
        "prompt": "Translate the following text to {target_language}. Output ONLY the translation, nothing else:\n\n{text}"
    },
    "logging": {
        "enabled": True,
        "log_path": "~/.local/share/live-translator/logs",
        "log_original": True,
        "log_translated": True
    },
    "ai_assistant": {
        "enabled": True,
        "provider": "ollama",
        "model": "mistral:7b",
        "use_translation_model": True,
        "context_entries": 10,
        "show_tips_on_failure": True,
        "auto_translate_response": True,
        "auto_detect_questions": True,
        "qa_prompt": "Based on the following context from a live translation session:\n\n{context}\n\nQuestion: {question}\n\nProvide a clear, helpful answer. If you cannot find a direct answer in the context, say \"I cannot find a direct answer\" and explain what information would be needed.\n\nAnswer:",
        "summary_prompt": "Summarize the following content from a live translation session.\nHighlight key points, important terms, and main ideas.\n\nContent:\n{context}\n\nSummary:",
        "learning_prompt": "Based on this content from a live translation session:\n\n{context}\n\n{question}\n\nProvide educational help including:\n- Definitions of key terms mentioned\n- Cultural or contextual information\n- Related vocabulary and phrases\n- Tips for better understanding\n\nResponse:"
    },
    "reverse_translation": {
        "enabled": False,
        "source_language": "Russian",
        "target_language": "English",
        "input_device": "",
        "tts_engine": "piper",
        "tts_voice": "",
        "tts_speed": 1.0,
        "virtual_sink_name": "LiveTranslator_VirtualMic",
        "auto_start": False
    }
}

class Settings:
    def __init__(self):
        self.config_dir = Path.home() / ".config" / "live-translator"
        self.config_file = self.config_dir / "settings.json"
        self.settings = deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        """Load settings from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    saved = json.load(f)
                    self._merge_settings(saved)
            except Exception as e:
                print(f"Error loading settings: {e}")

    def _merge_settings(self, saved):
        """Merge saved settings with defaults."""
        for category, values in saved.items():
            if category in self.settings:
                if isinstance(values, dict):
                    self.settings[category].update(values)
                else:
                    self.settings[category] = values

    def save(self):
        """Save settings to file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.config_dir, prefix=".settings-")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self.settings, f, indent=2)
                os.replace(temporary, self.config_file)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get(self, category, key, default=None):
        """Get a setting value."""
        value = self.settings.get(category, {}).get(key, default)
        return default if value is None else value

    def set(self, category, key, value):
        """Set a setting value."""
        if category not in self.settings:
            self.settings[category] = {}
        self.settings[category][key] = value

    def get_all(self):
        """Get all settings."""
        return deepcopy(self.settings)


# Global settings instance
_settings = None

def get_settings():
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
