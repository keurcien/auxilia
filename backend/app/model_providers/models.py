from enum import Enum


class ModelProviderType(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    anthropic = "anthropic"
    google = "google"
    ollama = "ollama"
