"""AI Chat service for fetching models and generating responses."""

import json
import logging
from dataclasses import dataclass
from typing import Optional, List

import aiohttp

logger = logging.getLogger(__name__)


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
        "OpenCode": {
            "base_url": "https://api.opencode.ai/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "name",
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
        },
        "DeepSeek": {
            "base_url": "https://api.deepseek.com/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
        },
        "xAI": {
            "base_url": "https://api.x.ai/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "model_id_field": "id",
            "model_name_field": "id",
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

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    raise ValueError("Invalid API key")
                if resp.status == 403:
                    raise ValueError("API key doesn't have permission to list models")
                text = await resp.text()
                if resp.status != 200:
                    raise ValueError(f"API error ({resp.status}): {text}")

                # Handle non-JSON responses (e.g., text/plain)
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
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
            raise ValueError(f"Network error: {e}")
        except Exception as e:
            logger.error(f"Error fetching models from {provider}: {e}")
            raise

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
            if provider == "OpenAI" or provider in ["OpenRouter", "DeepSeek", "xAI", "OpenCode"]:
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
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"{provider} API error ({resp.status}): {text}")

            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()

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
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"Anthropic API error ({resp.status}): {text}")

            data = await resp.json()
            return data["content"][0]["text"].strip()

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
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"Gemini API error ({resp.status}): {text}")

            data = await resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()