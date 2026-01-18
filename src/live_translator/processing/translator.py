"""
Translation module using Ollama or other providers
"""
from live_translator.ai import APIClient


class Translator:
    def __init__(self, provider="ollama", model="mistral:7b", target_language="Russian", prompt=None):
        """
        Initialize translator.

        Args:
            provider: Translation provider (ollama, openai, anthropic)
            model: Model name
            target_language: Target language for translation
            prompt: Custom prompt template (use {text} and {target_language} as placeholders)
        """
        self.provider = provider
        self.model = model
        self.target_language = target_language
        self.prompt_template = prompt or (
            "Translate the following text to {target_language}. "
            "Output ONLY the translation, nothing else:\n\n{text}"
        )
        # Use shared API client with timeout
        self._client = APIClient(provider=provider, model=model, timeout=30)

    def set_settings(self, provider=None, model=None, target_language=None, prompt=None):
        """Update translator settings."""
        if provider:
            self.provider = provider
        if model:
            self.model = model
        if target_language:
            self.target_language = target_language
        if prompt:
            self.prompt_template = prompt
        # Update API client settings
        self._client.set_settings(provider=provider, model=model)

    def translate(self, text):
        """
        Translate text to target language.

        Args:
            text: Text to translate

        Returns:
            Translated text or None on error
        """
        if not text or not text.strip():
            return None

        prompt = self.prompt_template.format(
            text=text,
            target_language=self.target_language
        )

        try:
            return self._client.generate(prompt)
        except Exception as e:
            print(f"Translation error: {e}")
            return None


if __name__ == "__main__":
    # Test translator
    translator = Translator()

    test_texts = [
        "Hello, how are you?",
        "The weather is nice today.",
        "This is a test of the translation system."
    ]

    for text in test_texts:
        print(f"EN: {text}")
        result = translator.translate(text)
        print(f"RU: {result}")
        print("-" * 40)
