from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "InsightFlow API"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_url: str

    # Local LLM configuration
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b-instruct"

    # Authentication configuration
    jwt_secret_key: str = (
        "development-only-change-this-secret-before-deployment"
    )
    jwt_access_token_expire_minutes: int = 30

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if self.environment.strip().lower() in {"production", "prod"}:
            insecure_default = (
                "development-only-change-this-secret-before-deployment"
            )

            if (
                self.jwt_secret_key == insecure_default
                or len(self.jwt_secret_key.strip()) < 32
            ):
                raise ValueError(
                    "Production requires a secure JWT_SECRET_KEY "
                    "of at least 32 characters."
                )

        return self


settings = Settings()