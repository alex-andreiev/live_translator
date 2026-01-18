"""
Logging module for Live Translator
"""
import os
from pathlib import Path
from datetime import datetime

from settings import get_settings


class TranslationLogger:
    def __init__(self):
        self.settings = get_settings()
        self.log_file = None
        self.current_date = None
        self.session_id = None
        self._init_log_file()

    def _get_log_path(self):
        """Get expanded log path from settings."""
        log_path = self.settings.get("logging", "log_path", "~/.local/share/live-translator/logs")
        return Path(os.path.expanduser(log_path))

    def _init_log_file(self):
        """Initialize a new log file for each session."""
        if not self.settings.get("logging", "enabled", True):
            return

        # Close previous file
        if self.log_file:
            self.log_file.close()

        # Create log directory
        log_dir = self._get_log_path()
        log_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique session ID with timestamp
        now = datetime.now()
        session_timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        self.session_id = session_timestamp

        # Create separate log file for each session
        log_filename = log_dir / f"session_{session_timestamp}.log"
        self.log_file = open(log_filename, "w", encoding="utf-8")
        self.current_date = now.strftime("%Y-%m-%d")

        # Write session header
        self.log_file.write(f"{'='*70}\n")
        self.log_file.write(f"Live Translator - Session Log\n")
        self.log_file.write(f"{'='*70}\n")
        self.log_file.write(f"Session ID: {self.session_id}\n")
        self.log_file.write(f"Started: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.log_file.write(f"{'='*70}\n\n")
        self.log_file.flush()

    def log(self, original_text, translated_text):
        """Log original and translated text."""
        if not self.settings.get("logging", "enabled", True):
            return

        if not self.log_file:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")

        if self.settings.get("logging", "log_original", True) and original_text:
            self.log_file.write(f"[{timestamp}] Original:\n{original_text}\n\n")

        if self.settings.get("logging", "log_translated", True) and translated_text:
            self.log_file.write(f"[{timestamp}] Translated:\n{translated_text}\n\n")

        self.log_file.write("-" * 70 + "\n\n")
        self.log_file.flush()

    def log_original(self, text):
        """Log only original text."""
        if not self.settings.get("logging", "enabled", True):
            return
        if not self.settings.get("logging", "log_original", True):
            return

        if self.log_file and text:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_file.write(f"[{timestamp}] Original:\n{text}\n\n")
            self.log_file.flush()

    def log_translated(self, text):
        """Log only translated text."""
        if not self.settings.get("logging", "enabled", True):
            return
        if not self.settings.get("logging", "log_translated", True):
            return

        if self.log_file and text:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_file.write(f"[{timestamp}] Translated:\n{text}\n\n")
            self.log_file.write("-" * 70 + "\n\n")
            self.log_file.flush()

    def close(self):
        """Close log file."""
        if self.log_file:
            now = datetime.now()
            self.log_file.write(f"\n{'='*70}\n")
            self.log_file.write(f"Session ended: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.log_file.write(f"Duration: See timestamps above\n")
            self.log_file.write(f"{'='*70}\n")
            self.log_file.close()
            self.log_file = None

    def reload_settings(self):
        """Reload settings (call after settings change)."""
        self.settings = get_settings()


# Global logger instance
_logger = None

def get_logger():
    global _logger
    if _logger is None:
        _logger = TranslationLogger()
    return _logger
