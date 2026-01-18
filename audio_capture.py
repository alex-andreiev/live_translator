"""
Audio capture module - captures system audio using PipeWire or PulseAudio
"""
import subprocess
import threading
import queue
import shutil
import numpy as np

class AudioCapture:
    def __init__(self, sample_rate=16000, chunk_duration=0.25):
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_duration)
        self.audio_queue = queue.Queue(maxsize=50)  # Prevent excessive buffering
        self.running = False
        self.process = None
        self.thread = None
        self.backend = None

    def _detect_backend(self):
        """Detect available audio backend."""
        if shutil.which('pw-record'):
            return 'pipewire'
        elif shutil.which('parec'):
            return 'pulseaudio'
        return None

    def _get_pipewire_monitor(self):
        """Get PipeWire monitor target for system audio."""
        try:
            # Get the default sink ID
            result = subprocess.run(
                ['wpctl', 'inspect', '@DEFAULT_AUDIO_SINK@'],
                capture_output=True, text=True
            )
            for line in result.stdout.split('\n'):
                if 'node.name' in line:
                    sink_name = line.split('=')[1].strip().strip('"')
                    return f"{sink_name}.monitor"
        except Exception as e:
            print(f"Error getting PipeWire monitor: {e}")
        return None

    def _get_pulseaudio_monitor(self):
        """Find the PulseAudio monitor source for system audio."""
        try:
            result = subprocess.run(
                ['pactl', 'list', 'short', 'sources'],
                capture_output=True, text=True
            )
            for line in result.stdout.strip().split('\n'):
                if '.monitor' in line:
                    return line.split()[1]
        except Exception as e:
            print(f"Error finding PulseAudio monitor: {e}")
        return None

    def start(self):
        """Start capturing audio."""
        self.backend = self._detect_backend()

        if self.backend == 'pipewire':
            monitor = self._get_pipewire_monitor()
            if not monitor:
                # Try default monitor
                monitor = "default"
        elif self.backend == 'pulseaudio':
            monitor = self._get_pulseaudio_monitor()
        else:
            raise RuntimeError("No audio backend found. Install pipewire or pulseaudio.")

        if not monitor:
            raise RuntimeError("No audio monitor source found.")

        self.running = True
        self.thread = threading.Thread(
            target=self._capture_loop,
            args=(monitor,),
            daemon=True
        )
        self.thread.start()
        return f"{self.backend}:{monitor}"

    def _capture_loop(self, monitor):
        """Capture audio using pw-record or parec."""
        if self.backend == 'pipewire':
            cmd = [
                'pw-record',
                '--target', monitor,
                '--rate', str(self.sample_rate),
                '--channels', '1',
                '--format', 's16',
                '-'
            ]
        else:  # pulseaudio
            cmd = [
                'parec',
                '--device', monitor,
                '--rate', str(self.sample_rate),
                '--channels', '1',
                '--format', 's16le',
                '--latency-msec', '100'
            ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"Failed to start audio capture: {e}")
            return

        bytes_per_chunk = self.chunk_size * 2  # 16-bit = 2 bytes per sample

        while self.running:
            data = self.process.stdout.read(bytes_per_chunk)
            if not data:
                break

            # Convert to numpy float32 array normalized to [-1, 1]
            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            self.audio_queue.put(audio)

    def get_audio(self, timeout=1.0):
        """Get audio chunk from queue."""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        """Stop capturing audio."""
        self.running = False
        if self.process:
            self.process.terminate()
            self.process.wait()
        if self.thread:
            self.thread.join(timeout=2.0)


if __name__ == "__main__":
    # Test audio capture
    capture = AudioCapture()
    print(f"Starting capture from: {capture.start()}")

    try:
        for i in range(10):
            audio = capture.get_audio()
            if audio is not None:
                print(f"Chunk {i}: {len(audio)} samples, max amplitude: {np.abs(audio).max():.3f}")
    finally:
        capture.stop()
        print("Stopped")
