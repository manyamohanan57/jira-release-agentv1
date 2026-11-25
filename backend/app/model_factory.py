from typing import Any

from app.config import Settings


SUPPORTED_PROVIDERS = {"groq", "gemini", "mistral"}


def validate_model_configuration(settings: Settings) -> None:
    provider = settings.model_provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise RuntimeError(
            f"Unsupported MODEL_PROVIDER '{provider}'. Choose one of: {supported}."
        )

    key_fields = {
        "groq": ("groq_api_key", "GROQ_API_KEY"),
        "gemini": ("google_api_key", "GOOGLE_API_KEY"),
        "mistral": ("mistral_api_key", "MISTRAL_API_KEY"),
    }
    key_field, environment_name = key_fields[provider]
    if not getattr(settings, key_field):
        raise RuntimeError(
            f"Model is not configured. Set {environment_name} for provider '{provider}'."
        )

    if not settings.model_name:
        raise RuntimeError("Set MODEL_NAME for the selected model provider.")


def build_chat_model(settings: Settings) -> Any:
    provider = settings.model_provider.strip().lower()

    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.model_name,
            api_key=settings.groq_api_key,
            temperature=0,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.model_name,
            google_api_key=settings.google_api_key,
            temperature=0,
        )

    from langchain_mistralai import ChatMistralAI

    return ChatMistralAI(
        model=settings.model_name,
        mistral_api_key=settings.mistral_api_key,
        temperature=0,
    )
