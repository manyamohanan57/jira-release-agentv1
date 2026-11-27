from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = BACKEND_DIR.parent / ".env"
BACKEND_ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    jira_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("JIRA_BASE_URL", "JIRA_URL"),
    )
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = ""
    dataset_label: str = "tyn-release-assessment-v2"
    model_provider: str = Field(
        default="groq",
        validation_alias=AliasChoices("MODEL_PROVIDER", "LLM_PROVIDER"),
    )
    model_name: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=AliasChoices(
            "MODEL_NAME",
            "GROQ_MODEL",
            "GEMINI_MODEL",
            "MISTRAL_MODEL",
        ),
    )
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GROQ_API_KEY"),
    )
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    mistral_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MISTRAL_API_KEY"),
    )

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE, BACKEND_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
