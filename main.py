#!/usr/bin/env python3
"""
Live Translator - Real-time speech-to-text translation
"""
import sys
import threading
import argparse

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

from audio_capture import AudioCapture
from transcriber import Transcriber
from translator import Translator
from overlay import CaptionOverlay
from settings import get_settings
from logger import get_logger
from qa_assistant import QAAssistant
from reverse_mode import ReverseMode


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
        self.running = False
        self.processing_thread = None
        self.processed_questions = set()  # Track already processed questions

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
        # Language code to name mapping
        lang_map = {
            'en': ['english', 'en-us', 'en-gb'],
            'ru': ['russian'],
            'uk': ['ukrainian'],
            'es': ['spanish'],
            'fr': ['french'],
            'de': ['german'],
            'it': ['italian'],
            'pt': ['portuguese'],
            'nl': ['dutch'],
            'pl': ['polish'],
            'zh': ['chinese', 'simplified chinese', 'traditional chinese'],
            'ja': ['japanese'],
            'ko': ['korean'],
        }
        
        if not detected_lang:
            return False
        
        detected_lower = detected_lang.lower().split('-')[0]  # Get main language code
        target_lower = target_lang.lower()
        
        # Direct match with target language
        if detected_lower == target_lower:
            return True
        
        # Check against language map for target language
        for code, names in lang_map.items():
            if detected_lower == code and any(name in target_lower for name in names):
                return True
        
        # If expected languages provided, check if detected language is in the list
        if expected_langs:
            expected_lower = [lang.lower() for lang in expected_langs]
            for code, names in lang_map.items():
                if detected_lower == code:
                    # Check if any of the language names match expected languages
                    for name in names:
                        if any(name in exp_lang for exp_lang in expected_lower):
                            return False  # Language is in expected list but not target, don't translate
        
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
            self.transcriber = Transcriber(
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
            self.source_language = source_lang
            self.diarization_enabled = enable_diarization and self.transcriber.enable_diarization

            # Initialize translator
            GLib.idle_add(self.window.set_status, "Initializing translator...")
            provider = self._get_setting("translation", "provider", None, "ollama")
            model = self._get_setting("translation", "model",
                self.args.ollama_model if self.args.ollama_model != "mistral:7b" else None, "mistral:7b")
            target_lang = self._get_setting("translation", "target_language",
                self.args.target_language if self.args.target_language != "Russian" else None, "Russian")
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
                                # Translate in background
                                threading.Thread(
                                    target=self._translate_and_display,
                                    args=(text,),
                                    daemon=True
                                ).start()

                            # Auto-detect questions if enabled
                            if (self.qa_assistant and
                                self.settings.get("ai_assistant", "auto_detect_questions", True)):
                                threading.Thread(
                                    target=self._detect_and_answer_questions,
                                    args=(text,),
                                    daemon=True
                                ).start()
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
                                # Translate in background
                                threading.Thread(
                                    target=self._translate_and_display,
                                    args=(text,),
                                    daemon=True
                                ).start()

                            # Auto-detect questions if enabled
                            if (self.qa_assistant and
                                self.settings.get("ai_assistant", "auto_detect_questions", True)):
                                threading.Thread(
                                    target=self._detect_and_answer_questions,
                                    args=(text,),
                                    daemon=True
                                ).start()

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
            
            self.reverse_mode = ReverseMode(
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

            self.qa_assistant.set_settings(
                provider=settings.get("ai_assistant", "provider", "ollama"),
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
            self.reverse_mode.update_settings(
                source_language=settings.get("reverse_translation", "source_language", "Russian"),
                target_language=settings.get("reverse_translation", "target_language", "English"),
                tts_voice=settings.get("reverse_translation", "tts_voice", ""),
                tts_speed=settings.get("reverse_translation", "tts_speed", 1.0)
            )
        
        print("Settings updated. Note: Transcription settings require restart.")

    def do_shutdown(self):
        self.running = False
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

    args = parser.parse_args()

    app = LiveTranslatorApp(args)
    app.run(None)


if __name__ == "__main__":
    main()
