import logging
from typing import List

from app.services.ai.config import (
    CLAUDE_API_KEY,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    MISTRAL_API_KEY,
    MISTRAL_BASE_URL,
    MISTRAL_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    TOGETHER_API_KEY,
    TOGETHER_BASE_URL,
    TOGETHER_MODEL,
    XAI_API_KEY,
    XAI_BASE_URL,
    XAI_MODEL,
)
from app.services.ai.models import AIRequest, AIResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    def __init__(self, provider_name: str, api_key: str, model: str, base_url: str):
        self.provider_name = provider_name
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate(self, request: AIRequest) -> AIResponse:
        import requests

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return AIResponse(
            success=True,
            provider=self.provider_name,
            model=self.model,
            content=content,
            usage=data.get("usage"),
        )


class GeminiProvider:
    def __init__(self):
        self.provider_name = "gemini"
        self.api_key = GEMINI_API_KEY
        self.model = "gemini-1.5-flash"

    def generate(self, request: AIRequest) -> AIResponse:
        import requests

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{request.system_prompt or ''}\n\n{request.prompt}"}
                    ]
                }
            ],
            "generationConfig": {"temperature": request.temperature, "maxOutputTokens": request.max_tokens},
        }
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return AIResponse(success=True, provider="gemini", model=self.model, content=content)


class ClaudeProvider:
    def __init__(self):
        self.provider_name = "claude"
        self.api_key = CLAUDE_API_KEY
        self.model = "claude-3-5-sonnet-20241022"

    def generate(self, request: AIRequest) -> AIResponse:
        import requests

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "messages": [{"role": "user", "content": request.prompt}],
                "system": request.system_prompt or "You are a helpful assistant.",
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        content = data["content"][0]["text"]
        return AIResponse(success=True, provider="claude", model=self.model, content=content)


class AIManager:
    def __init__(self):
        self.providers: List[object] = []
        self._register_providers()

    def _register_providers(self):
        if GEMINI_API_KEY:
            self.providers.append(GeminiProvider())
        if XAI_API_KEY:
            self.providers.append(OpenAICompatibleProvider("grok", XAI_API_KEY, XAI_MODEL, XAI_BASE_URL))
        if GROQ_API_KEY:
            self.providers.append(OpenAICompatibleProvider("groq", GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL))
        if OPENAI_API_KEY:
            self.providers.append(OpenAICompatibleProvider("openai", OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL))
        if DEEPSEEK_API_KEY:
            self.providers.append(OpenAICompatibleProvider("deepseek", DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL))
        if MISTRAL_API_KEY:
            self.providers.append(OpenAICompatibleProvider("mistral", MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_BASE_URL))
        if OPENROUTER_API_KEY:
            self.providers.append(OpenAICompatibleProvider("openrouter", OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL))
        if TOGETHER_API_KEY:
            self.providers.append(OpenAICompatibleProvider("together", TOGETHER_API_KEY, TOGETHER_MODEL, TOGETHER_BASE_URL))
        if CLAUDE_API_KEY:
            self.providers.append(ClaudeProvider())

    def generate(self, request: AIRequest) -> AIResponse:
        if not self.providers:
            raise RuntimeError("No AI providers are configured. Add GEMINI_API_KEY, OPENAI_API_KEY, or another supported provider in .env.")

        errors = []
        for provider in self.providers:
            provider_name = getattr(provider, "provider_name", provider.__class__.__name__)
            try:
                result = provider.generate(request)
                if result.success and result.content:
                    return result
                errors.append(f"{provider_name}: empty response")
            except Exception as exc:
                errors.append(f"{provider_name}: {type(exc).__name__}")
        raise RuntimeError("All configured AI providers failed. " + " | ".join(errors))
