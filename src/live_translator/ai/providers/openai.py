from .base import HTTPAdapter


class OpenAIAdapter(HTTPAdapter):
    default_url = "https://api.openai.com/v1"
    key_env = "OPENAI_API_KEY"
    requires_key = True
