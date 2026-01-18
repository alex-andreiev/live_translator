"""
Text-to-Speech engine module using Piper TTS or espeak as fallback
"""
import subprocess
import shutil
import os
import tempfile
import wave
import numpy as np
from pathlib import Path
import urllib.request
import tarfile


# Piper voice models - English voices optimized for quality/speed
PIPER_VOICES = {
    'en_US-lessac-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json',
        'description': 'US English, male, medium quality'
    },
    'en_US-amy-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json',
        'description': 'US English, female, medium quality'
    },
    'en_GB-alan-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json',
        'description': 'British English, male, medium quality'
    },
    'de_DE-thorsten-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json',
        'description': 'German, male, medium quality'
    },
    'fr_FR-upmc-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json',
        'description': 'French, male, medium quality'
    },
    'es_ES-davefx-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json',
        'description': 'Spanish, male, medium quality'
    },
    'ru_RU-irina-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json',
        'description': 'Russian, female, medium quality'
    },
    'uk_UA-ukrainian_tts-medium': {
        'url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium.onnx',
        'config_url': 'https://huggingface.co/rhasspy/piper-voices/resolve/main/uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium.onnx.json',
        'description': 'Ukrainian, medium quality'
    },
}

# Language to default voice mapping
LANGUAGE_VOICES = {
    'english': 'en_US-lessac-medium',
    'german': 'de_DE-thorsten-medium',
    'french': 'fr_FR-upmc-medium',
    'spanish': 'es_ES-davefx-medium',
    'russian': 'ru_RU-irina-medium',
    'ukrainian': 'uk_UA-ukrainian_tts-medium',
}


