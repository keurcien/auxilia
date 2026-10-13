"""Catalog prices in EUR per token, using Langfuse usage-type names."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field


Rate = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class TokenPrices(BaseModel):
    input: Rate
    input_cache_read: Rate
    output: Rate


class ModelPricing(BaseModel):
    currency: Literal["EUR"] = "EUR"
    prices: TokenPrices
