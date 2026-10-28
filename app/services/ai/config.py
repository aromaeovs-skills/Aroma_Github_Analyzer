import os

from dotenv import load_dotenv

load_dotenv()


def is_real_secret(value: str | None) -> bool:
    if not value:
        return False
    cleaned = value.strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    placeholder_markers = (
        "your_",
        "example",
        "placeholder",
        "changeme",
        "key_here",
        "insert_",
        "todo",
        "dummy",
    )
    if any(marker in lowered for marker in placeholder_markers):
        return False
    return len(cleaned) >= 10


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if isinstance(value, str):
        value = value.strip()
    value = value or default
    if value is not None and not is_real_secret(value):
        return None
    return value


GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-latest")

OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-5-mini")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1")

XAI_API_KEY = env("XAI_API_KEY")
XAI_MODEL = env("XAI_MODEL", "grok-4.5")
XAI_BASE_URL = env("XAI_BASE_URL", "https://api.x.ai/v1")

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY") or env("CLAUDE_API_KEY")
CLAUDE_API_KEY = ANTHROPIC_API_KEY
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-sonnet-4-5")

GROQ_API_KEY = env("GROQ_API_KEY")
GROQ_MODEL = env("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

MISTRAL_API_KEY = env("MISTRAL_API_KEY")
MISTRAL_MODEL = env("MISTRAL_MODEL", "mistral-small-latest")
MISTRAL_BASE_URL = env("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")

DEEPSEEK_API_KEY = env("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = env("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

COHERE_API_KEY = env("COHERE_API_KEY")
COHERE_MODEL = env("COHERE_MODEL", "command-a-plus-05-2026")

OPENROUTER_API_KEY = env("OPENROUTER_API_KEY")
OPENROUTER_MODEL = env("OPENROUTER_MODEL", "openai/gpt-5-mini")
OPENROUTER_BASE_URL = env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

TOGETHER_API_KEY = env("TOGETHER_API_KEY")
TOGETHER_MODEL = env("TOGETHER_MODEL")
TOGETHER_BASE_URL = env("TOGETHER_BASE_URL", "https://api.together.xyz/v1")

OLLAMA_URL = env("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "llama3.1:8b")

GITHUB_TOKEN = env("GITHUB_TOKEN")
