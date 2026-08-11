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
            "moderation_endpoint": "/chat/completions",
            "supports_moderation_api": False,
        },
        "Gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "models_endpoint": "/models",
            "auth_header": "x-goog-api-key",
            "auth_prefix": "",
            "model_id_field": "name",
            "model_name_field": "displayName",
            "filter": lambda m: "generateContent" in m.get("supportedGenerationMethods", []),
            "moderation_endpoint": "/models/{model}:generateContent",
            "supports_moderation_api": False,
        },
        "OpenAI": {
            "base_url": "https://api.openai.com/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
            "moderation_endpoint": "/moderations",
            "supports_moderation_api": True,
        },
        "Anthropic": {
            "base_url": "https://api.anthropic.com/v1",
            "models_endpoint": "/models",
            "auth_header": "x-api-key",
            "auth_prefix": "",
            "model_id_field": "id",
            "model_name_field": "display_name",
            "moderation_endpoint": "/messages",
            "supports_moderation_api": False,
            "fallback_models": [
                {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
                {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
                {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus"},
                {"id": "claude-3-sonnet-20240229", "name": "Claude 3 Sonnet"},
                {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku"},
            ]
        },
        "DeepSeek": {
            "base_url": "https://api.deepseek.com/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
            "moderation_endpoint": "/chat/completions",
            "supports_moderation_api": False,
            "fallback_models": [
                {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)"},
                {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)"},
            ]
        },
        "xAI": {
            "base_url": "https://api.x.ai/v1",
            "models_endpoint": "/models",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
            "moderation_endpoint": "/chat/completions",
            "supports_moderation_api": False,
            "fallback_models": [
                {"id": "grok-beta", "name": "Grok Beta"},
                {"id": "grok-2", "name": "Grok 2"},
                {"id": "grok-2-mini", "name": "Grok 2 Mini"},
            ]
        }
    }

    # OpenAI Moderation API categories mapping
    MODERATION_CATEGORIES = [
        "hate", "hate/threatening", "harassment", "harassment/threatening",
        "self-harm", "self-harm/intent", "self-harm/instructions",
        "sexual", "sexual/minors", "violence", "violence/graphic"
    ]

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
                text = await resp.text()
                if resp.status != 200:
                    # Try fallback models for known providers
                    if "fallback_models" in config and resp.status == 404:
                        logger.warning(f"Models endpoint 404 for {provider}, using fallback models")
                        return self._get_fallback_models(config, provider)
                    raise ValueError(f"API error ({resp.status}): {text}")

                # Handle non-JSON responses (e.g., text/plain)
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    # Try fallback models
                    if "fallback_models" in config:
                        logger.warning(f"Invalid JSON from {provider}, using fallback models")
                        return self._get_fallback_models(config, provider)
                    raise ValueError(f"Invalid JSON response: {text[:200]}")

                models = []

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
            # Try fallback models on network error
            if "fallback_models" in config:
                logger.warning(f"Network error for {provider}, using fallback models")
                return self._get_fallback_models(config, provider)
            raise ValueError(f"Network error: {e}")
        except Exception as e:
            logger.error(f"Error fetching models from {provider}: {e}")
            # Try fallback models on any error
            if "fallback_models" in config:
                logger.warning(f"Error for {provider}, using fallback models")
                return self._get_fallback_models(config, provider)
            raise

    def _get_fallback_models(self, config: dict, provider: str) -> list[AIModel]:
        """Return fallback models for providers without working models endpoint."""
        models = []
        for fm in config.get("fallback_models", []):
            models.append(AIModel(
                id=fm["id"],
                name=fm["name"],
                provider=provider
            ))
        logger.info(f"Using {len(models)} fallback models for {provider}")
        return models

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
        try:
            if provider == "OpenAI" and self.PROVIDERS[provider]["supports_moderation_api"]:
                return await self._moderate_openai(model_id, api_key, message_content, moderation_level)
            elif provider == "Anthropic":
                return await self._moderate_anthropic(model_id, api_key, message_content, moderation_level, guild_context)
            elif provider == "Gemini":
                return await self._moderate_gemini(model_id, api_key, message_content, moderation_level, guild_context)
            else:
                # Use generic OpenAI-compatible chat completions for OpenRouter, DeepSeek, xAI
                return await self._moderate_chat_completion(provider, model_id, api_key, message_content, moderation_level, guild_context)
        except Exception as e:
            logger.error(f"Moderation error for {provider}/{model_id}: {e}")
            return {
                "action": "none",
                "reason": f"Moderation error: {str(e)[:100]}",
                "confidence": 0.0,
                "categories": []
            }

    async def _moderate_openai(self, model_id: str, api_key: str, message_content: str, moderation_level: str) -> dict:
        """Use OpenAI's native Moderation API (free, purpose-built)."""
        session = await self._get_session()
        url = f"{self.PROVIDERS['OpenAI']['base_url']}/moderations"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "input": message_content,
            "model": model_id if model_id in ["omni-moderation-latest", "text-moderation-latest", "text-moderation-stable"] else "omni-moderation-latest"
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"OpenAI Moderation API error ({resp.status}): {text}")

            data = await resp.json()
            result = data["results"][0]
            flagged = result["flagged"]
            categories = result["categories"]
            scores = result["category_scores"]

            if not flagged:
                return {"action": "none", "reason": "", "confidence": 0.0, "categories": []}

            # Map categories to our action system using thresholds
            return self._evaluate_moderation_result(categories, scores, moderation_level)

    async def _moderate_anthropic(self, model_id: str, api_key: str, message_content: str, moderation_level: str, guild_context: str) -> dict:
        """Use Anthropic Claude for content moderation."""
        session = await self._get_session()
        url = f"{self.PROVIDERS['Anthropic']['base_url']}/messages"

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        system_prompt = self._build_moderation_prompt(moderation_level)

        payload = {
            "model": model_id,
            "max_tokens": 500,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": f"Analyze this message for moderation violations:\n\n{message_content}"}
            ],
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"Anthropic API error ({resp.status}): {text}")

            data = await resp.json()
            response_text = data["content"][0]["text"]
            return self._parse_llm_response(response_text, moderation_level)

    async def _moderate_gemini(self, model_id: str, api_key: str, message_content: str, moderation_level: str, guild_context: str) -> dict:
        """Use Google Gemini for content moderation."""
        session = await self._get_session()
        # Use the model name from model_id (e.g., "models/gemini-1.5-pro")
        model_name = model_id.replace("models/", "")
        url = f"{self.PROVIDERS['Gemini']['base_url']}/models/{model_name}:generateContent"

        headers = {
            "Content-Type": "application/json",
        }

        params = {"key": api_key}

        system_prompt = self._build_moderation_prompt(moderation_level)

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\nAnalyze this message:\n{message_content}"}]}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 500,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        }

        async with session.post(url, headers=headers, params=params, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"Gemini API error ({resp.status}): {text}")

            data = await resp.json()
            response_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return self._parse_llm_response(response_text, moderation_level)

    async def _moderate_chat_completion(self, provider: str, model_id: str, api_key: str, message_content: str, moderation_level: str, guild_context: str) -> dict:
        """Use OpenAI-compatible chat completions for OpenRouter, DeepSeek, xAI."""
        config = self.PROVIDERS[provider]
        session = await self._get_session()
        url = f"{config['base_url']}{config['moderation_endpoint']}"

        headers = {
            "Content-Type": "application/json",
        }
        if config["auth_header"]:
            headers[config["auth_header"]] = f"{config['auth_prefix']}{api_key}"

        system_prompt = self._build_moderation_prompt(moderation_level)

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this message for moderation violations:\n\n{message_content}"}
            ],
            "temperature": 0.1,
            "max_tokens": 500,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"{provider} API error ({resp.status}): {text}")

            data = await resp.json()
            response_text = data["choices"][0]["message"]["content"]
            return self._parse_llm_response(response_text, moderation_level)

    def _build_moderation_prompt(self, moderation_level: str) -> str:
        """Build the system prompt for LLM-based moderation."""
        level_config = MODERATION_LEVELS.get(moderation_level, MODERATION_LEVELS["moderate"])
        thresholds = level_config["thresholds"]

        return f"""You are an AI content moderator. Analyze the given message for policy violations.

MODERATION LEVEL: {moderation_level.upper()} - {level_config['description']}

THRESHOLDS (score >= threshold = violation):
- Hate Speech: {thresholds['hate_speech']}
- Harassment: {thresholds['harassment']}
- Violence: {thresholds['violence']}
- Sexual Content: {thresholds['sexual']}
- Spam: {thresholds['spam']}
- Self-Harm: {thresholds['self_harm']}
- Illegal Activity: {thresholds['illegal']}

DEFAULT ACTION: {level_config['default_action']}

RESPOND WITH VALID JSON ONLY:
{{
  "action": "none|warn|timeout|kick|ban",
  "reason": "Brief explanation of violation",
  "confidence": 0.0-1.0,
  "categories": ["category1", "category2"]
}}

Categories: hate_speech, harassment, violence, sexual, spam, self_harm, illegal
Actions escalate: none -> warn -> timeout -> kick -> ban
Only return the JSON object, no extra text."""

    def _evaluate_moderation_result(self, categories: dict, scores: dict, moderation_level: str) -> dict:
        """Evaluate OpenAI Moderation API result against thresholds."""
        level_config = MODERATION_LEVELS.get(moderation_level, MODERATION_LEVELS["moderate"])
        thresholds = level_config["thresholds"]

        violations = []
        max_score = 0.0

        # Map OpenAI categories to our categories
        category_map = {
            "hate": "hate_speech",
            "hate/threatening": "hate_speech",
            "harassment": "harassment",
            "harassment/threatening": "harassment",
            "violence": "violence",
            "violence/graphic": "violence",
            "sexual": "sexual",
            "sexual/minors": "sexual",
            "self-harm": "self_harm",
            "self-harm/intent": "self_harm",
            "self-harm/instructions": "self_harm",
        }

        for cat, flagged in categories.items():
            if not flagged:
                continue
            mapped = category_map.get(cat, cat)
            score = scores.get(cat, 0.0)
            threshold = thresholds.get(mapped, 0.5)
            if score >= threshold:
                violations.append(mapped)
                max_score = max(max_score, score)

        if not violations:
            return {"action": "none", "reason": "", "confidence": 0.0, "categories": []}

        # Determine action based on severity and level
        action = self._determine_action(violations, max_score, moderation_level)
        reason = f"Violations: {', '.join(violations)}"

        return {
            "action": action,
            "reason": reason,
            "confidence": max_score,
            "categories": violations
        }

    def _parse_llm_response(self, response_text: str, moderation_level: str) -> dict:
        """Parse JSON response from LLM moderation."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)

            action = result.get("action", "none")
            if action not in MODERATION_ACTIONS:
                action = "none"

            return {
                "action": action,
                "reason": result.get("reason", "AI-detected violation"),
                "confidence": float(result.get("confidence", 0.5)),
                "categories": result.get("categories", [])
            }
        except Exception as e:
            logger.error(f"Failed to parse LLM moderation response: {e}")
            return {"action": "none", "reason": "Parse error", "confidence": 0.0, "categories": []}

    def _determine_action(self, violations: list, max_score: float, moderation_level: str) -> str:
        """Determine action based on violations and severity."""
        level_config = MODERATION_LEVELS.get(moderation_level, MODERATION_LEVELS["moderate"])
        default_action = level_config["default_action"]

        # Severe categories always escalate
        severe = {"hate_speech", "sexual", "violence", "illegal", "self_harm"}
        has_severe = any(v in severe for v in violations)

        action_order = ["none", "warn", "timeout", "kick", "ban"]
        default_idx = action_order.index(default_action)

        if has_severe and max_score > 0.8:
            return action_order[min(default_idx + 2, 4)]  # Escalate 2 levels
        elif has_severe:
            return action_order[min(default_idx + 1, 4)]  # Escalate 1 level
        elif max_score > 0.8:
            return action_order[min(default_idx + 1, 4)]
        else:
            return default_action


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