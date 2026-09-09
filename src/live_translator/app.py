#!/usr/bin/env python3
"""
Live Translator - Real-time speech-to-text translation
"""
import sys
import signal
import threading
import argparse
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

from live_translator.audio import AudioCapture
from live_translator.processing import Transcriber, Translator, WHISPER_MODELS
from live_translator.ui import CaptionOverlay
from live_translator.utils import get_settings, get_logger
from live_translator.ai import PROVIDERS, QAAssistant
from live_translator.modes import ReverseTranslationMode


class LiveTranslatorApp(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id="com.local.livetranslator")
        self.args = args
        self.settings = get_settings()
        self.logger = get_logger()
        self.window = None
        self.audio_capture = None
        self.transcriber = None
        self._transcriber_config = None
        self._reloading = False
        self.translator = None
        self.qa_assistant = None
        self.reverse_mode = None  # Speech-to-speech translation
        self.running = False
        self.processing_thread = None
        self.processed_questions = set()  # Track already processed questions
        # Thread pool for translation tasks (limit concurrent threads)
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="translate")

    def do_activate(self):
        if not self.window:
            self.window = CaptionOverlay(self)

        self.window.present()
        self.window.set_status("Initializing...")

        # Initialize components in background thread
        threading.Thread(target=self._initialize, daemon=True).start()

    def _get_setting(self, category, key, arg_value=None, default=None):
        """Get setting from args or config."""
        if arg_value is not None:
            return arg_value
        return self.settings.get(category, key, default)

    def _language_matches(self, detected_lang, target_lang, expected_langs=None):
        """
        Check if detected language matches target language.
        
        Args:
            detected_lang: Language code from Whisper (e.g., 'en', 'ru', 'en-US')
            target_lang: Target language name (e.g., 'English', 'Russian')
            expected_langs: List of expected language names to check against
        
        Returns:
            True if languages match, False otherwise
        """
        # Language code to name mapping (bidirectional for exact matching)
        lang_map = {
            'en': ['english'],
            'ru': ['russian'],
            'uk': ['ukrainian'],
            'es': ['spanish'],
            'fr': ['french'],
            'de': ['german'],
            'it': ['italian'],
            'pt': ['portuguese'],
            'nl': ['dutch'],
            'pl': ['polish'],
            'zh': ['chinese'],
            'ja': ['japanese'],
            'ko': ['korean'],
        }

        # Reverse mapping: name -> code
        name_to_code = {}
        for code, names in lang_map.items():
            for name in names:
                name_to_code[name] = code

        if not detected_lang:
            return False

        detected_lower = detected_lang.lower().split('-')[0]  # Get main language code
        target_lower = target_lang.lower().strip()

        # Normalize target to code if it's a full name
        target_code = name_to_code.get(target_lower, target_lower)

        # Direct exact match with target language code
        if detected_lower == target_code:
            return True

        # Check if detected code maps to target name (exact match)
        if detected_lower in lang_map:
            detected_names = lang_map[detected_lower]
            if target_lower in detected_names:
                return True

        # If expected languages provided, check if detected language matches any expected
        if expected_langs:
            for exp_lang in expected_langs:
                exp_lower = exp_lang.lower().strip()
                exp_code = name_to_code.get(exp_lower, exp_lower)

                # Check if detected matches this expected language
                if detected_lower == exp_code:
                    # Detected is in expected list - check if it's the target
                    if exp_code == target_code or exp_lower == target_lower:
                        return True  # Language matches target
                    else:
                        return False  # Language is expected but not target, skip translation

        return False

    def _transcription_config(self):
        """Every setting the Transcriber is constructed from, as a comparable dict."""
        return {
            "model_size": self._get_setting("transcription", "whisper_model", self.args.whisper_model, "base"),
            "device": self._get_setting("transcription", "device", self.args.device, "cpu"),
            "compute_type": self._get_setting("transcription", "compute_type", self.args.compute_type, "int8"),
            "enable_diarization": self.settings.get("transcription", "enable_diarization", False),
            "num_speakers": self.settings.get("transcription", "num_speakers", None),
            "min_audio_length": self.settings.get("transcription", "min_audio_length", 0.5),
            "beam_size": self.settings.get("transcription", "beam_size", 3),
            "min_silence_duration_ms": self.settings.get("transcription", "min_silence_duration_ms", 300),
            "speech_pad_ms": self.settings.get("transcription", "speech_pad_ms", 100),
            "no_speech_threshold": self.settings.get("transcription", "no_speech_threshold", 0.4),
        }

    def _build_transcriber(self, config):
        """Construct a Transcriber, warning first if the weights must be downloaded."""
        from live_translator.processing.whisper_models import is_model_cached
        model = config["model_size"]
        if not is_model_cached(model):
            GLib.idle_add(self.window.set_status,
                          f"Downloading Whisper '{model}' (first use, up to a few GB) — "
                          "this can take several minutes")
        else:
            GLib.idle_add(self.window.set_status,
                          f"Loading Whisper model '{model}' on {config['device']}...")
        return Transcriber(**config)

    def _initialize(self):
        try:
            config = self._transcription_config()
            source_lang = self._get_setting("transcription", "source_language", self.args.source_language, "en")
            self.transcriber = self._build_transcriber(config)
            self._transcriber_config = config
            self.source_language = source_lang
            self.diarization_enabled = (config["enable_diarization"]
                                        and self.transcriber.enable_diarization)

            # Initialize translator
            GLib.idle_add(self.window.set_status, "Initializing translator...")
            provider = self._get_setting("translation", "provider", self.args.provider, "ollama")
            model = self._get_setting("translation", "model", self.args.model, "mistral:7b")
            target_lang = self._get_setting("translation", "target_language", self.args.target_language, "Russian")
            prompt = self.settings.get("translation", "prompt")

            self.translator = Translator(
                provider=provider,
                model=model,
                target_language=target_lang,
                prompt=prompt
            )

            # Initialize QA Assistant
            if self.settings.get("ai_assistant", "enabled", True):
                GLib.idle_add(self.window.set_status, "Initializing AI Assistant...")
                ai_provider = self._get_setting("ai_assistant", "provider", None, "ollama")
                if self.settings.get("ai_assistant", "use_translation_model", True):
                    ai_provider = provider
                    ai_model = model
                else:
                    ai_model = self._get_setting("ai_assistant", "model", None, "mistral:7b")

                self.qa_assistant = QAAssistant(
                    provider=ai_provider,
                    model=ai_model,
                    source_language="English",
                    target_language=target_lang
                )

            # Initialize audio capture
            GLib.idle_add(self.window.set_status, "Starting audio capture...")
            chunk_duration = self.settings.get("transcription", "audio_chunk_duration", 0.25)
            self.audio_capture = AudioCapture(
                sample_rate=16000,
                chunk_duration=chunk_duration
            )
            monitor = self.audio_capture.start()

            GLib.idle_add(self.window.set_status, f"Listening on: {monitor}")
            GLib.idle_add(self.window.set_translated_text, "Ready for translation...")

            # Initialize reverse translation mode if enabled
            if self.settings.get("reverse_translation", "enabled", False):
                self._init_reverse_mode()

            # Start processing
            self.running = True
            self.processing_thread = threading.Thread(target=self._process_loop, daemon=True)
            self.processing_thread.start()

        except Exception as e:
            GLib.idle_add(self.window.set_status, f"Error: {e}")
            print(f"Initialization error: {e}")
            import traceback
            traceback.print_exc()

    def _process_loop(self):
        """Main processing loop - capture, transcribe, translate."""
        last_text = ""

        while self.running:
            # Get audio chunk
            audio = self.audio_capture.get_audio(timeout=1.0)
            if audio is None:
                continue

            # Add to transcriber buffer
            self.transcriber.add_audio(audio)

            # Try to transcribe when we have enough audio
            if self.transcriber.get_buffer_duration() >= 2.0:
                result = self.transcriber.transcribe(language=self.source_language)

                if result:
                    # Get detected language and target language
                    detected_lang = self.transcriber.detected_language
                    target_lang = self.settings.get("translation", "target_language", "Russian")
                    auto_detect_enabled = self.settings.get("transcription", "auto_detect_language", True)
                    expected_langs = self.settings.get("transcription", "expected_languages", ["Russian", "Ukrainian", "English"])
                    
                    # Handle diarization result (list of segments) vs plain text
                    if isinstance(result, list):
                        # Diarized output - list of speaker segments
                        text = " ".join([seg.get("text", "") for seg in result])
                        text_repr = str(result)  # For comparison

                        if text_repr != last_text:
                            last_text = text_repr
                            GLib.idle_add(self.window.set_original_text_with_speakers, result)
                            self.logger.log_original(self._format_diarized_text(result))

                            # Check if language matches target - skip translation if it does
                            if auto_detect_enabled and self._language_matches(detected_lang, target_lang, expected_langs):
                                GLib.idle_add(self.window.set_translated_text, "[Same language - no translation needed]")
                                self.logger.log_translated("[Same language - no translation needed]")
                            else:
                                # Translate in background using thread pool
                                self._executor.submit(self._translate_and_display, text)

                            # Auto-detect questions if enabled
                            if (self.qa_assistant and
                                self.settings.get("ai_assistant", "auto_detect_questions", True)):
                                self._executor.submit(self._detect_and_answer_questions, text)
                    else:
                        # Plain text output
                        text = result
                        if text != last_text:
                            last_text = text
                            GLib.idle_add(self.window.set_original_text, text)
                            self.logger.log_original(text)

                            # Check if language matches target - skip translation if it does
                            if auto_detect_enabled and self._language_matches(detected_lang, target_lang, expected_langs):
                                GLib.idle_add(self.window.set_translated_text, "[Same language - no translation needed]")
                                self.logger.log_translated("[Same language - no translation needed]")
                            else:
                                # Translate in background using thread pool
                                self._executor.submit(self._translate_and_display, text)

                            # Auto-detect questions if enabled
                            if (self.qa_assistant and
                                self.settings.get("ai_assistant", "auto_detect_questions", True)):
                                self._executor.submit(self._detect_and_answer_questions, text)

    def _format_diarized_text(self, segments):
        """Format diarized segments for logging."""
        lines = []
        for seg in segments:
            speaker = seg.get("speaker", "Unknown")
            text = seg.get("text", "")
            lines.append(f"[{speaker}]: {text}")
        return "\n".join(lines)

    def _init_reverse_mode(self):
        """Initialize reverse translation (speech-to-speech) mode."""
        try:
            GLib.idle_add(self.window.set_status, "Initializing Reverse Translation...")
            
            # Get settings
            source_lang = self.settings.get("reverse_translation", "source_language", "Russian")
            target_lang = self.settings.get("reverse_translation", "target_language", "English")
            input_device = self.settings.get("reverse_translation", "input_device", "") or None
            tts_engine = self.settings.get("reverse_translation", "tts_engine", "piper")
            tts_voice = self.settings.get("reverse_translation", "tts_voice", "") or None
            tts_speed = self.settings.get("reverse_translation", "tts_speed", 1.0)
            virtual_sink = self.settings.get("reverse_translation", "virtual_sink_name", "LiveTranslator_VirtualMic")
            
            # Use same transcription settings as main mode
            whisper_model = self.settings.get("transcription", "whisper_model", "base")
            whisper_device = self.settings.get("transcription", "device", "cpu")
            whisper_compute = self.settings.get("transcription", "compute_type", "int8")
            
            # Use same translation model
            translator_model = self.settings.get("translation", "model", "mistral:7b")
            
            self.reverse_mode = ReverseTranslationMode(
                whisper_model=whisper_model,
                whisper_device=whisper_device,
                whisper_compute_type=whisper_compute,
                translator_provider=self.settings.get("translation", "provider", "ollama"),
                translator_model=translator_model,
                source_language=source_lang,
                target_language=target_lang,
                tts_engine=tts_engine,
                tts_voice=tts_voice,
                tts_speed=tts_speed,
                input_device=input_device,
                virtual_sink_name=virtual_sink
            )
            
            # Set callbacks
            self.reverse_mode.set_callbacks(
                on_transcription=self._on_reverse_transcription,
                on_translation=self._on_reverse_translation,
                on_error=self._on_reverse_error
            )
            
            # Auto-start if configured
            if self.settings.get("reverse_translation", "auto_start", False):
                self.start_reverse_mode()
            else:
                GLib.idle_add(self.window.set_status, "Reverse Translation ready (not started)")
                
        except Exception as e:
            print(f"Error initializing reverse mode: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_reverse_transcription(self, text):
        """Callback for reverse mode transcription."""
        GLib.idle_add(self.window.set_status, f"[Reverse] Said: {text[:50]}...")
    
    def _on_reverse_translation(self, text):
        """Callback for reverse mode translation."""
        GLib.idle_add(self.window.set_status, f"[Reverse] Speaking: {text[:50]}...")
    
    def _on_reverse_error(self, message):
        """Callback for reverse mode errors."""
        GLib.idle_add(self.window.set_status, f"[Reverse Error] {message}")
    
    def start_reverse_mode(self):
        """Start reverse translation mode."""
        if self.reverse_mode:
            if self.reverse_mode.start():
                virtual_mic = self.reverse_mode.get_virtual_mic_source()
                GLib.idle_add(self.window.set_status, f"Reverse Translation active. Virtual mic: {virtual_mic}")
                return True
        return False
    
    def stop_reverse_mode(self):
        """Stop reverse translation mode."""
        if self.reverse_mode:
            self.reverse_mode.stop()
            GLib.idle_add(self.window.set_status, "Reverse Translation stopped")
    
    def toggle_reverse_mode(self):
        """Toggle reverse translation mode on/off."""
        if self.reverse_mode:
            if self.reverse_mode.is_running():
                self.stop_reverse_mode()
            else:
                self.start_reverse_mode()
    
    def is_reverse_mode_active(self):
        """Check if reverse mode is active."""
        return self.reverse_mode and self.reverse_mode.is_running()

    def _translate_and_display(self, text):
        """Translate text and update display."""
        if self.translator.provider == "none":
            GLib.idle_add(self.window.set_status, "Transcription only — translation disabled")
            return
        translated = self.translator.translate(text)
        if not translated and self.translator.last_error:
            GLib.idle_add(self.window.set_status, self.translator.last_error)
        if translated:
            GLib.idle_add(self.window.set_translated_text, translated)
            self.logger.log_translated(translated)

    def _detect_and_answer_questions(self, text):
        """Detect questions in transcribed text and answer them."""
        if not self.qa_assistant:
            return

        # Detect questions in the text
        questions = self.qa_assistant.detect_questions(text)

        for question in questions:
            # Skip if already processed (normalize for comparison)
            q_normalized = question.lower().strip()
            if q_normalized in self.processed_questions:
                continue

            # Mark as processed
            self.processed_questions.add(q_normalized)

            # Keep processed questions set from growing too large
            if len(self.processed_questions) > 100:
                # Remove oldest entries (convert to list, slice, convert back)
                self.processed_questions = set(list(self.processed_questions)[-50:])

            # Get context for answering
            context = self._get_context_for_ai()

            if not context:
                continue

            try:
                # Process the question
                result = self.qa_assistant.process_detected_question(question, context)

                # Update UI with the detected question and answer
                GLib.idle_add(
                    self.window.show_detected_qa,
                    question,
                    result.get("original_response", ""),
                    result.get("translated_response", "")
                )
            except Exception as e:
                print(f"Error answering detected question: {e}")

    def _get_context_for_ai(self):
        """Get recent context for AI assistant."""
        if not self.window:
            return ""

        num_entries = self.settings.get("ai_assistant", "context_entries", 10)

        original = self.window.original_history[-num_entries:] if self.window.original_history else []
        translated = self.window.translated_history[-num_entries:] if self.window.translated_history else []

        if not original and not translated:
            return ""

        context_parts = []
        if original:
            context_parts.append("Original:\n" + "\n".join(original))
        if translated:
            context_parts.append("Translation:\n" + "\n".join(translated))

        return "\n\n".join(context_parts)

    def on_ai_request(self, context, question, mode):
        """Handle AI Assistant request."""
        if not self.qa_assistant:
            return {
                "success": False,
                "original_response": "AI Assistant not initialized.",
                "translated_response": "",
                "is_tips": False
            }

        try:
            result = self.qa_assistant.ask(context, question, mode)
            return result
        except Exception as e:
            return {
                "success": False,
                "original_response": f"Error: {e}",
                "translated_response": "",
                "is_tips": False
            }

    def on_settings_changed(self, settings):
        """Called when settings are changed from the dialog."""
        # Update translator settings (can be done without restart)
        if self.translator:
            self.translator.set_settings(
                provider=settings.get("translation", "provider"),
                model=settings.get("translation", "model"),
                target_language=settings.get("translation", "target_language"),
                prompt=settings.get("translation", "prompt")
            )

        # Update QA Assistant settings
        if self.qa_assistant:
            target_lang = settings.get("translation", "target_language", "Russian")
            if settings.get("ai_assistant", "use_translation_model", True):
                ai_model = settings.get("translation", "model", "mistral:7b")
            else:
                ai_model = settings.get("ai_assistant", "model", "mistral:7b")

            ai_category = "translation" if settings.get("ai_assistant", "use_translation_model", True) else "ai_assistant"
            self.qa_assistant.set_settings(
                provider=settings.get(ai_category, "provider", "ollama"),
                model=ai_model,
                target_language=target_lang
            )

        # Reload logger settings
        self.logger.reload_settings()
        
        # Handle reverse translation settings changes
        reverse_enabled = settings.get("reverse_translation", "enabled", False)
        if reverse_enabled and not self.reverse_mode:
            # Initialize reverse mode if newly enabled
            self._init_reverse_mode()
        elif not reverse_enabled and self.reverse_mode:
            # Stop and clean up reverse mode if disabled
            self.reverse_mode.stop()
            self.reverse_mode = None
        elif self.reverse_mode:
            # Update reverse mode settings
            self.reverse_mode.translator.set_settings(
                provider=settings.get("translation", "provider", "ollama"),
                model=settings.get("translation", "model", ""))
            self.reverse_mode.update_settings(
                source_language=settings.get("reverse_translation", "source_language", "Russian"),
                target_language=settings.get("reverse_translation", "target_language", "English"),
                tts_voice=settings.get("reverse_translation", "tts_voice", ""),
                tts_speed=settings.get("reverse_translation", "tts_speed", 1.0)
            )
        
        self.source_language = self._get_setting(
            "transcription", "source_language", self.args.source_language, "en")
        self._reload_transcriber_if_needed()

    def _reload_transcriber_if_needed(self):
        """Rebuild the transcriber in the background when its settings changed."""
        if not self.transcriber:
            return
        config = self._transcription_config()
        if config == getattr(self, "_transcriber_config", None) or self._reloading:
            return
        self._reloading = True

        def worker():
            try:
                transcriber = self._build_transcriber(config)
            except Exception as exc:
                # Keep the working transcriber rather than leaving the app deaf.
                GLib.idle_add(self.window.set_status,
                              f"Could not apply transcription settings: {exc}. "
                              "Previous model still running.")
                self._reloading = False
                return
            GLib.idle_add(finish, transcriber)

        def finish(transcriber):
            # Swapping a fully built object is atomic for the processing loop.
            self.transcriber = transcriber
            self._transcriber_config = config
            self.diarization_enabled = (config["enable_diarization"]
                                        and transcriber.enable_diarization)
            self._reloading = False
            self.window.set_status(
                f"Transcription now using {config['model_size']} "
                f"({config['compute_type']}) on {config['device']}")
            return False

        threading.Thread(target=worker, daemon=True).start()

    def do_shutdown(self):
        self.running = False

        # Wait for processing thread to finish
        if self.processing_thread:
            self.processing_thread.join(timeout=2.0)

        # Shutdown thread pool executor
        if self._executor:
            self._executor.shutdown(wait=False)

        if self.audio_capture:
            self.audio_capture.stop()
        if self.reverse_mode:
            self.reverse_mode.stop()
        if self.logger:
            self.logger.close()
        Gtk.Application.do_shutdown(self)


def main():
    parser = argparse.ArgumentParser(
        description="Live Translator",
        epilog="Options left unset fall back to the saved settings file, then to the defaults shown."
    )
    parser.add_argument(
        "--whisper-model", "-w",
        choices=list(WHISPER_MODELS),
        help="Whisper model size (default: base)"
    )
    parser.add_argument(
        "--provider", "-p",
        choices=list(PROVIDERS),
        help="Translation provider; 'none' transcribes without translating (default: ollama)"
    )
    parser.add_argument(
        "--model", "-m", "--ollama-model",
        dest="model",
        help="Model ID for the selected translation provider (default: mistral:7b)"
    )
    parser.add_argument(
        "--source-language", "-s",
        help="Source language code (default: en)"
    )
    parser.add_argument(
        "--target-language", "-t",
        help="Target language name (default: Russian)"
    )
    parser.add_argument(
        "--device", "-d",
        choices=["cpu", "cuda"],
        help="Device for Whisper (default: cpu)"
    )
    parser.add_argument(
        "--compute-type",
        choices=["int8", "float16", "float32"],
        help="Compute type for Whisper (default: int8)"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check dependencies, hardware and settings, print the report and exit. "
             "Exit status 1 if anything would stop the app working."
    )

    args = parser.parse_args()

    if args.check:
        from live_translator.utils.diagnostics import run_checks, render, FAIL
        results = run_checks()
        print(render(results))
        sys.exit(1 if any(r.status == FAIL for r in results) else 0)

    app = LiveTranslatorApp(args)
    # PyGObject's SIGINT helper unwinds badly when Ctrl+C lands inside a worker
    # thread (a model download, say), so quit the app instead of raising there.
    def interrupt(signum, frame):
        print("\nStopping...")
        GLib.idle_add(app.quit)
    signal.signal(signal.SIGINT, interrupt)
    try:
        app.run(None)
    except KeyboardInterrupt:
        app.quit()


if __name__ == "__main__":
    main()
