from .base import HTTPAdapter


class DeepSeekAdapter(HTTPAdapter):
    default_url = "https://api.deepseek.com"
    key_env = "DEEPSEEK_API_KEY"
    requires_key = True

    def chat_payload(self, model, prompt):
        payload = super().chat_payload(model, prompt)
        # Non-thinking mode keeps live translation latency down.
        if model.startswith("deepseek-v4"):
            payload["thinking"] = {"type": "disabled"}
        return payload
