"""Service for fetching available AI models from providers."""

import httpx
from typing import Optional

from app.core.config import settings
from app.core.logging import logger


# Comprehensive list of Anthropic models (they don't have a public API for this)
ANTHROPIC_MODELS = [
    # Claude 3.5 family
    {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet (Oct 2024)"},
    {"id": "claude-3-5-sonnet-20240620", "name": "Claude 3.5 Sonnet (Jun 2024)"},
    {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
    # Claude 3 family
    {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus"},
    {"id": "claude-3-sonnet-20240229", "name": "Claude 3 Sonnet"},
    {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku"},
    # Claude 2 family (legacy)
    {"id": "claude-2.1", "name": "Claude 2.1"},
    {"id": "claude-2.0", "name": "Claude 2.0"},
    {"id": "claude-instant-1.2", "name": "Claude Instant 1.2"},
]

# OpenAI models we care about (chat/completion models only)
# We'll filter the API response to these prefixes
OPENAI_CHAT_MODEL_PREFIXES = [
    "gpt-4",
    "gpt-3.5",
    "o1",  # New reasoning models
    "o3",  # Future reasoning models
    "chatgpt",
]

# Fallback list if API is unavailable
OPENAI_FALLBACK_MODELS = [
    {"id": "gpt-4o", "name": "GPT-4o"},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
    {"id": "gpt-4-turbo-preview", "name": "GPT-4 Turbo Preview"},
    {"id": "gpt-4", "name": "GPT-4"},
    {"id": "gpt-4-0613", "name": "GPT-4 (0613)"},
    {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
    {"id": "gpt-3.5-turbo-0125", "name": "GPT-3.5 Turbo (0125)"},
    {"id": "gpt-3.5-turbo-1106", "name": "GPT-3.5 Turbo (1106)"},
    {"id": "o1-preview", "name": "O1 Preview"},
    {"id": "o1-mini", "name": "O1 Mini"},
]


def _format_model_name(model_id: str) -> str:
    """Convert model ID to a human-readable name."""
    # Common formatting rules
    name = model_id.replace("-", " ").replace("_", " ")

    # Specific formatting
    replacements = {
        "gpt 4o mini": "GPT-4o Mini",
        "gpt 4o": "GPT-4o",
        "gpt 4 turbo preview": "GPT-4 Turbo Preview",
        "gpt 4 turbo": "GPT-4 Turbo",
        "gpt 4": "GPT-4",
        "gpt 3.5 turbo": "GPT-3.5 Turbo",
        "o1 preview": "O1 Preview",
        "o1 mini": "O1 Mini",
        "o3 mini": "O3 Mini",
    }

    name_lower = name.lower()
    for pattern, replacement in replacements.items():
        if name_lower.startswith(pattern):
            # Keep any suffix (like date versions)
            suffix = name[len(pattern):].strip()
            if suffix:
                return f"{replacement} ({suffix})"
            return replacement

    # Default: Title case
    return name.title()


async def fetch_openai_models() -> list[dict]:
    """Fetch available models from OpenAI API."""
    api_key = settings.openai_api_key
    if not api_key:
        logger.warning("openai_api_key_missing", message="Using fallback model list")
        return OPENAI_FALLBACK_MODELS

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            data = response.json()

        models = []
        seen_ids = set()

        for model in data.get("data", []):
            model_id = model.get("id", "")

            # Skip if not a chat model we care about
            if not any(model_id.startswith(prefix) for prefix in OPENAI_CHAT_MODEL_PREFIXES):
                continue

            # Skip fine-tuned models
            if "ft:" in model_id or "ft-" in model_id:
                continue

            # Skip realtime/audio models (not for text chat)
            if "realtime" in model_id or "audio" in model_id:
                continue

            # Skip embedding models
            if "embedding" in model_id:
                continue

            # Skip duplicates
            if model_id in seen_ids:
                continue
            seen_ids.add(model_id)

            models.append({
                "id": model_id,
                "name": _format_model_name(model_id),
            })

        # Sort by model name (newest/best first typically)
        models.sort(key=lambda m: (
            0 if "gpt-4o" in m["id"] else
            1 if "o1" in m["id"] or "o3" in m["id"] else
            2 if "gpt-4" in m["id"] else
            3 if "gpt-3.5" in m["id"] else
            4,
            m["id"]
        ))

        if models:
            logger.info("openai_models_fetched", count=len(models))
            return models

        # If API returned no usable models, use fallback
        logger.warning("openai_no_models", message="API returned no chat models, using fallback")
        return OPENAI_FALLBACK_MODELS

    except Exception as e:
        logger.error("openai_models_fetch_error", error=str(e))
        return OPENAI_FALLBACK_MODELS


def get_anthropic_models() -> list[dict]:
    """Get the list of available Anthropic models."""
    return ANTHROPIC_MODELS.copy()


async def get_all_available_models() -> dict[str, list[dict]]:
    """Get all available models from all providers."""
    openai_models = await fetch_openai_models()
    anthropic_models = get_anthropic_models()

    return {
        "openai": openai_models,
        "anthropic": anthropic_models,
    }


def merge_with_settings(
    available_models: dict[str, list[dict]],
    stored_settings: Optional[dict],
) -> dict[str, list[dict]]:
    """
    Merge available models with stored enabled/disabled settings.

    New models default to enabled=True.
    Removed models are dropped.
    """
    if not stored_settings:
        # No settings yet - all models enabled by default
        result = {}
        for provider, models in available_models.items():
            result[provider] = [
                {"id": m["id"], "name": m["name"], "enabled": True}
                for m in models
            ]
        return result

    result = {}
    for provider, models in available_models.items():
        stored_provider = stored_settings.get(provider, [])
        stored_map = {m["id"]: m.get("enabled", True) for m in stored_provider}

        result[provider] = [
            {
                "id": m["id"],
                "name": m["name"],
                "enabled": stored_map.get(m["id"], True),  # Default to enabled for new models
            }
            for m in models
        ]

    return result
