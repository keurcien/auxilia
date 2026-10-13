"""Catalog pricing, in USD per million tokens (never a persisted charge)."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field


Rate = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class ModelPricing(BaseModel):
    currency: Literal["USD"] = "USD"
    input_cost: Rate
    cached_input_cost: Rate
    output_cost: Rate
