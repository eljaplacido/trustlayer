"""Egress policy (ADR-020 §5).

Sending a system's traces to a third-country endpoint in order to assess its
compliance posture is self-defeating (design principle P7). This module
decides whether a run may leave the machine at all, before any provider is
called.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .models import EgressDecision, Residency

#: Data classes that make third-country egress a refusal rather than a choice.
RESTRICTED_DATA_CLASSES = frozenset({"personal_data", "special_category_data"})


class EgressRefused(RuntimeError):
    """The run was refused by policy. Carries the decision for the record."""

    def __init__(self, decision: EgressDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class EgressPolicy:
    """Resolves `data_classes` × provider `residency` into a decision."""

    def __init__(self, system: dict[str, Any] | None = None) -> None:
        self._system = system or {}

    def data_classes(self) -> tuple[str, ...]:
        raw = self._system.get("data_classes")
        if isinstance(raw, list):
            return tuple(str(entry) for entry in raw)
        return ()

    def decide(self, *, provider: str, residency: Residency) -> EgressDecision:
        classes = self.data_classes()
        restricted = tuple(sorted(set(classes) & RESTRICTED_DATA_CLASSES))

        # UNKNOWN is treated as THIRD_COUNTRY: an unlabelled endpoint is not a
        # safe one, and defaulting the other way would make the safe path the
        # one that requires configuration.
        effective = Residency.THIRD_COUNTRY if residency is Residency.UNKNOWN else residency

        if not restricted or effective in {Residency.LOCAL, Residency.EU}:
            return EgressDecision(
                allowed=True,
                provider=provider,
                residency=residency,
                data_classes=classes,
                reason=(
                    "no restricted data classes declared"
                    if not restricted
                    else f"provider residency {effective.value} is within scope"
                ),
            )

        override = self._override()
        if override is not None:
            safeguard, approver = override
            return EgressDecision(
                allowed=True,
                provider=provider,
                residency=residency,
                data_classes=classes,
                reason=(
                    f"third-country egress of {', '.join(restricted)} permitted under "
                    f"a recorded safeguard"
                ),
                override_safeguard=safeguard,
                override_approver=approver,
            )

        raise EgressRefused(
            EgressDecision(
                allowed=False,
                provider=provider,
                residency=residency,
                data_classes=classes,
                reason=(
                    f"refused: this system declares {', '.join(restricted)} and provider "
                    f"{provider!r} has residency {effective.value}. To proceed, add an "
                    "`egress_override` to system.yaml carrying a `safeguard` reference "
                    "(adequacy decision, SCCs, or DPA) and an `approver`. The override is "
                    "recorded in the run and surfaces in the audit package — it is an "
                    "auditable decision, not a config flag."
                ),
            )
        )

    def _override(self) -> tuple[str, str] | None:
        """Read `egress_override`, requiring both a safeguard and an approver.

        A half-filled override is not an override. Accepting one with no named
        approver would turn the auditable decision this is meant to be back
        into a config flag.
        """
        raw = self._system.get("egress_override")
        if not isinstance(raw, dict):
            return None
        safeguard = raw.get("safeguard")
        approver = raw.get("approver")
        if isinstance(safeguard, str) and safeguard.strip() and isinstance(approver, str):
            if approver.strip():
                return safeguard.strip(), approver.strip()
        return None


def summarise(decisions: Sequence[EgressDecision]) -> str:
    return "; ".join(f"{d.provider}:{'allow' if d.allowed else 'refuse'}" for d in decisions)
