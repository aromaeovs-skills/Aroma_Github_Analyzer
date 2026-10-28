from typing import Any, Dict, Optional

from pydantic import BaseModel


class AIRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 2048


class AIResponse(BaseModel):
    success: bool
    provider: str
    model: str
    content: str
    usage: Optional[Dict[str, Any]] = None
