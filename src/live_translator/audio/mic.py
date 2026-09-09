"""
Microphone capture module - captures audio from microphone input
"""
import json
import subprocess
import threading
import queue
import shutil
import numpy as np


class MicCapture:
    """Capture audio from microphone using PipeWire or PulseAudio."""
    
    def __init__(self, sample_rate=16000, chunk_duration=0.25, device=None):
        """
        Initialize microphone capture.
        
        Args:
            sample_rate: Audio sample rate (default: 16000 for Whisper)
            chunk_duration: Duration of each audio chunk in seconds
            device: Specific device name/id (None = default microphone)
        """
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_duration)
        self.audio_queue = queue.Queue(maxsize=50)
        self.running = False
        self.process = None
        self.thread = None
        self.backend = None
        self.device = device

    def _detect_backend(self):
        """Detect available audio backend."""
        if shutil.which('pw-record'):
            return 'pipewire'
        elif shutil.which('parec'):
            return 'pulseaudio'
        return None

    def _get_default_source(self):
        """Get default microphone source."""
        if self.device:
            return self.device
            
        if self.backend == 'pipewire':
            try:
                result = subprocess.run(
                    ['wpctl', 'inspect', '@DEFAULT_AUDIO_SOURCE@'],
                    capture_output=True, text=True
                )
                for line in result.stdout.split('\n'):
                    if 'node.name' in line:
                        return line.split('=')[1].strip().strip('"')
            except Exception:
                pass
        return None  # Use system default

    def list_microphones(self):
        """List available microphone devices as {'id', 'name', 'full'} dicts."""
        if self.backend == 'pipewire' or shutil.which('pw-dump'):
            microphones = self._list_pipewire_sources()
            if microphones:
                return microphones
        return self._list_pulseaudio_sources()

    @staticmethod
    def _list_pipewire_sources():
        """List PipeWire capture nodes via pw-dump's JSON node graph."""
        # pw-record has no source listing flag, so read the graph directly.
        if not shutil.which('pw-dump'):
            return []
        try:
            result = subprocess.run(['pw-dump'], capture_output=True, text=True, timeout=10)
            objects = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return []

        microphones = []
        for entry in objects:
            if not isinstance(entry, dict):
                continue
            props = ((entry.get('info') or {}).get('props') or {})
            if props.get('media.class') not in ('Audio/Source', 'Audio/Duplex'):
                continue
            name = props.get('node.name')
            if not name:
                continue
            description = props.get('node.description') or props.get('node.nick') or name
            microphones.append({'id': name, 'name': description, 'full': name})
        return microphones

    @staticmethod
    def _list_pulseaudio_sources():
        """List PulseAudio sources, skipping monitors of output sinks."""
        if not shutil.which('pactl'):
            return []
        try:
            result = subprocess.run(['pactl', 'list', 'sources', 'short'],
                                    capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return []

        microphones = []
        for line in result.stdout.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2 and not parts[1].endswith('.monitor'):
                microphones.append({'id': parts[1], 'name': parts[1], 'full': line.strip()})
        return microphones

    def start(self):
        """Start microphone capture."""
        self.backend = self._detect_backend()
        if not self.backend:
            raise RuntimeError("No audio backend found. Install PipeWire or PulseAudio.")

        source = self._get_default_source()
        
        if self.backend == 'pipewire':
            cmd = [
                'pw-record',
                '--format', 's16',
                '--rate', str(self.sample_rate),
                '--channels', '1',
            ]
            if source:
                cmd.extend(['--target', source])
            cmd.append('-')
            source_name = source or "default microphone"
        else:
            cmd = [
                'parec',
                '--format=s16le',
                f'--rate={self.sample_rate}',
                '--channels=1',
            ]
            if source:
                cmd.extend(['-d', source])
            source_name = source or "default microphone"

        print(f"Starting microphone capture: {source_name} ({self.backend})")

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

        return source_name

    def _capture_loop(self):
        """Capture audio in background thread."""
        bytes_per_chunk = self.chunk_size * 2  # 16-bit = 2 bytes per sample

        while self.running and self.process:
            data = self.process.stdout.read(bytes_per_chunk)
            if not data:
                break

            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

            try:
                # Use blocking put with timeout to avoid race conditions
                self.audio_queue.put(audio, timeout=0.1)
            except queue.Full:
                # Queue is full even after timeout, drop this chunk
                pass

    def get_audio(self, timeout=1.0):
        """Get audio chunk from queue."""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        """Stop microphone capture."""
        self.running = False
        if self.process:
            self.process.terminate()
            self.process.wait()
            self.process = None
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None


def list_available_microphones():
    """Convenience function to list available microphones."""
    capture = MicCapture()
    capture.backend = capture._detect_backend()
    return capture.list_microphones()


if __name__ == "__main__":
    # Test microphone capture
    print("Available microphones:")
    mics = list_available_microphones()
    for mic in mics:
        print(f"  {mic['id']}: {mic['name']}")
    
    print("\nTesting microphone capture (5 seconds)...")
    capture = MicCapture()
    source = capture.start()
    print(f"Capturing from: {source}")
    
    import time
    start = time.time()
    chunks = 0
    
    while time.time() - start < 5:
        audio = capture.get_audio(timeout=0.5)
        if audio is not None:
            chunks += 1
            level = np.abs(audio).mean() * 100
            bars = int(level * 50)
            print(f"\rLevel: {'█' * bars}{' ' * (50-bars)} {level:.1f}%", end='')
    
    print(f"\n\nCaptured {chunks} chunks")
    capture.stop()
