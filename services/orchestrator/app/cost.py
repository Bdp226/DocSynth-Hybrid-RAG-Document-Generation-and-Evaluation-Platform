"""Cost tracking and billing utilities for document synthesis operations.

Tracks token counts and estimated costs per request, enabling operators to
understand per-document economics without modifying generation logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CostBreakdown:
    """Cost estimate for a single request."""

    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def total_cost_usd(self) -> float:
        return round(self.input_cost_usd + self.output_cost_usd, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost_usd": round(self.input_cost_usd, 6),
            "output_cost_usd": round(self.output_cost_usd, 6),
            "total_cost_usd": self.total_cost_usd,
        }


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    input_cost_per_1k: float,
    output_cost_per_1k: float,
) -> CostBreakdown:
    """Calculate cost from token counts and per-1k rates.
    
    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        input_cost_per_1k: Cost per 1000 input tokens in USD
        output_cost_per_1k: Cost per 1000 output tokens in USD
        
    Returns:
        CostBreakdown with itemized costs
    """
    input_cost = (input_tokens / 1000) * input_cost_per_1k
    output_cost = (output_tokens / 1000) * output_cost_per_1k

    return CostBreakdown(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
    )
