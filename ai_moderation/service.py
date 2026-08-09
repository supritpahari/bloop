"""AI Moderation service for fetching models and analyzing messages."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class AIModel:
    """Represents an AI model from a provider."""
    id: str
    name: str
    provider: str


class AIModerationService:
    """Service for fetching AI models and analyzing messages for moderation."""

    PROVIDERS = {
        "OpenRouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "name",
        },
        "Gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "models_endpoint": "/models",
            "auth_header": "x-goog-api-key",
            "auth_prefix": "",
            "model_id_field": "name",
            "model_name_field": "displayName",
            "filter": lambda m: "generateContent" in m.get("supportedGenerationMethods", []),
        },
        "OpenCode": {
            "base_url": "https://api.opencode.ai/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "name",
        },
        "OpenAI": {
            "base_url": "https://api.openai.com/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
        },
        "Anthropic": {
            "base_url": "https://api.anthropic.com/v1",
            "models_endpoint": "/models",
            "auth_header": "x-api-key",
            "auth_prefix": "",
            "model_id_field": "id",
            "model_name_field": "display_name",
        },
        "DeepSeek": {
            "base_url": "https://api.deepseek.com/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
        },
        "xAI": {
            "base_url": "https://api.x.ai/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
        },
    }

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_models(self, provider: str, api_key: str) -> list[AIModel]:
        """Fetch available models from the specified provider."""
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        config = self.PROVIDERS[provider]
        session = await self._get_session()
        url = f"{config['base_url']}{config['models_endpoint']}"

        headers = {}
        if config["auth_header"]:
            headers[config["auth_header"]] = f"{config['auth_prefix']}{api_key}"

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    raise ValueError("Invalid API key")
                if resp.status == 403:
                    raise ValueError("API key doesn't have permission to list models")
                if resp.status != 200:
                    text = await resp.text()
                    raise ValueError(f"API error ({resp.status}): {text}")

                data = await resp.json()
                models = []

                # Handle different response formats
                if provider == "Gemini":
                    items = data.get("models", [])
                elif provider == "OpenRouter":
                    items = data.get("data", [])
                elif provider == "OpenAI":
                    items = data.get("data", [])
                elif provider == "Anthropic":
                    items = data.get("data", [])
                else:
                    items = data.get("data", data.get("models", []))

                for item in items:
                    # Apply filter if provided
                    filter_fn = config.get("filter")
                    if filter_fn and not filter_fn(item):
                        continue

                    model_id = item.get(config["model_id_field"])
                    model_name = item.get(config["model_name_field"], model_id)

                    if model_id:
                        models.append(AIModel(
                            id=model_id,
                            name=model_name,
                            provider=provider
                        ))

                logger.info(f"Fetched {len(models)} models from {provider}")
                return models

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching models from {provider}: {e}")
            raise ValueError(f"Network error: {e}")
        except Exception as e:
            logger.error(f"Error fetching models from {provider}: {e}")
            raise

    async def moderate_message(
        self,
        provider: str,
        model_id: str,
        api_key: str,
        message_content: str,
        moderation_level: str,
        guild_context: str = ""
    ) -> dict:
        """Analyze a message using the specified AI model."""
        # This would call the appropriate provider's moderation/chat completion API
        # For now, return a mock response structure
        # TODO: Implement actual API calls per provider
        return {
            "action": "none",  # none, warn, timeout, kick, ban
            "reason": "",
            "confidence": 0.0,
            "categories": []
        }


# Moderation level configurations
MODERATION_LEVELS = {
    "strict": {
        "description": "Zero tolerance - immediate action on any violation",
        "thresholds": {
            "hate_speech": 0.3,
            "harassment": 0.3,
            "violence": 0.3,
            "sexual": 0.3,
            "spam": 0.4,
            "self_harm": 0.3,
            "illegal": 0.3,
        },
        "default_action": "timeout",
    },
    "moderate": {
        "description": "Balanced - warn first, escalate on repeat",
        "thresholds": {
            "hate_speech": 0.5,
            "harassment": 0.5,
            "violence": 0.4,
            "sexual": 0.5,
            "spam": 0.6,
            "self_harm": 0.4,
            "illegal": 0.4,
        },
        "default_action": "warn",
    },
    "lenient": {
        "description": "Relaxed - only act on severe violations",
        "thresholds": {
            "hate_speech": 0.7,
            "harassment": 0.7,
            "violence": 0.6,
            "sexual": 0.7,
            "spam": 0.8,
            "self_harm": 0.5,
            "illegal": 0.6,
        },
        "default_action": "warn",
    },
}

MODERATION_ACTIONS = ["none", "warn", "timeout", "kick", "ban"]