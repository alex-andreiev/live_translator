"""
Shared API client for LLM providers (Ollama, OpenAI, Anthropic)
"""
import ollama


class APIClient:
    """Unified client for multiple LLM providers."""

    def __init__(self, provider="ollama", model="mistral:7b", timeout=30):
        """
        Initialize API client.

        Args:
            provider: LLM provider (ollama, openai, anthropic)
            model: Model name
            timeout: Request timeout in seconds
        """
        self.provider = provider
        self.model = model
        self.timeout = timeout

    def set_settings(self, provider=None, model=None, timeout=None):
        """Update client settings."""
        if provider:
            self.provider = provider
        if model:
            self.model = model
        if timeout:
            self.timeout = timeout

    def generate(self, prompt):
        """
        Generate text completion from a prompt.

        Args:
            prompt: The prompt to send to the model

        Returns:
            Generated text or None on error
        """
        if not prompt or not prompt.strip():
            return None

        try:
            if self.provider == "ollama":
                return self._generate_ollama(prompt)
            elif self.provider == "openai":
                return self._generate_openai(prompt)
            elif self.provider == "anthropic":
                return self._generate_anthropic(prompt)
            else:
                print(f"Unknown provider: {self.provider}")
                return None
        except Exception as e:
            print(f"API client error: {e}")
            return None

    def _generate_ollama(self, prompt):
        """Generate using Ollama."""
        response = ollama.generate(
            model=self.model,
            prompt=prompt,
            stream=False,
            options={'timeout': self.timeout}
        )
        result = response.get('response') if isinstance(response, dict) else getattr(response, 'response', None)
        return result.strip() if result else None

    def _generate_openai(self, prompt):
        """Generate using OpenAI API."""
        try:
            import openai
            client = openai.OpenAI()
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                timeout=self.timeout
            )
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                return content.strip() if content else None
            return None
        except ImportError:
            print("OpenAI package not installed. Run: pip install openai")
            return None

    def _generate_anthropic(self, prompt):
        """Generate using Anthropic API."""
        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
                timeout=self.timeout
            )
            if response.content and len(response.content) > 0:
                text = response.content[0].text
                return text.strip() if text else None
            return None
        except ImportError:
            print("Anthropic package not installed. Run: pip install anthropic")
            return None


# Convenience function for simple use cases
def generate_text(prompt, provider="ollama", model="mistral:7b", timeout=30):
    """
    One-shot text generation.

    Args:
        prompt: The prompt to send
        provider: LLM provider
        model: Model name
        timeout: Request timeout

    Returns:
        Generated text or None
    """
    client = APIClient(provider=provider, model=model, timeout=timeout)
    return client.generate(prompt)
