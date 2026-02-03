#!/usr/bin/env python3
"""
Live Translator - Real-time speech-to-text translation
"""
import sys
import threading
import argparse
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

from live_translator.audio import AudioCapture
from live_translator.processing import Transcriber, Translator
from live_translator.ui import CaptionOverlay
from live_translator.utils import get_settings, get_logger
from live_translator.ai import QAAssistant
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
        self.translator = None
        self.qa_assistant = None
        self.reverse_mode = None  # Speech-to-speech translation
        self.transcription_only_mode = False
        self.transcription_language = "en"
        self.running = False
        self.processing_thread = None
        self.processed_questions = set()  # Track already processed questions
        # Thread pool for translation tasks (limit concurrent threads)
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="translate")
        self._transcriber_reload_lock = threading.Lock()
        self._audio_restart_lock = threading.Lock()
        self._transcriber_reload_in_progress = False

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

    def _initialize(self):
        try:
            # Get settings
            whisper_model = self._get_setting("transcription", "whisper_model",
                self.args.whisper_model if self.args.whisper_model != "base" else None, "base")
            device = self._get_setting("transcription", "device",
                self.args.device if self.args.device != "cpu" else None, "cpu")
            compute_type = self._get_setting("transcription", "compute_type",
                self.args.compute_type if self.args.compute_type != "int8" else None, "int8")
            source_lang = self._get_setting("transcription", "source_language",
                self.args.source_language if self.args.source_language != "en" else None, "en")
            auto_detect_enabled = self.settings.get("transcription", "auto_detect_language", True)

            # Diarization settings (local - no token required)
            enable_diarization = self.settings.get("transcription", "enable_diarization", False)
            num_speakers = self.settings.get("transcription", "num_speakers", None)

            # Performance optimization settings
            min_audio_length = self.settings.get("transcription", "min_audio_length", 0.5)
            beam_size = self.settings.get("transcription", "beam_size", 3)
            min_silence_duration_ms = self.settings.get("transcription", "min_silence_duration_ms", 300)
            speech_pad_ms = self.settings.get("transcription", "speech_pad_ms", 100)
            no_speech_threshold = self.settings.get("transcription", "no_speech_threshold", 0.4)

            # Initialize transcriber
            GLib.idle_add(self.window.set_status, f"Loading Whisper model '{whisper_model}'...")
            self.transcriber = self._create_transcriber_with_fallback(
                whisper_model=whisper_model,
                device=device,
                compute_type=compute_type,
                enable_diarization=enable_diarization,
                num_speakers=num_speakers,
                min_audio_length=min_audio_length,
                beam_size=beam_size,
                min_silence_duration_ms=min_silence_duration_ms,
                speech_pad_ms=speech_pad_ms,
                no_speech_threshold=no_speech_threshold
            )
            self.source_language = source_lang
            # Whisper: language=None enables auto detection.
            self.transcription_language = None if auto_detect_enabled else source_lang
            self.diarization_enabled = enable_diarization and self.transcriber.enable_diarization
            GLib.idle_add(
                self.window.set_status,
                f"Whisper ready: {self.transcriber.model_size} on {self.transcriber.device} ({self.transcriber.compute_type})"
            )
            self.transcription_only_mode = (
                bool(getattr(self.args, "transcription_only", False)) or
                self.settings.get("transcription", "transcription_only_mode", False)
            )

            if self.transcription_only_mode:
                GLib.idle_add(self.window.set_status, "Transcription-only mode enabled (translation disabled)")
                self.translator = None
                self.qa_assistant = None
            else:
                # Initialize translator
                GLib.idle_add(self.window.set_status, "Initializing translator...")
                model = self._get_setting("translation", "model",
                    self.args.ollama_model if self.args.ollama_model != "mistral:7b" else None, "mistral:7b")
                target_lang = self._get_setting("translation", "target_language",
                    self.args.target_language if self.args.target_language != "Russian" else None, "Russian")
                self._init_translation_services(model_override=model, target_lang_override=target_lang)
            GLib.idle_add(self.window.set_transcription_only_mode, self.transcription_only_mode)

            # Initialize audio capture
            GLib.idle_add(self.window.set_status, "Starting audio capture...")
            chunk_duration = self.settings.get("transcription", "audio_chunk_duration", 0.25)
            self.audio_capture = AudioCapture(
                sample_rate=16000,
                chunk_duration=chunk_duration
            )
            monitor = self.audio_capture.start()

            GLib.idle_add(self.window.set_status, f"Listening on: {monitor}")
            if self.transcription_only_mode:
                GLib.idle_add(self.window.set_translated_text, "Transcription-only mode: translation disabled.")
            else:
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
            min_process_duration = max(0.3, getattr(self.transcriber, "min_audio_length", 0.5))
            if self.transcriber.get_buffer_duration() >= min_process_duration:
                result = self.transcriber.transcribe(language=self.transcription_language)

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

                            if not self.transcription_only_mode:
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

                            if not self.transcription_only_mode:
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

    def _create_transcriber_with_fallback(
        self,
        whisper_model,
        device,
        compute_type,
        enable_diarization,
        num_speakers,
        min_audio_length,
        beam_size,
        min_silence_duration_ms,
        speech_pad_ms,
        no_speech_threshold
    ):
        """Create transcriber and gracefully fallback to CPU when CUDA is unavailable."""
        try:
            return Transcriber(
                model_size=whisper_model,
                device=device,
                compute_type=compute_type,
                enable_diarization=enable_diarization,
                num_speakers=num_speakers,
                min_audio_length=min_audio_length,
                beam_size=beam_size,
                min_silence_duration_ms=min_silence_duration_ms,
                speech_pad_ms=speech_pad_ms,
                no_speech_threshold=no_speech_threshold
            )
        except Exception as e:
            if device != "cuda":
                raise

            fallback_compute = "int8"
            GLib.idle_add(
                self.window.set_status,
                "CUDA unavailable, switching Whisper to CPU (int8)."
            )
            print(f"Whisper CUDA init failed ({e}). Falling back to CPU.")
            return Transcriber(
                model_size=whisper_model,
                device="cpu",
                compute_type=fallback_compute,
                enable_diarization=enable_diarization,
                num_speakers=num_speakers,
                min_audio_length=min_audio_length,
                beam_size=beam_size,
                min_silence_duration_ms=min_silence_duration_ms,
                speech_pad_ms=speech_pad_ms,
                no_speech_threshold=no_speech_threshold
            )

    def _init_translation_services(self, model_override=None, target_lang_override=None):
        """Initialize or reinitialize translator and optional AI assistant."""
        provider = self._get_setting("translation", "provider", None, "ollama")
        model = model_override or self._get_setting("translation", "model", None, "mistral:7b")
        target_lang = target_lang_override or self._get_setting("translation", "target_language", None, "Russian")
        prompt = self.settings.get("translation", "prompt")

        self.translator = Translator(
            provider=provider,
            model=model,
            target_language=target_lang,
            prompt=prompt
        )

        if self.settings.get("ai_assistant", "enabled", True):
            ai_provider = self._get_setting("ai_assistant", "provider", None, "ollama")
            if self.settings.get("ai_assistant", "use_translation_model", True):
                ai_model = model
            else:
                ai_model = self._get_setting("ai_assistant", "model", None, "mistral:7b")

            self.qa_assistant = QAAssistant(
                provider=ai_provider,
                model=ai_model,
                source_language="English",
                target_language=target_lang
            )
        else:
            self.qa_assistant = None

    def _apply_transcriber_runtime_settings(self, settings):
        """Apply non-model transcription settings without reload."""
        if not self.transcriber:
            return

        self.source_language = settings.get("transcription", "source_language", "en")
        auto_detect_enabled = settings.get("transcription", "auto_detect_language", True)
        self.transcription_language = None if auto_detect_enabled else self.source_language
        self.transcriber.min_audio_length = settings.get("transcription", "min_audio_length", 0.5)
        self.transcriber.beam_size = settings.get("transcription", "beam_size", 3)
        self.transcriber.min_silence_duration_ms = settings.get("transcription", "min_silence_duration_ms", 300)
        self.transcriber.speech_pad_ms = settings.get("transcription", "speech_pad_ms", 100)
        self.transcriber.no_speech_threshold = settings.get("transcription", "no_speech_threshold", 0.4)
        self.transcriber.set_diarization(
            settings.get("transcription", "enable_diarization", False),
            settings.get("transcription", "num_speakers", None)
        )

    def _reload_transcriber(self, settings):
        """Reload Whisper model in background to apply model/device/compute changes."""
        if not self._transcriber_reload_lock.acquire(blocking=False):
            return

        self._transcriber_reload_in_progress = True
        try:
            whisper_model = settings.get("transcription", "whisper_model", "base")
            device = settings.get("transcription", "device", "cpu")
            compute_type = settings.get("transcription", "compute_type", "int8")
            enable_diarization = settings.get("transcription", "enable_diarization", False)
            num_speakers = settings.get("transcription", "num_speakers", None)
            min_audio_length = settings.get("transcription", "min_audio_length", 0.5)
            beam_size = settings.get("transcription", "beam_size", 3)
            min_silence_duration_ms = settings.get("transcription", "min_silence_duration_ms", 300)
            speech_pad_ms = settings.get("transcription", "speech_pad_ms", 100)
            no_speech_threshold = settings.get("transcription", "no_speech_threshold", 0.4)

            GLib.idle_add(self.window.set_status, f"Reloading Whisper model '{whisper_model}'...")
            new_transcriber = self._create_transcriber_with_fallback(
                whisper_model=whisper_model,
                device=device,
                compute_type=compute_type,
                enable_diarization=enable_diarization,
                num_speakers=num_speakers,
                min_audio_length=min_audio_length,
                beam_size=beam_size,
                min_silence_duration_ms=min_silence_duration_ms,
                speech_pad_ms=speech_pad_ms,
                no_speech_threshold=no_speech_threshold
            )

            old_transcriber = self.transcriber
            self.transcriber = new_transcriber
            self.source_language = settings.get("transcription", "source_language", "en")
            auto_detect_enabled = settings.get("transcription", "auto_detect_language", True)
            self.transcription_language = None if auto_detect_enabled else self.source_language
            self.diarization_enabled = enable_diarization and self.transcriber.enable_diarization

            if old_transcriber:
                old_transcriber.clear_buffer()

            GLib.idle_add(
                self.window.set_status,
                f"Transcriber reloaded: {self.transcriber.model_size} on {self.transcriber.device} ({self.transcriber.compute_type})"
            )
        except Exception as e:
            GLib.idle_add(self.window.set_status, f"Failed to reload transcriber: {e}")
            print(f"Transcriber reload error: {e}")
        finally:
            self._transcriber_reload_in_progress = False
            self._transcriber_reload_lock.release()

    def is_transcriber_reload_in_progress(self):
        """Check whether Whisper model is currently reloading."""
        return self._transcriber_reload_in_progress

    def _restart_audio_capture(self, chunk_duration):
        """Restart audio capture to apply chunk duration without app restart."""
        if not self._audio_restart_lock.acquire(blocking=False):
            return

        try:
            GLib.idle_add(self.window.set_status, "Restarting audio capture...")
            old_capture = self.audio_capture
            if old_capture:
                old_capture.stop()

            self.audio_capture = AudioCapture(sample_rate=16000, chunk_duration=chunk_duration)
            monitor = self.audio_capture.start()
            GLib.idle_add(self.window.set_status, f"Listening on: {monitor}")
        except Exception as e:
            GLib.idle_add(self.window.set_status, f"Audio restart failed: {e}")
            print(f"Audio restart error: {e}")
        finally:
            self._audio_restart_lock.release()

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
                translator_provider="ollama",
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
        if not self.translator:
            return
        translated = self.translator.translate(text)
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

    def set_transcription_only_mode(self, enabled, save_setting=True):
        """Toggle transcription-only mode at runtime."""
        self.settings.set("transcription", "transcription_only_mode", bool(enabled))
        if save_setting:
            self.settings.save()
        return self.on_settings_changed(self.settings)

    def on_settings_changed(self, settings):
        """Called when settings are changed from the dialog."""
        transcriber_reload_started = False
        previous_mode = self.transcription_only_mode
        self.transcription_only_mode = settings.get("transcription", "transcription_only_mode", False)
        GLib.idle_add(self.window.set_transcription_only_mode, self.transcription_only_mode)

        if self.transcription_only_mode:
            # Stop translation-related services while keeping transcription/logging active.
            if not previous_mode:
                self.qa_assistant = None
            GLib.idle_add(self.window.set_translated_text, "Transcription-only mode: translation disabled.")
        else:
            # Translation mode can be enabled live; initialize missing services.
            if self.translator is None:
                self._init_translation_services()
            else:
                self.translator.set_settings(
                    provider=settings.get("translation", "provider"),
                    model=settings.get("translation", "model"),
                    target_language=settings.get("translation", "target_language"),
                    prompt=settings.get("translation", "prompt")
                )

            # Update or initialize QA Assistant settings
            if settings.get("ai_assistant", "enabled", True):
                target_lang = settings.get("translation", "target_language", "Russian")
                if settings.get("ai_assistant", "use_translation_model", True):
                    ai_model = settings.get("translation", "model", "mistral:7b")
                else:
                    ai_model = settings.get("ai_assistant", "model", "mistral:7b")

                if self.qa_assistant:
                    self.qa_assistant.set_settings(
                        provider=settings.get("ai_assistant", "provider", "ollama"),
                        model=ai_model,
                        target_language=target_lang
                    )
                else:
                    self._init_translation_services()
            else:
                self.qa_assistant = None

        # Apply transcription settings live
        self._apply_transcriber_runtime_settings(settings)

        # Reload transcriber when model/backend settings change
        if self.transcriber:
            model_changed = settings.get("transcription", "whisper_model", "base") != self.transcriber.model_size
            device_changed = settings.get("transcription", "device", "cpu") != self.transcriber.device
            compute_changed = settings.get("transcription", "compute_type", "int8") != self.transcriber.compute_type
            if model_changed or device_changed or compute_changed:
                threading.Thread(target=self._reload_transcriber, args=(settings,), daemon=True).start()
                transcriber_reload_started = True

        # Restart audio capture when chunk duration changes
        if self.audio_capture:
            new_chunk = settings.get("transcription", "audio_chunk_duration", 0.25)
            current_chunk = self.audio_capture.chunk_size / self.audio_capture.sample_rate
            if abs(new_chunk - current_chunk) > 1e-6:
                threading.Thread(target=self._restart_audio_capture, args=(new_chunk,), daemon=True).start()

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
            self.reverse_mode.update_settings(
                source_language=settings.get("reverse_translation", "source_language", "Russian"),
                target_language=settings.get("reverse_translation", "target_language", "English"),
                tts_voice=settings.get("reverse_translation", "tts_voice", ""),
                tts_speed=settings.get("reverse_translation", "tts_speed", 1.0)
            )

        print("Settings updated and applied without restart.")
        return {
            "transcriber_reload_started": transcriber_reload_started,
            "transcriber_reload_in_progress": self.is_transcriber_reload_in_progress()
        }

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
    parser = argparse.ArgumentParser(description="Live Translator")
    parser.add_argument(
        "--whisper-model", "-w",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        help="Whisper model size (default: base)"
    )
    parser.add_argument(
        "--ollama-model", "-m",
        default="mistral:7b",
        help="Ollama model for translation (default: mistral:7b)"
    )
    parser.add_argument(
        "--source-language", "-s",
        default="en",
        help="Source language code (default: en)"
    )
    parser.add_argument(
        "--target-language", "-t",
        default="Russian",
        help="Target language name (default: Russian)"
    )
    parser.add_argument(
        "--device", "-d",
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device for Whisper (default: cpu)"
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        choices=["int8", "float16", "float32"],
        help="Compute type for Whisper (default: int8)"
    )
    parser.add_argument(
        "--transcription-only",
        action="store_true",
        help="Transcribe speech and log it without translation"
    )

    args = parser.parse_args()

    app = LiveTranslatorApp(args)
    app.run(None)


if __name__ == "__main__":
    main()
