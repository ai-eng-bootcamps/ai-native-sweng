"""Provider-neutral model adapter interface (spec 5.3, 7.1).

Every model provider and execution mode (live, scripted, replay) is accessed
through this interface. It covers the adapter responsibilities from spec 7.1:
provider selection happens in the factory; structured outputs, tool-call
representation, usage reporting, and timeouts are part of the request/response
model (types.py); cost calculation and capability metadata live here; error
normalization and retryable classification live in errors.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from anse_harness.models.types import (
    CostTable,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    Usage,
)


class ModelAdapter(ABC):
    """Common interface for model execution."""

    def __init__(self, cost_table: CostTable | None = None) -> None:
        self._cost_table = cost_table if cost_table is not None else CostTable()

    @abstractmethod
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Execute one non-streaming model call and return the normalized response."""

    @abstractmethod
    def capabilities(self) -> ModelCapabilities:
        """Return capability metadata for the configured model."""

    def calculate_cost(self, usage: Usage) -> float:
        """Cost calculation hook: USD cost of one call from the configured cost table."""
        return self._cost_table.cost_usd(usage)
