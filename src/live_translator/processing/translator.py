"""
Translation through the configured provider adapter (see live_translator.ai.providers).
"""
from live_translator.ai import APIClient


class Translator:
    def __init__(self, provider="ollama", model="mistral:7b", target_language="Russian", prompt=None):
        """
        Initialize translator.

        Args:
            provider: Provider key from live_translator.ai.providers.PROVIDERS
                ("none" transcribes without translating)
            model: Model ID for that provider
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

    @property
    def last_error(self):
        """Message from the most recent failed request, or None."""
        return self._client.last_error

    def set_settings(self, provider=None, model=None, target_language=None, prompt=None):
        """Update translator settings; None leaves a field unchanged."""
        # Compare against None so "none" and a cleared model still apply.
        if provider is not None:
            self.provider = provider
        if model is not None:
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
        if not text or not text.strip() or self.provider == "none":
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
