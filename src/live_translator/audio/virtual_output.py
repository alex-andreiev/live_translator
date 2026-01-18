"""
Virtual audio output module for routing synthesized speech to applications.
Uses PipeWire to create a virtual microphone sink that other apps can use as input.
"""

import subprocess
import threading
import struct
import time
from typing import Optional, Callable


class VirtualOutput:
    """
    Outputs synthesized audio to a virtual microphone using PipeWire.
    Creates a virtual sink that video call apps can select as microphone input.
    """
    
    def __init__(self, 
                 sink_name: str = "LiveTranslator_VirtualMic",
                 sample_rate: int = 16000,
                 channels: int = 1):
        """
        Initialize virtual output.
        
        Args:
            sink_name: Name for the virtual sink (visible in audio settings)
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels (1 = mono, 2 = stereo)
        """
        self.sink_name = sink_name
        self.sample_rate = sample_rate
        self.channels = channels
        self._module_id: Optional[int] = None
        self._monitor_source: Optional[str] = None
        self._is_active = False
        self._lock = threading.Lock()
        
    def create_virtual_sink(self) -> bool:
        """
        Create a virtual sink using PipeWire/PulseAudio.
        Returns True if successful.
        """
        with self._lock:
            if self._is_active:
                return True
                
            try:
                # Try PipeWire first (pactl works with PipeWire's pulse compatibility)
                result = subprocess.run(
                    [
                        "pactl", "load-module", "module-null-sink",
                        f"sink_name={self.sink_name}",
                        f"sink_properties=device.description=\"Live_Translator_Virtual_Mic\"",
                        f"rate={self.sample_rate}",
                        f"channels={self.channels}"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    # Validate module ID is numeric before conversion
                    module_id_str = result.stdout.strip()
                    if module_id_str.isdigit():
                        self._module_id = int(module_id_str)
                    else:
                        print(f"Warning: Unexpected module ID format: {module_id_str}")
                        self._module_id = None
                    self._monitor_source = f"{self.sink_name}.monitor"
                    self._is_active = True
                    print(f"Created virtual sink: {self.sink_name}")
                    print(f"Monitor source: {self._monitor_source}")
                    print(f"Module ID: {self._module_id}")
                    return True
                else:
                    print(f"Failed to create virtual sink: {result.stderr}")
                    return False
                    
            except FileNotFoundError:
                print("pactl not found. Please install pulseaudio-utils or pipewire-pulse.")
                return False
            except subprocess.TimeoutExpired:
                print("Timeout creating virtual sink")
                return False
            except Exception as e:
                print(f"Error creating virtual sink: {e}")
                return False
    
    def destroy_virtual_sink(self) -> bool:
        """
        Remove the virtual sink.
        Returns True if successful.
        """
        with self._lock:
            if not self._is_active or self._module_id is None:
                return True
                
            try:
                result = subprocess.run(
                    ["pactl", "unload-module", str(self._module_id)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    print(f"Removed virtual sink module {self._module_id}")
                    self._module_id = None
                    self._monitor_source = None
                    self._is_active = False
                    return True
                else:
                    print(f"Failed to remove virtual sink: {result.stderr}")
                    return False
                    
            except Exception as e:
                print(f"Error removing virtual sink: {e}")
                return False
    
    def get_monitor_source(self) -> Optional[str]:
        """
        Get the monitor source name that apps should use as microphone input.
        """
        return self._monitor_source
    
    def play_audio(self, audio_data: bytes, sample_rate: Optional[int] = None) -> bool:
        """
        Play audio data to the virtual sink.
        
        Args:
            audio_data: Raw PCM audio data (16-bit signed, little-endian)
            sample_rate: Sample rate of audio (uses default if None)
            
        Returns:
            True if playback started successfully
        """
        if not self._is_active:
            if not self.create_virtual_sink():
                return False
        
        rate = sample_rate or self.sample_rate
        
        try:
            # Use paplay to send audio to the sink
            process = subprocess.Popen(
                [
                    "paplay",
                    "--raw",
                    f"--rate={rate}",
                    f"--channels={self.channels}",
                    "--format=s16le",
                    f"--device={self.sink_name}"
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )
            
            process.communicate(input=audio_data, timeout=30)
            return process.returncode == 0
            
        except subprocess.TimeoutExpired:
            process.kill()
            print("Audio playback timeout")
            return False
        except Exception as e:
            print(f"Error playing audio: {e}")
            return False
    
    def play_audio_async(self, audio_data: bytes, 
                         sample_rate: Optional[int] = None,
                         callback: Optional[Callable[[], None]] = None) -> threading.Thread:
        """
        Play audio in a background thread.
        
        Args:
            audio_data: Raw PCM audio data
            sample_rate: Sample rate
            callback: Optional callback when playback completes
            
        Returns:
            Thread object
        """
        def _play():
            self.play_audio(audio_data, sample_rate)
            if callback:
                callback()
        
        thread = threading.Thread(target=_play, daemon=True)
        thread.start()
        return thread
    
    def is_active(self) -> bool:
        """Check if virtual sink is active."""
        return self._is_active
    
    @staticmethod
    def list_sinks() -> list[dict]:
        """
        List available audio sinks.
        Returns list of sink info dicts.
        """
        sinks = []
        try:
            result = subprocess.run(
                ["pactl", "list", "sinks", "short"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            sinks.append({
                                'id': parts[0],
                                'name': parts[1],
                                'driver': parts[2] if len(parts) > 2 else '',
                                'format': parts[3] if len(parts) > 3 else '',
                                'state': parts[4] if len(parts) > 4 else ''
                            })
        except Exception as e:
            print(f"Error listing sinks: {e}")
            
        return sinks
    
    @staticmethod
    def list_sources() -> list[dict]:
        """
        List available audio sources (microphones and monitors).
        Returns list of source info dicts.
        """
        sources = []
        try:
            result = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            sources.append({
                                'id': parts[0],
                                'name': parts[1],
                                'driver': parts[2] if len(parts) > 2 else '',
                                'format': parts[3] if len(parts) > 3 else '',
                                'state': parts[4] if len(parts) > 4 else ''
                            })
        except Exception as e:
            print(f"Error listing sources: {e}")
            
        return sources
    
    def __enter__(self):
        """Context manager entry - create sink."""
        self.create_virtual_sink()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - destroy sink."""
        self.destroy_virtual_sink()
        return False


# Test if run directly
if __name__ == "__main__":
    print("Testing VirtualOutput...")
    
    # List available sinks
    print("\n=== Available Sinks ===")
    for sink in VirtualOutput.list_sinks():
        print(f"  {sink['name']}")
    
    # List available sources
    print("\n=== Available Sources ===")
    for source in VirtualOutput.list_sources():
        print(f"  {source['name']}")
    
    # Test virtual sink creation
    print("\n=== Testing Virtual Sink ===")
    with VirtualOutput() as vo:
        print(f"Virtual sink active: {vo.is_active()}")
        print(f"Monitor source: {vo.get_monitor_source()}")
        
        # Generate a test tone
        import math
        duration = 1.0  # seconds
        frequency = 440  # Hz
        samples = int(16000 * duration)
        audio = b''
        for i in range(samples):
            t = i / 16000
            value = int(32767 * 0.5 * math.sin(2 * math.pi * frequency * t))
            audio += struct.pack('<h', value)
        
        print("Playing test tone (440 Hz)...")
        vo.play_audio(audio)
        print("Done!")
    
    print("\nVirtual sink cleaned up")
