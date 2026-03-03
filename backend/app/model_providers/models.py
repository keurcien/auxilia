from enum import Enum

from pydantic import BaseModel
from sqlmodel import SQLModel


class ModelProviderType(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    anthropic = "anthropic"
    google = "google"
    ollama = "ollama"
    litellm = "litellm"


class ModelProviderRead(SQLModel):
    name: ModelProviderType


class ModelRead(BaseModel):
    name: str
    id: str
    chef: str
    chefSlug: str
    providers: list[ModelProviderType]
