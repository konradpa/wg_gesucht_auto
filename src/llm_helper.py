"""
LLM helper for personalizing WG-Gesucht messages.

Supports Gemini, Anthropic, and OpenAI-compatible APIs (OpenAI, OpenRouter,
Groq, Together, local gateways such as LM Studio/vLLM).
"""

from typing import Any, Dict, Optional


OPENAI_COMPATIBLE_PROVIDER_ALIASES = {
    "openai_compatible": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "openrouter": "openai_compatible",
    "groq": "openai_compatible",
    "together": "openai_compatible",
}

OPENAI_COMPATIBLE_DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
}

DEFAULT_MODELS = {
    "gemini": "gemini-1.5-flash",
    "anthropic": "claude-3-5-haiku-latest",
    "openai": "gpt-4o-mini",
    "openrouter": "openai/gpt-4o-mini",
    "groq": "llama-3.1-8b-instant",
    "together": "meta-llama/Llama-3.1-8B-Instruct-Turbo",
    "openai_compatible": "gpt-4o-mini",
}


def _normalize_text(value: Optional[object]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_llm_config(config: dict, require_enabled: bool = True) -> Optional[Dict[str, str]]:
    """
    Resolve LLM settings from config.

    Prefers the new `llm` block and falls back to legacy `gemini` for backward
    compatibility.
    """
    llm = config.get("llm")
    if isinstance(llm, dict):
        enabled = bool(llm.get("enabled", False))
        source = _normalize_text(llm.get("provider") or "gemini").lower()
        provider = OPENAI_COMPATIBLE_PROVIDER_ALIASES.get(source, source)
        api_key = _normalize_text(llm.get("api_key"))
        model = _normalize_text(llm.get("model")) or DEFAULT_MODELS.get(source) or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        base_url = _normalize_text(llm.get("base_url")) or OPENAI_COMPATIBLE_DEFAULT_BASE_URLS.get(source, "")

        if require_enabled and not enabled:
            return None
        if not api_key:
            return None

        return {
            "enabled": "true" if enabled else "false",
            "provider": provider,
            "source": source,
            "api_key": api_key,
            "model": model,
            "base_url": base_url,
        }

    # Legacy config support
    gemini = config.get("gemini")
    if isinstance(gemini, dict):
        enabled = bool(gemini.get("enabled", False))
        api_key = _normalize_text(gemini.get("api_key"))
        model = _normalize_text(gemini.get("model")) or DEFAULT_MODELS["gemini"]

        if require_enabled and not enabled:
            return None
        if not api_key:
            return None

        return {
            "enabled": "true" if enabled else "false",
            "provider": "gemini",
            "source": "gemini",
            "api_key": api_key,
            "model": model,
            "base_url": "",
        }

    return None


class LLMHelper:
    """Helper class for AI-based message personalization."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
        source: str = "",
    ):
        self.provider = provider
        self.source = source or provider
        self.model = model
        self.base_url = base_url
        self._client: Any = None

        if provider == "gemini":
            from google import genai

            self._client = genai.Client(api_key=api_key)
        elif provider == "anthropic":
            from anthropic import Anthropic

            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = Anthropic(**kwargs)
        elif provider in ("openai", "openai_compatible"):
            from openai import OpenAI

            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = OpenAI(**kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        print(f"✓ AI initialized: {self.display_name} ({model})")

    @property
    def display_name(self) -> str:
        labels = {
            "gemini": "Gemini",
            "anthropic": "Anthropic",
            "openai": "OpenAI",
            "openrouter": "OpenRouter",
            "groq": "Groq",
            "together": "Together",
            "openai_compatible": "OpenAI-compatible API",
        }
        return labels.get(self.source, labels.get(self.provider, self.source or self.provider))

    @classmethod
    def from_config(cls, config: dict, require_enabled: bool = True) -> Optional["LLMHelper"]:
        resolved = resolve_llm_config(config, require_enabled=require_enabled)
        if not resolved:
            return None
        return cls(
            provider=resolved["provider"],
            api_key=resolved["api_key"],
            model=resolved["model"],
            base_url=resolved.get("base_url", ""),
            source=resolved.get("source", resolved["provider"]),
        )

    def _build_prompt(self, base_message: str, listing_details: dict, recipient_name: str) -> str:
        """Create the personalization prompt shared by all providers."""
        title = listing_details.get("title", "")
        description = listing_details.get("description", "")
        district = listing_details.get("district", "")
        rent = listing_details.get("rent", "")
        gesucht = listing_details.get("gesucht_wird", "")
        availability_from = listing_details.get("availability_from", "")
        availability_to = listing_details.get("availability_to", "")
        advertiser_name = listing_details.get("advertiser_name", "")
        contact_email = listing_details.get("contact_email", "")
        contact_phone = listing_details.get("contact_phone", "")

        return f"""Du bist ein freundlicher WG-Bewerber. Personalisiere die folgende Nachricht basierend auf der WG-Anzeige.

WICHTIGE REGELN:
1. Behalte den Grundton und die Struktur der Originalnachricht bei
2. Füge 1-2 spezifische Bezüge zur Anzeige hinzu (z.B. Lage, etwas Besonderes aus der Beschreibung)
3. Bleib authentisch und nicht zu übertrieben freundlich
4. Die Nachricht sollte etwa gleich lang bleiben
5. Schreibe auf Deutsch
6. Ersetze {{name}} mit dem echten Namen falls vorhanden.
7. Verwende Kommas statt Gedankenstrichen (kein " - ").
8. Kontakt (Email/Telefon) nur falls in der Beschreibung explizit gefragt.

ORIGINALNACHRICHT:
{base_message}

WG-ANZEIGE:
Titel: {title}
Bezirk: {district}
Miete: {rent}€
Frei ab: {availability_from}
Frei bis: {availability_to}
Gesucht wird: {gesucht[:500]}
Anbieter: {advertiser_name}
Kontakt (nur falls noetig): {contact_email} {contact_phone}
Beschreibung: {description[:500]}

EMPFÄNGER: {recipient_name}

Gib NUR die personalisierte Nachricht zurück, keine Erklärungen."""

    def _generate_text(self, prompt: str) -> str:
        if self.provider == "gemini":
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            return (getattr(response, "text", "") or "").strip()

        if self.provider == "anthropic":
            response = self._client.messages.create(
                model=self.model,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            blocks = getattr(response, "content", None) or []
            parts = []
            for block in blocks:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    continue
                if getattr(block, "type", None) == "text":
                    parts.append(getattr(block, "text", ""))
            return "".join(parts).strip()

        if self.provider in ("openai", "openai_compatible"):
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif hasattr(item, "type") and getattr(item, "type", None) == "text":
                        parts.append(getattr(item, "text", ""))
                return "".join(parts).strip()
            return ""

        raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def personalize_message(
        self,
        base_message: str,
        listing_details: dict,
        recipient_name: str,
    ) -> Optional[str]:
        """Personalize a message based on listing details."""
        prompt = self._build_prompt(base_message, listing_details, recipient_name)
        try:
            personalized = self._generate_text(prompt)
            if len(personalized) < 50:
                print(f"⚠ {self.display_name} response too short, using template")
                return None
            return personalized
        except Exception as e:
            print(f"⚠ {self.display_name} error: {e}")
            return None

    def test_connection(self) -> bool:
        """Verify the configured API credentials and model can respond."""
        try:
            response = self._generate_text("Antworte nur mit: OK")
            return bool(response)
        except Exception as e:
            print(f"{self.display_name} test failed: {e}")
            return False
