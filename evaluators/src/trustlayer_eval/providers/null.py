"""The default provider: refuses every call (ADR-020 §2).

An unconfigured install produces deterministic results only and never makes an
unexpected network call. Opting in to a model is a deliberate act, so a
misconfigured deployment degrades to deterministic-only rather than to a
surprise egress.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from ..models import Message, ProviderResponse, Residency
from .base import ProviderRefusal

REFUSAL = (
    "No evaluator provider is configured, so no model was called. "
    "Set TRUSTLAYER_EVAL_PROVIDER (ollama | agentcenter | openai_compat | "
    "anthropic) to enable model-assisted evaluation. Deterministic results "
    "are unaffected."
)


class NullProvider:
    """Configured absence, not a failure."""

    name = "null"
    residency = Residency.LOCAL
    """LOCAL because nothing leaves the machine — there is no call to make."""

    def __init__(self, *, model: str = "none") -> None:
        self.model = model

    def complete(
        self,
        messages: Sequence[Message],
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        raise ProviderRefusal(REFUSAL)

    def available(self) -> bool:
        """True: the provider is working exactly as configured.

        Reporting False would make callers fall back to a *real* provider,
        which is the opposite of what an unconfigured install should do.
        """
        return True
