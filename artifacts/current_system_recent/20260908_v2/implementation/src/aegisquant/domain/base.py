"""Shared immutable and strict domain-model configuration."""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base for immutable contracts that reject undeclared or coerced fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        validate_return=True,
    )
