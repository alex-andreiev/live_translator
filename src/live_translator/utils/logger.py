"""
Logging module for Live Translator
"""
import os
import glob
from pathlib import Path
from datetime import datetime

from live_translator.utils.settings import get_settings

# Maximum number of log files to keep
MAX_LOG_FILES = 30
# Maximum total log size in MB
MAX_TOTAL_LOG_SIZE_MB = 100


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

    def _cleanup_old_logs(self, log_dir):
        """
        Clean up old log files based on count and total size limits.
        Keeps the newest MAX_LOG_FILES and deletes older ones.
        Also ensures total size doesn't exceed MAX_TOTAL_LOG_SIZE_MB.
        """
        try:
            # Get all log files sorted by modification time (oldest first)
            log_files = sorted(
                log_dir.glob("session_*.log"),
                key=lambda f: f.stat().st_mtime
            )

            # Remove files if count exceeds limit
            while len(log_files) > MAX_LOG_FILES:
                oldest = log_files.pop(0)
                try:
                    oldest.unlink()
                    print(f"Removed old log file: {oldest.name}")
                except OSError:
                    pass

            # Check total size and remove oldest if too large
            total_size_mb = sum(f.stat().st_size for f in log_files) / (1024 * 1024)
            while total_size_mb > MAX_TOTAL_LOG_SIZE_MB and log_files:
                oldest = log_files.pop(0)
                try:
                    file_size_mb = oldest.stat().st_size / (1024 * 1024)
                    oldest.unlink()
                    total_size_mb -= file_size_mb
                    print(f"Removed old log file (size limit): {oldest.name}")
                except OSError:
                    pass

        except Exception as e:
            print(f"Error cleaning up old logs: {e}")

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

        # Clean up old log files
        self._cleanup_old_logs(log_dir)

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