class TTSEngine:
    """Text-to-Speech engine with Piper TTS or espeak fallback."""
    
    def __init__(self, voice='en_US-lessac-medium', models_dir=None):
        """
        Initialize TTS engine.
        
        Args:
            voice: Voice model name (from PIPER_VOICES)
            models_dir: Directory to store voice models
        """
        self.voice = voice
        self.models_dir = Path(models_dir or Path.home() / ".local" / "share" / "piper-tts")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.piper_available = self._check_piper()
        self.espeak_available = shutil.which('espeak-ng') or shutil.which('espeak')
        
        self.sample_rate = 22050  # Piper default
        
        if self.piper_available:
            print(f"TTS Engine: Using Piper with voice '{voice}'")
        elif self.espeak_available:
            print("TTS Engine: Piper not found, using espeak-ng fallback")
        else:
            print("WARNING: No TTS engine found! Install piper-tts or espeak-ng")
    
    def _check_piper(self):
        """Check if Piper TTS is available."""
        return shutil.which('piper') is not None
    
    def _download_voice(self, voice_name):
        """Download Piper voice model if not exists."""
        if voice_name not in PIPER_VOICES:
            print(f"Unknown voice: {voice_name}")
            return None, None
        
        voice_info = PIPER_VOICES[voice_name]
        model_path = self.models_dir / f"{voice_name}.onnx"
        config_path = self.models_dir / f"{voice_name}.onnx.json"
        
        # Download model if not exists
        if not model_path.exists():
            print(f"Downloading voice model: {voice_name}...")
            try:
                urllib.request.urlretrieve(voice_info['url'], model_path)
                print(f"Downloaded: {model_path}")
            except Exception as e:
                print(f"Error downloading voice model: {e}")
                return None, None
        
        # Download config if not exists
        if not config_path.exists():
            try:
                urllib.request.urlretrieve(voice_info['config_url'], config_path)
            except Exception as e:
                print(f"Error downloading voice config: {e}")
                return None, None
        
        return str(model_path), str(config_path)
    
    def set_voice(self, voice):
        """Change the voice model."""
        self.voice = voice
    
    def set_voice_for_language(self, language):
        """Set voice based on target language."""
        lang_lower = language.lower()
        if lang_lower in LANGUAGE_VOICES:
            self.voice = LANGUAGE_VOICES[lang_lower]
            print(f"TTS: Using voice '{self.voice}' for {language}")
            return True
        return False
    
    def synthesize(self, text, output_file=None):
        """
        Synthesize speech from text.
        
        Args:
            text: Text to synthesize
            output_file: Optional output WAV file path
        
        Returns:
            Audio data as numpy array (float32, mono)
        """
        if not text or not text.strip():
            return None
        
        if self.piper_available:
            return self._synthesize_piper(text, output_file)
        elif self.espeak_available:
            return self._synthesize_espeak(text, output_file)
        else:
            print("No TTS engine available!")
            return None
    
    def _synthesize_piper(self, text, output_file=None):
        """Synthesize using Piper TTS."""
        # Download voice if needed
        model_path, config_path = self._download_voice(self.voice)
        if not model_path:
            # Fallback to espeak
            if self.espeak_available:
                return self._synthesize_espeak(text, output_file)
            return None
        
        # Create temp file for output
        if output_file:
            wav_path = output_file
        else:
            fd, wav_path = tempfile.mkstemp(suffix='.wav')
            os.close(fd)
        
        try:
            # Run Piper
            cmd = [
                'piper',
                '--model', model_path,
                '--output_file', wav_path
            ]
            
            process = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True
            )
            
            if process.returncode != 0:
                print(f"Piper error: {process.stderr}")
                return None
            
            # Read WAV file
            audio = self._read_wav(wav_path)
            
            return audio
            
        finally:
            # Cleanup temp file
            if not output_file and os.path.exists(wav_path):
                os.remove(wav_path)
    
    def _synthesize_espeak(self, text, output_file=None):
        """Synthesize using espeak-ng as fallback."""
        espeak_cmd = 'espeak-ng' if shutil.which('espeak-ng') else 'espeak'
        
        # Map voice to espeak language
        lang_map = {
            'en_US': 'en-us',
            'en_GB': 'en-gb',
            'de_DE': 'de',
            'fr_FR': 'fr',
            'es_ES': 'es',
            'ru_RU': 'ru',
            'uk_UA': 'uk',
        }
        
        voice_prefix = self.voice.split('-')[0] if '-' in self.voice else 'en_US'
        espeak_voice = lang_map.get(voice_prefix, 'en-us')
        
        # Create temp file for output
        if output_file:
            wav_path = output_file
        else:
            fd, wav_path = tempfile.mkstemp(suffix='.wav')
            os.close(fd)
        
        try:
            cmd = [
                espeak_cmd,
                '-v', espeak_voice,
                '-w', wav_path,
                text
            ]
            
            subprocess.run(cmd, capture_output=True)
            
            # Read WAV file
            audio = self._read_wav(wav_path)
            self.sample_rate = 22050  # espeak default
            
            return audio
            
        finally:
            if not output_file and os.path.exists(wav_path):
                os.remove(wav_path)
    
    def _read_wav(self, wav_path):
        """Read WAV file and return as numpy array."""
        try:
            with wave.open(wav_path, 'rb') as wf:
                self.sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                audio_data = wf.readframes(n_frames)
                
                # Convert to numpy
                if wf.getsampwidth() == 2:
                    audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
                elif wf.getsampwidth() == 1:
                    audio = np.frombuffer(audio_data, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0
                else:
                    audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
                
                # Convert to mono if stereo
                if wf.getnchannels() == 2:
                    audio = audio.reshape(-1, 2).mean(axis=1)
                
                return audio
        except Exception as e:
            print(f"Error reading WAV: {e}")
            return None
    
    def synthesize_to_file(self, text, output_path):
        """Synthesize and save directly to file."""
        audio = self.synthesize(text, output_file=output_path)
        return audio is not None
    
    def get_available_voices(self):
        """Get list of available voices."""
        return list(PIPER_VOICES.keys())
    
    def get_voice_description(self, voice_name):
        """Get description of a voice."""
        if voice_name in PIPER_VOICES:
            return PIPER_VOICES[voice_name]['description']
        return "Unknown voice"


def list_available_voices():
    """List all available TTS voices."""
    print("Available Piper voices:")
    for name, info in PIPER_VOICES.items():
        print(f"  {name}: {info['description']}")


if __name__ == "__main__":
    import sys
    
    list_available_voices()
    
    print("\nTesting TTS engine...")
    tts = TTSEngine()
    
    test_text = "Hello! This is a test of the text to speech engine."
    print(f"Synthesizing: '{test_text}'")
    
    audio = tts.synthesize(test_text)
    if audio is not None:
        print(f"Generated audio: {len(audio)} samples, {tts.sample_rate} Hz")
        print(f"Duration: {len(audio) / tts.sample_rate:.2f} seconds")
        
        # Save test file
        tts.synthesize_to_file(test_text, "/tmp/tts_test.wav")
        print("Saved to /tmp/tts_test.wav")
        
        # Play if possible
        if shutil.which('aplay'):
            print("Playing audio...")
            subprocess.run(['aplay', '/tmp/tts_test.wav'])
    else:
        print("Failed to synthesize audio!")
