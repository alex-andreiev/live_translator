"""
Speech-to-text module using Faster-Whisper with local speaker diarization
"""
import threading
import numpy as np
from faster_whisper import WhisperModel
from sklearn.cluster import AgglomerativeClustering
from collections import deque

# Local speaker diarization using resemblyzer (no HuggingFace token needed)
DIARIZATION_AVAILABLE = False
try:
    from resemblyzer import VoiceEncoder
    DIARIZATION_AVAILABLE = True
except ImportError:
    pass


class Transcriber:
    def __init__(self, model_size="base", device="cpu", compute_type="int8",
                 enable_diarization=False, num_speakers=None,
                 min_audio_length=0.5, beam_size=3, min_silence_duration_ms=300,
                 speech_pad_ms=100, no_speech_threshold=0.4):
        """
        Initialize Whisper model.

        Args:
            model_size: tiny, base, small, medium, large-v2, large-v3
            device: cpu or cuda
            compute_type: int8, float16, float32
            enable_diarization: Enable speaker diarization (local, no token needed)
            num_speakers: Expected number of speakers (None for auto-detect)
            min_audio_length: Minimum seconds before transcribing
            beam_size: Beam search width (1-10, higher = more accurate but slower)
            min_silence_duration_ms: Silence threshold in milliseconds
            speech_pad_ms: Padding around speech segments
            no_speech_threshold: Threshold for detecting non-speech (0.0-1.0)
        """
        # Validate compute_type
        valid_compute_types = ["int8", "float16", "float32"]
        if compute_type not in valid_compute_types:
            print(f"Warning: Invalid compute_type '{compute_type}', using 'int8'")
            compute_type = "int8"

        print(f"Loading Whisper model '{model_size}' on {device} ({compute_type})...")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print("Model loaded.")
        self.model_size = model_size
        self.compute_type = compute_type

        self.audio_buffer = []
        self._buffer_lock = threading.RLock()  # Reentrant lock for thread safety
        self.min_audio_length = min_audio_length
        self.beam_size = beam_size
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms
        self.no_speech_threshold = no_speech_threshold
        self.sample_rate = 16000
        self.device = device
        self.detected_language = None  # Will be set after each transcription

        # Speaker diarization (local - no token required)
        self.enable_diarization = enable_diarization and DIARIZATION_AVAILABLE
        self.voice_encoder = None
        self.num_speakers = num_speakers if num_speakers and num_speakers > 0 else None
        self.speaker_map = {}  # Map cluster IDs to speaker numbers
        self.next_speaker_num = 1

        # Keep history of speaker embeddings for better continuity
        self.embedding_history = deque(maxlen=20)  # Store recent embeddings
        self.speaker_centroids = {}  # Store average embedding per speaker

        if self.enable_diarization:
            self._init_diarization()

    def _init_diarization(self):
        """Initialize local speaker diarization using resemblyzer."""
        if not DIARIZATION_AVAILABLE:
            print("Warning: resemblyzer not installed. Speaker diarization disabled.")
            print("Install with: pip install resemblyzer")
            self.enable_diarization = False
            return

        try:
            print("Loading speaker encoder model (local, no token required)...")
            self.voice_encoder = VoiceEncoder(device=self.device)
            print("Speaker diarization ready (using resemblyzer).")
        except Exception as e:
            print(f"Error loading speaker encoder: {e}")
            self.enable_diarization = False

    def set_diarization(self, enabled, num_speakers=None):
        """Enable or disable speaker diarization."""
        if num_speakers is not None:
            self.num_speakers = num_speakers if num_speakers > 0 else None

        if enabled and not self.voice_encoder:
            self.enable_diarization = True
            self._init_diarization()
        else:
            self.enable_diarization = enabled

    def add_audio(self, audio_chunk):
        """Add audio chunk to buffer (thread-safe)."""
        with self._buffer_lock:
            self.audio_buffer.append(audio_chunk)
            # Limit buffer to 30 seconds max to prevent OOM
            max_samples = self.sample_rate * 30
            total_samples = sum(len(chunk) for chunk in self.audio_buffer)
            while total_samples > max_samples and len(self.audio_buffer) > 1:
                removed = self.audio_buffer.pop(0)
                total_samples -= len(removed)

    def get_buffer_duration(self):
        """Get current buffer duration in seconds (thread-safe)."""
        with self._buffer_lock:
            total_samples = sum(len(chunk) for chunk in self.audio_buffer)
            return total_samples / self.sample_rate

    def _get_speaker_for_embedding(self, embedding):
        """
        Find the best matching speaker for an embedding using stored centroids.
        Returns speaker number (1-based).
        """
        if not self.speaker_centroids:
            # First speaker
            speaker_num = 1
            self.speaker_centroids[speaker_num] = embedding
            return speaker_num

        # Find closest centroid
        best_speaker = None
        best_similarity = -1
        threshold = 0.75  # Similarity threshold for same speaker

        for speaker_num, centroid in self.speaker_centroids.items():
            # Cosine similarity with zero-norm protection
            embedding_norm = np.linalg.norm(embedding)
            centroid_norm = np.linalg.norm(centroid)
            if embedding_norm > 0 and centroid_norm > 0:
                similarity = np.dot(embedding, centroid) / (embedding_norm * centroid_norm)
            else:
                similarity = 0.0  # Treat zero-norm vectors as dissimilar
            if similarity > best_similarity:
                best_similarity = similarity
                best_speaker = speaker_num

        if best_similarity >= threshold:
            # Update centroid with running average
            old_centroid = self.speaker_centroids[best_speaker]
            self.speaker_centroids[best_speaker] = 0.9 * old_centroid + 0.1 * embedding
            return best_speaker
        else:
            # New speaker
            if self.num_speakers and len(self.speaker_centroids) >= self.num_speakers:
                # Max speakers reached, assign to closest
                return best_speaker
            else:
                new_speaker = max(self.speaker_centroids.keys()) + 1
                self.speaker_centroids[new_speaker] = embedding
                return new_speaker

    def transcribe(self, language="en"):
        """
        Transcribe buffered audio and clear buffer.

        Returns:
            If diarization enabled: list of dicts with 'speaker', 'text'
            Otherwise: Transcribed text string or None if buffer too short
        """
        if self.get_buffer_duration() < self.min_audio_length:
            return None

        # Combine audio chunks and clear buffer (thread-safe)
        with self._buffer_lock:
            if not self.audio_buffer:
                return None
            audio = np.concatenate(self.audio_buffer)
            self.audio_buffer = []

        # Check if audio has enough energy (not silence)
        # Use RMS-based detection which is more accurate for speech
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 0.005:  # Lower threshold, RMS is typically smaller than peak
            return None

        # Transcribe with Whisper
        segments, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=self.beam_size,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=self.min_silence_duration_ms,
                speech_pad_ms=self.speech_pad_ms
            ),
            word_timestamps=self.enable_diarization,  # Need timestamps for diarization
            condition_on_previous_text=False,  # Helps reduce repetition/hallucinated loops
            temperature=0.0,  # More deterministic, faster
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            no_speech_threshold=self.no_speech_threshold
        )

        segments_list = list(segments)
        
        # Store detected language for later use
        self.detected_language = info.language if info else language

        if not segments_list:
            return None

        # If diarization is enabled, assign speakers to segments
        if self.enable_diarization and self.voice_encoder:
            return self._transcribe_with_diarization(audio, segments_list)

        # Standard transcription without diarization
        text_parts = []
        for segment in segments_list:
            text_parts.append(segment.text.strip())

        text = " ".join(text_parts).strip()
        if not text:
            return None
        if self._looks_like_repetition_hallucination(text):
            return None
        return text

    def _looks_like_repetition_hallucination(self, text):
        """
        Detect obvious repetition loops like:
        'и все еще и все еще ...' to avoid logging/model artifacts.
        """
        words = [w for w in text.lower().split() if w]
        if len(words) < 12:
            return False

        # Too few unique words in long output is usually a hallucination loop.
        unique_ratio = len(set(words)) / len(words)
        if len(words) >= 24 and unique_ratio < 0.22:
            return True

        # Detect long consecutive single-word repeats.
        run = 1
        for i in range(1, len(words)):
            if words[i] == words[i - 1]:
                run += 1
                if run >= 6:
                    return True
            else:
                run = 1

        return False

    def _transcribe_with_diarization(self, audio, segments):
        """Transcribe with local speaker diarization using resemblyzer."""
        try:
            results = []

            for segment in segments:
                start_sample = int(segment.start * self.sample_rate)
                end_sample = int(segment.end * self.sample_rate)

                # Ensure we have valid indices
                start_sample = max(0, start_sample)
                end_sample = min(len(audio), end_sample)

                segment_audio = audio[start_sample:end_sample]
                text = segment.text.strip()

                if not text:
                    continue

                # Try to get speaker embedding
                speaker_num = None

                # Need at least 0.3 seconds for embedding (reduced from 0.5)
                if len(segment_audio) >= self.sample_rate * 0.3:
                    # Preprocess for resemblyzer (expects float32)
                    if segment_audio.dtype != np.float32:
                        segment_audio = segment_audio.astype(np.float32)

                    try:
                        embedding = self.voice_encoder.embed_utterance(segment_audio)
                        speaker_num = self._get_speaker_for_embedding(embedding)
                    except Exception as e:
                        print(f"Embedding error: {e}")

                # If no embedding could be extracted, mark as unknown speaker
                if speaker_num is None:
                    results.append({
                        "speaker": "Unknown",
                        "text": text
                    })
                    continue

                results.append({
                    "speaker": f"Speaker {speaker_num}",
                    "text": text,
                    "start": segment.start,
                    "end": segment.end
                })

            return results if results else None

        except Exception as e:
            print(f"Diarization error: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to plain transcription
            text_parts = [seg.text.strip() for seg in segments]
            return " ".join(text_parts).strip()

    def reset_speakers(self):
        """Reset speaker mapping (start fresh speaker numbering)."""
        self.speaker_map = {}
        self.next_speaker_num = 1
        self.speaker_centroids = {}
        self.embedding_history.clear()

    def clear_buffer(self):
        """Clear the audio buffer (thread-safe)."""
        with self._buffer_lock:
            self.audio_buffer = []


if __name__ == "__main__":
    # Test transcriber
    print(f"Diarization available: {DIARIZATION_AVAILABLE}")

    transcriber = Transcriber(model_size="base", enable_diarization=True, num_speakers=2)
    print(f"Diarization enabled: {transcriber.enable_diarization}")
    print(f"Num speakers: {transcriber.num_speakers}")

    # Generate 2 seconds of silence (for testing)
    silence = np.zeros(32000, dtype=np.float32)
    transcriber.add_audio(silence)

    result = transcriber.transcribe()
    print(f"Result: {result}")
