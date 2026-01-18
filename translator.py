"""
Translation module using Ollama or other providers
"""
import ollama

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
            if self.provider == "ollama":
                return self._translate_ollama(prompt)
            elif self.provider == "openai":
                return self._translate_openai(prompt)
            elif self.provider == "anthropic":
                return self._translate_anthropic(prompt)
            else:
                print(f"Unknown provider: {self.provider}")
                return None
        except Exception as e:
            print(f"Translation error: {e}")
            return None

    def _translate_ollama(self, prompt):
        """Translate using Ollama."""
        response = ollama.generate(
            model=self.model,
            prompt=prompt,
            stream=False
        )
        return response['response'].strip()

    def _translate_openai(self, prompt):
        """Translate using OpenAI API."""
        try:
            import openai
            client = openai.OpenAI()
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
        except ImportError:
            print("OpenAI package not installed. Run: pip install openai")
            return None

    def _translate_anthropic(self, prompt):
        """Translate using Anthropic API."""
        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except ImportError:
            print("Anthropic package not installed. Run: pip install anthropic")
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
