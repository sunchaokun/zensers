"""
LLM Client - Standalone LLM invocation utility, not a Skill.

LLM is an intrinsic agent capability, not an external tool.
Agents should call LLM directly, not through the skill registry.

Features:
- OpenAI-compatible interface
- System prompt support
- Automatic fallback to backup model
- Token usage tracking
- Configuration-driven (settings.llm.*)
- Multimodal/Vision support (call_llm_vision)
"""
import base64
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from src.config import settings
from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint

logger = logging.getLogger(__name__)

_router: Optional[Any] = None
_client_pool: Optional[Any] = None


def init_llm_infrastructure(registry: LLMProfileRegistry):
    global _router, _client_pool
    from src.core.llm_router import LLMRouter
    from src.core.llm_client_pool import LLMClientPool
    _router = LLMRouter(registry)
    _client_pool = LLMClientPool()


async def call_llm_stream(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: str = "",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Streaming variant of call_llm. Yields content tokens as they arrive.

    No retry/fallback — callers should catch exceptions and degrade to call_llm().
    Does NOT trigger _on_complete_var (not defined in this module).
    """
    model = model or settings.llm.model
    max_tokens = max_tokens or settings.llm.max_tokens
    temperature = temperature or settings.llm.temperature
    api_key = api_key or settings.llm.api_key
    base_url = base_url or settings.llm.base_url

    if not prompt or not prompt.strip():
        return

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=settings.llm.top_p,
        frequency_penalty=settings.llm.frequency_penalty,
        presence_penalty=settings.llm.presence_penalty,
        stream=True,
    )
    async for chunk in response:
        choices = chunk.choices if chunk.choices else []
        if choices:
            delta = choices[0].delta
            if delta and delta.content:
                yield delta.content


async def call_llm(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: str = "",
    fallback_model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    routing_hint: Optional[RoutingHint] = None,
) -> Dict[str, Any]:
    """
    Call LLM (standalone utility, not a skill).

    Args:
        prompt: User prompt (required)
        model: Model name (default from settings.llm.model)
        system_prompt: System prompt (optional)
        fallback_model: Fallback model (default from settings.llm.cheap_model)
        max_tokens: Max generation tokens (default from settings.llm.max_tokens)
        temperature: Temperature (default from settings.llm.temperature)
        api_key: API key (default from settings.llm.api_key)
        base_url: API base URL (default from settings.llm.base_url)
        routing_hint: Optional routing hint for profile-based routing

    Returns:
        Dict with keys: success, content, model, usage
        On failure: success=False, message=str, error=str
    """
    if routing_hint is not None and _router is not None and model is None:
        profile = _router.resolve(routing_hint)
        model = profile.model
        fallback_model = profile.fallback_model
        max_tokens = max_tokens or profile.max_tokens
        temperature = temperature or profile.temperature
        api_key = api_key or profile.api_key
        base_url = base_url or profile.base_url

    model = model or settings.llm.model
    fallback_model = fallback_model or settings.llm.cheap_model
    max_tokens = max_tokens or settings.llm.max_tokens
    temperature = temperature or settings.llm.temperature
    api_key = api_key or settings.llm.api_key
    base_url = base_url or settings.llm.base_url

    if not prompt or not prompt.strip():
        return {"success": False, "message": "prompt cannot be empty", "error": "empty_prompt"}

    # Cost limit check
    if settings.llm.cost_limit_per_report > 0:
        estimated_cost = (max_tokens / 1000) * 0.01
        if estimated_cost > settings.llm.cost_limit_per_report:
            return {
                "success": False,
                "message": f"Estimated cost ${estimated_cost:.4f} exceeds limit ${settings.llm.cost_limit_per_report:.2f}",
                "error": "cost_limit",
            }

    # Try primary model
    try:
        response = await _call_llm_api(prompt=prompt, model=model, system_prompt=system_prompt,
                                       max_tokens=max_tokens, temperature=temperature,
                                       api_key=api_key, base_url=base_url)
        return _parse_response(response, model)
    except Exception as primary_err:
        if fallback_model and fallback_model != model:
            try:
                response = await _call_llm_api(prompt=prompt, model=fallback_model, system_prompt=system_prompt,
                                               max_tokens=max_tokens, temperature=temperature,
                                               api_key=api_key, base_url=base_url)
                result = _parse_response(response, fallback_model)
                result["fallback_used"] = True
                return result
            except Exception as fallback_err:
                return {
                    "success": False,
                    "message": f"Primary: {primary_err}; Fallback: {fallback_err}",
                    "error": "llm_call_failed",
                }
        return {"success": False, "message": str(primary_err), "error": "llm_call_failed"}


async def _call_llm_api(
    prompt: str,
    model: str,
    system_prompt: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.7,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Raw API call to OpenAI-compatible endpoint."""
    from openai import AsyncOpenAI

    _api_key = api_key or settings.llm.api_key
    _base_url = base_url or settings.llm.base_url
    client = AsyncOpenAI(api_key=_api_key, base_url=_base_url)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=settings.llm.top_p,
        frequency_penalty=settings.llm.frequency_penalty,
        presence_penalty=settings.llm.presence_penalty,
    )
    return response.model_dump()


def _parse_response(response: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Parse LLM API response into standard format."""
    try:
        content = response["choices"][0]["message"]["content"]
        usage = response.get("usage", {})
        return {
            "success": True,
            "content": content,
            "model": model,
            "usage": usage,
            "message": "LLM call successful",
        }
    except (KeyError, IndexError) as e:
        return {"success": False, "message": f"Response parsing failed: {e}", "error": "parse_error"}


async def call_llm_vision(
    prompt: str,
    images: Optional[List[Union[str, bytes]]] = None,
    model: Optional[str] = None,
    system_prompt: str = "",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call multimodal/Vision LLM with text + images.

    Args:
        prompt: Text prompt
        images: List of image data — each item is either:
            - str: base64-encoded image data (without data: prefix)
            - bytes: raw image bytes (will be base64-encoded)
            - str starting with "http": URL to fetch
        model: Vision model name (default from settings.llm.vision_model or settings.llm.model)
        system_prompt: System prompt
        max_tokens: Max generation tokens
        temperature: Temperature
        api_key: API key
        base_url: API base URL

    Returns:
        Same format as call_llm: {success, content, model, usage}
    """
    vision_model = getattr(settings.llm, 'vision_model', None)
    model = model or vision_model or settings.llm.model
    max_tokens = max_tokens or settings.llm.max_tokens
    temperature = temperature or settings.llm.temperature
    api_key = api_key or settings.llm.api_key
    base_url = base_url or settings.llm.base_url

    if not prompt or not prompt.strip():
        return {"success": False, "message": "prompt cannot be empty", "error": "empty_prompt"}

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    content_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

    if images:
        for img in images:
            if isinstance(img, bytes):
                b64 = base64.b64encode(img).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            elif isinstance(img, str):
                if img.startswith(("http://", "https://")):
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img},
                    })
                elif img.startswith("data:"):
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img},
                    })
                else:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img}"},
                    })

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content_parts})

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=settings.llm.top_p,
        )
        return _parse_response(response.model_dump(), model)
    except Exception as e:
        logger.warning(f"Vision LLM call failed: {e}")
        return {"success": False, "message": str(e), "error": "vision_call_failed"}
