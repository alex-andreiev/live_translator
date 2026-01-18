"""
Reverse Translation Mode - Speech-to-Speech Translation.
Captures microphone audio, transcribes, translates, synthesizes speech,
and outputs to virtual microphone for video call apps.

Pipeline: Microphone → Whisper STT → Ollama Translate → Piper TTS → Virtual Mic
"""

import threading
import time
import queue
import numpy as np
from typing import Optional, Callable

from mic_capture import MicCapture
from transcriber import Transcriber
from translator import Translator
from tts_engine import TTSEngine
from virtual_output import VirtualOutput


class ReverseMode:
    """
    Coordinates the reverse translation pipeline:
    Your speech → Recognition → Translation → Synthesis → Virtual Microphone
    """
    
    def __init__(self,
                 # Transcription settings
                 whisper_model: str = "base",
                 whisper_device: str = "cpu",
                 whisper_compute_type: str = "int8",
                 # Translation settings  
                 translator_provider: str = "ollama",
                 translator_model: str = "mistral:7b",
                 source_language: str = "Russian",
                 target_language: str = "English",
                 # TTS settings
                 tts_engine: str = "piper",
                 tts_voice: Optional[str] = None,
                 tts_speed: float = 1.0,
                 # Audio settings
                 input_device: Optional[str] = None,
                 virtual_sink_name: str = "LiveTranslator_VirtualMic",
                 sample_rate: int = 16000):
        """
        Initialize reverse translation mode.
        
        Args:
            whisper_model: Whisper model size
            whisper_device: cpu or cuda
            whisper_compute_type: int8, float16, float32
            translator_provider: Translation provider (ollama)
            translator_model: Translation model name
            source_language: Language you speak
            target_language: Language to translate to
            tts_engine: TTS engine (piper or espeak)
            tts_voice: Voice name for TTS
            tts_speed: Speech speed (0.5-2.0)
            input_device: Microphone device name (None for default)
            virtual_sink_name: Name for virtual output sink
            sample_rate: Audio sample rate
        """
        self.source_language = source_language
        self.target_language = target_language
        self.sample_rate = sample_rate
        
        # Initialize components
        print("Initializing Reverse Translation Mode...")
        
        # Microphone capture
        self.mic = MicCapture(
            device_name=input_device,
            sample_rate=sample_rate,
            channels=1
        )
        
        # Speech recognition (reuse existing transcriber)
        self.transcriber = Transcriber(
            model_size=whisper_model,
            device=whisper_device,
            compute_type=whisper_compute_type,
            enable_diarization=False,  # Not needed for single speaker
            min_audio_length=0.5,
            beam_size=3
        )
        
        # Translation (target language is what others hear)
        self.translator = Translator(
            provider=translator_provider,
            model=translator_model,
            target_language=target_language,
            # Custom prompt for real-time conversation
            prompt=(
                f"You are translating spoken {source_language} to {target_language}. "
                "Translate naturally as if speaking in conversation. "
                "Output ONLY the translation, nothing else:\n\n{text}"
            )
        )
        
        # Text-to-Speech
        self.tts = TTSEngine(engine=tts_engine)
        if tts_voice:
            self.tts.set_voice(tts_voice)
        self.tts.set_speed(tts_speed)
        
        # Virtual output
        self.virtual_output = VirtualOutput(
            sink_name=virtual_sink_name,
            sample_rate=sample_rate,
            channels=1
        )
        
        # Processing state
        self._running = False
        self._paused = False
        self._process_thread: Optional[threading.Thread] = None
        self._audio_queue = queue.Queue()
        
        # Callbacks
        self._on_transcription: Optional[Callable[[str], None]] = None
        self._on_translation: Optional[Callable[[str], None]] = None
        self._on_synthesis: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        
        # Statistics
        self.stats = {
            'transcriptions': 0,
            'translations': 0,
            'audio_chunks': 0,
            'total_audio_seconds': 0.0,
            'errors': 0
        }
        
        print("Reverse Translation Mode initialized.")
    
    def set_callbacks(self,
                      on_transcription: Optional[Callable[[str], None]] = None,
                      on_translation: Optional[Callable[[str], None]] = None,
                      on_synthesis: Optional[Callable[[], None]] = None,
                      on_error: Optional[Callable[[str], None]] = None):
        """Set callback functions for events."""
        self._on_transcription = on_transcription
        self._on_translation = on_translation
        self._on_synthesis = on_synthesis
        self._on_error = on_error
    
    def start(self) -> bool:
        """
        Start reverse translation.
        Returns True if started successfully.
        """
        if self._running:
            return True
        
        # Create virtual output sink
        if not self.virtual_output.create_virtual_sink():
            self._notify_error("Failed to create virtual microphone")
            return False
        
        # Start microphone capture
        def audio_callback(audio_data: np.ndarray):
            if not self._paused:
                self._audio_queue.put(audio_data)
        
        if not self.mic.start(callback=audio_callback):
            self._notify_error("Failed to start microphone capture")
            self.virtual_output.destroy_virtual_sink()
            return False
        
        # Start processing thread
        self._running = True
        self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._process_thread.start()
        
        print("Reverse translation started")
        return True
    
    def stop(self):
        """Stop reverse translation."""
        self._running = False
        
        # Stop microphone
        self.mic.stop()
        
        # Clear queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        
        # Wait for processing thread
        if self._process_thread:
            self._process_thread.join(timeout=2.0)
            self._process_thread = None
        
        # Destroy virtual sink
        self.virtual_output.destroy_virtual_sink()
        
        print("Reverse translation stopped")
    
    def pause(self):
        """Pause processing (microphone still runs but audio is dropped)."""
        self._paused = True
        print("Reverse translation paused")
    
    def resume(self):
        """Resume processing."""
        self._paused = False
        print("Reverse translation resumed")
    
    def is_running(self) -> bool:
        """Check if reverse translation is active."""
        return self._running
    
    def is_paused(self) -> bool:
        """Check if processing is paused."""
        return self._paused
    
    def _process_loop(self):
        """Main processing loop running in background thread."""
        audio_buffer = []
        buffer_duration = 0.0
        min_chunk_duration = 1.0  # Process at least 1 second of audio
        max_chunk_duration = 5.0  # Process max 5 seconds at a time
        
        while self._running:
            try:
                # Get audio from queue with timeout
                try:
                    audio_chunk = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    # If we have buffered audio and queue is empty, process it
                    if audio_buffer and buffer_duration >= min_chunk_duration:
                        self._process_audio_chunk(audio_buffer, buffer_duration)
                        audio_buffer = []
                        buffer_duration = 0.0
                    continue
                
                # Add to buffer
                audio_buffer.append(audio_chunk)
                chunk_duration = len(audio_chunk) / self.sample_rate
                buffer_duration += chunk_duration
                self.stats['audio_chunks'] += 1
                self.stats['total_audio_seconds'] += chunk_duration
                
                # Process if buffer is large enough
                if buffer_duration >= max_chunk_duration:
                    self._process_audio_chunk(audio_buffer, buffer_duration)
                    audio_buffer = []
                    buffer_duration = 0.0
                    
            except Exception as e:
                self.stats['errors'] += 1
                self._notify_error(f"Processing error: {e}")
                # Reset buffer on error
                audio_buffer = []
                buffer_duration = 0.0
    
    def _process_audio_chunk(self, audio_chunks: list, duration: float):
        """Process accumulated audio through the pipeline."""
        try:
            # Combine audio chunks
            audio = np.concatenate(audio_chunks)
            
            # Step 1: Transcribe (speech to text)
            text = self.transcriber.transcribe(audio)
            if not text or not text.strip():
                return
            
            self.stats['transcriptions'] += 1
            if self._on_transcription:
                self._on_transcription(text)
            print(f"[STT] {text}")
            
            # Step 2: Translate
            translated = self.translator.translate(text)
            if not translated:
                return
            
            self.stats['translations'] += 1
            if self._on_translation:
                self._on_translation(translated)
            print(f"[TTS] {translated}")
            
            # Step 3: Synthesize speech
            audio_data = self.tts.synthesize(translated)
            if not audio_data:
                self._notify_error("TTS synthesis failed")
                return
            
            # Step 4: Output to virtual microphone
            self.virtual_output.play_audio(audio_data, self.tts.sample_rate)
            
            if self._on_synthesis:
                self._on_synthesis()
                
        except Exception as e:
            self.stats['errors'] += 1
            self._notify_error(f"Pipeline error: {e}")
    
    def _notify_error(self, message: str):
        """Notify about an error."""
        print(f"[ERROR] {message}")
        if self._on_error:
            self._on_error(message)
    
    def get_virtual_mic_source(self) -> Optional[str]:
        """Get the virtual microphone source name to select in apps."""
        return self.virtual_output.get_monitor_source()
    
    def get_stats(self) -> dict:
        """Get processing statistics."""
        return self.stats.copy()
    
    def update_settings(self,
                        source_language: Optional[str] = None,
                        target_language: Optional[str] = None,
                        tts_voice: Optional[str] = None,
                        tts_speed: Optional[float] = None):
        """Update settings on the fly."""
        if source_language:
            self.source_language = source_language
        if target_language:
            self.target_language = target_language
            self.translator.set_settings(target_language=target_language)
        if tts_voice:
            self.tts.set_voice(tts_voice)
        if tts_speed is not None:
            self.tts.set_speed(tts_speed)
        
        # Update translator prompt
        self.translator.prompt_template = (
            f"You are translating spoken {self.source_language} to {self.target_language}. "
            "Translate naturally as if speaking in conversation. "
            "Output ONLY the translation, nothing else:\n\n{text}"
        )
    
    @staticmethod
    def list_input_devices() -> list[dict]:
        """List available input devices (microphones)."""
        return MicCapture.list_devices()
    
    @staticmethod
    def list_tts_voices() -> list[str]:
        """List available TTS voices."""
        tts = TTSEngine()
        return tts.list_voices()
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


