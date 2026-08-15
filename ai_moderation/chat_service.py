"""AI Chat service for fetching models and generating responses."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional, List

import aiohttp

logger = logging.getLogger(__name__)


class AuthError(ValueError):
    """Raised when the provider rejects the API key. Never swallowed by fallbacks."""


def _short_error(text: str) -> str:
    """Pull the human-readable message out of a provider error body."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return (text or "")[:300]
    err = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(err, dict):
        msg = err.get("message") or err.get("detail") or err.get("code")
        if msg:
            return str(msg)[:300]
    return (text or "")[:300]


@dataclass
class AIModel:
    """Represents an AI model from a provider."""
    id: str
    name: str
    provider: str


class AIChatService:
    """Service for fetching AI models and generating chat responses."""

    PROVIDERS = {
        "OpenRouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "name",
        },
        "Gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "models_endpoint": "/models",
            "chat_endpoint": "/models/{model}:generateContent",
            "auth_header": "x-goog-api-key",
            "auth_prefix": "",
            "model_id_field": "name",
            "model_name_field": "displayName",
            "filter": lambda m: "generateContent" in m.get("supportedGenerationMethods", []),
        },
        "OpenAI": {
            "base_url": "https://api.openai.com/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
        },
        "Anthropic": {
            "base_url": "https://api.anthropic.com/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/messages",
            "auth_header": "x-api-key",
            "auth_prefix": "",
            "model_id_field": "id",
            "model_name_field": "display_name",
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
            "chat_endpoint": "/chat/completions",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
            "fallback_models": [
                {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)"},
                {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)"},
            ]
        },
        "xAI": {
            "base_url": "https://api.x.ai/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
            "fallback_models": [
                {"id": "grok-beta", "name": "Grok Beta"},
                {"id": "grok-2", "name": "Grok 2"},
                {"id": "grok-2-mini", "name": "Grok 2 Mini"},
            ]
        },
    }

    # Predefined tone presets
    TONE_PRESETS = {
        "casual": "You are a friendly, casual chat buddy. Talk like a real person - use contractions, slang occasionally, keep it light and conversational. Don't be robotic or overly formal. Match the user's energy.",
        "friendly": "You are a warm, helpful friend. Be supportive, use emojis naturally, show genuine interest. Keep responses concise but caring.",
        "witty": "You are clever and playful. Use humor, wordplay, light teasing. Keep it fun but never mean. Match the user's wit level.",
        "professional": "You are a knowledgeable assistant. Clear, concise, helpful. Professional but approachable. No slang.",
        "roleplay": "You are an immersive character. Stay in character, use *actions* for narration, \"dialogue\" for speech. Rich sensory detail.",
        "custom": "Custom tone set by server owner."
    }

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_models(self, provider: str, api_key: str) -> List[AIModel]:
        """Fetch available models from the specified provider."""
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        config = self.PROVIDERS[provider]
        session = await self._get_session()
        url = f"{config['base_url']}{config['models_endpoint']}"

        headers = {}
        if config["auth_header"]:
            headers[config["auth_header"]] = f"{config['auth_prefix']}{api_key}"

        # Gemini pages its model list (default 50) - ask for the full set.
        params = {"pageSize": 200} if provider == "Gemini" else None

        try:
            async with session.get(url, headers=headers, params=params) as resp:
                # Auth failures must always surface - never mask them with the
                # fallback list, or the user "successfully" configures a dead key
                # and only finds out when the bot silently fails to reply.
                if resp.status == 401:
                    raise AuthError("Invalid API key")
                if resp.status == 403:
                    raise AuthError("API key doesn't have permission to list models")
                text = await resp.text()
                if resp.status != 200:
                    # Try fallback models for known providers
                    if "fallback_models" in config and resp.status in (404, 405):
                        logger.warning(f"Models endpoint {resp.status} for {provider}, using fallback models")
                        return self._get_fallback_models(config, provider)
                    raise ValueError(f"API error ({resp.status}): {text[:300]}")

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

        except AuthError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Network error fetching models from {provider}: {e}")
            # Try fallback models on network error
            if "fallback_models" in config:
                logger.warning(f"Network error for {provider}, using fallback models")
                return self._get_fallback_models(config, provider)
            raise ValueError(f"Network error: {e}")
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching models from {provider}: {e}")
            # Try fallback models on any unexpected error
            if "fallback_models" in config:
                logger.warning(f"Error for {provider}, using fallback models")
                return self._get_fallback_models(config, provider)
            raise

    def _get_fallback_models(self, config: dict, provider: str) -> List[AIModel]:
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

    async def generate_response(
        self,
        provider: str,
        model_id: str,
        api_key: str,
        user_message: str,
        system_prompt: str,
        conversation_history: List[dict] = None
    ) -> str:
        """Generate a chat response using the specified AI model."""
        try:
            if provider == "OpenAI" or provider in ["OpenRouter", "DeepSeek", "xAI"]:
                return await self._chat_openai_compatible(provider, model_id, api_key, user_message, system_prompt, conversation_history)
            elif provider == "Anthropic":
                return await self._chat_anthropic(model_id, api_key, user_message, system_prompt, conversation_history)
            elif provider == "Gemini":
                return await self._chat_gemini(model_id, api_key, user_message, system_prompt, conversation_history)
            else:
                raise ValueError(f"Unsupported provider for chat: {provider}")
        except Exception as e:
            logger.error(f"Chat generation error for {provider}/{model_id}: {e}")
            raise

    async def _chat_openai_compatible(
        self,
        provider: str,
        model_id: str,
        api_key: str,
        user_message: str,
        system_prompt: str,
        conversation_history: List[dict] = None
    ) -> str:
        config = self.PROVIDERS[provider]
        session = await self._get_session()
        url = f"{config['base_url']}{config['chat_endpoint']}"

        headers = {
            "Content-Type": "application/json",
        }
        if config["auth_header"]:
            headers[config["auth_header"]] = f"{config['auth_prefix']}{api_key}"

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history[-10:])  # Keep last 10 messages
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 500,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise ValueError(f"{provider} API error ({resp.status}): {_short_error(text)}")

            try:
                data = json.loads(text)
                return (data["choices"][0]["message"]["content"] or "").strip()
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                raise ValueError(f"Unexpected {provider} response: {text[:300]}")

    async def _chat_anthropic(
        self,
        model_id: str,
        api_key: str,
        user_message: str,
        system_prompt: str,
        conversation_history: List[dict] = None
    ) -> str:
        session = await self._get_session()
        url = f"{self.PROVIDERS['Anthropic']['base_url']}/messages"

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        messages = []
        if conversation_history:
            for msg in conversation_history[-10:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": model_id,
            "max_tokens": 500,
            "system": system_prompt,
            "messages": messages,
            "temperature": 0.8,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise ValueError(f"Anthropic API error ({resp.status}): {_short_error(text)}")

            try:
                data = json.loads(text)
                parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
                return "".join(parts).strip()
            except (json.JSONDecodeError, AttributeError, TypeError):
                raise ValueError(f"Unexpected Anthropic response: {text[:300]}")

    async def _chat_gemini(
        self,
        model_id: str,
        api_key: str,
        user_message: str,
        system_prompt: str,
        conversation_history: List[dict] = None
    ) -> str:
        session = await self._get_session()
        model_name = model_id.replace("models/", "")
        url = f"{self.PROVIDERS['Gemini']['base_url']}/models/{model_name}:generateContent"

        headers = {"Content-Type": "application/json"}
        params = {"key": api_key}

        contents = []
        if conversation_history:
            for msg in conversation_history[-10:]:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "temperature": 0.8,
                "maxOutputTokens": 500,
            },
        }

        async with session.post(url, headers=headers, params=params, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise ValueError(f"Gemini API error ({resp.status}): {_short_error(text)}")

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError(f"Unexpected Gemini response: {text[:300]}")

            candidates = data.get("candidates") or []
            if not candidates:
                blocked = (data.get("promptFeedback") or {}).get("blockReason")
                raise ValueError(f"Gemini returned no candidates{f' (blocked: {blocked})' if blocked else ''}")

            candidate = candidates[0]
            parts = (candidate.get("content") or {}).get("parts") or []
            out = "".join(p.get("text", "") for p in parts).strip()
            if not out:
                reason = candidate.get("finishReason")
                if reason == "MAX_TOKENS":
                    raise ValueError("Gemini hit the output token limit before producing text")
                raise ValueError(f"Gemini returned an empty response (finishReason={reason})")
            return out