from pydantic import BaseModel
from sqlmodel import SQLModel

from app.model_providers.models import ModelProviderType


class ModelProviderResponse(SQLModel):
    name: ModelProviderType


class ModelResponse(BaseModel):
    name: str
    id: str
    chef: str
    chefSlug: str
    providers: list[ModelProviderType]