# Test if run directly
if __name__ == "__main__":
    import time
    
    print("=== Reverse Translation Mode Test ===\n")
    
    # List available devices
    print("Available input devices:")
    for dev in ReverseMode.list_input_devices():
        print(f"  - {dev['name']}")
    
    print("\nAvailable TTS voices:")
    for voice in ReverseMode.list_tts_voices()[:5]:  # Show first 5
        print(f"  - {voice}")
    
    # Create instance
    print("\nInitializing...")
    reverse = ReverseMode(
        whisper_model="tiny",  # Use tiny for testing
        whisper_device="cpu",
        source_language="Russian",
        target_language="English",
        tts_engine="espeak"  # Use espeak for testing (more available)
    )
    
    # Set callbacks
    def on_text(text):
        print(f"  → Recognized: {text}")
    
    def on_translation(text):
        print(f"  → Translated: {text}")
    
    reverse.set_callbacks(
        on_transcription=on_text,
        on_translation=on_translation
    )
    
    print(f"\nVirtual mic source: {reverse.get_virtual_mic_source()}")
    print("\nStarting... (speak into microphone, Ctrl+C to stop)")
    
    try:
        reverse.start()
        while True:
            time.sleep(1)
            stats = reverse.get_stats()
            if stats['transcriptions'] > 0:
                print(f"Stats: {stats['transcriptions']} transcriptions, "
                      f"{stats['translations']} translations")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        reverse.stop()
        print("Done!")
