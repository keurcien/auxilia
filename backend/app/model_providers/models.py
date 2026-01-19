from enum import Enum
from sqlmodel import SQLModel


class ModelProviderType(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    anthropic = "anthropic"
    google = "google"
    ollama = "ollama"


class ModelProviderRead(SQLModel):
    name: ModelProviderType