"""Provider registry and configuration (ADR-020 §2).

`NullProvider` is the default. An unconfigured install therefore produces
deterministic results only and never makes an unexpected network call —
opting in to a model is a deliberate act.
"""

from __future__ import annotations

import logging
import os

from ..models import Residency
from . import agentcenter as agentcenter_defaults
from . import ollama as ollama_defaults
from .agentcenter import AgentcenterProvider
from .anthropic import AnthropicProvider
from .base import (
    ChatProvider,
    HTTPProvider,
    ProviderError,
    ProviderRefusal,
    merge_system,
    schema_instruction,
)
from .null import NullProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatibleProvider

log = logging.getLogger("trustlayer_eval.providers")

PROVIDER_ENV_VAR = "TRUSTLAYER_EVAL_PROVIDER"
MODEL_ENV_VAR = "TRUSTLAYER_EVAL_MODEL"
BASE_URL_ENV_VAR = "TRUSTLAYER_EVAL_BASE_URL"
RESIDENCY_ENV_VAR = "TRUSTLAYER_EVAL_RESIDENCY"
TIMEOUT_ENV_VAR = "TRUSTLAYER_EVAL_TIMEOUT"

#: Generous, because the realistic failure is a cold model load on a busy GPU
#: rather than a wedged connection — and a timeout that fires mid-generation is
#: indistinguishable from a refusal in the run record.
DEFAULT_TIMEOUT = 300.0

__all__ = [
    "AgentcenterProvider",
    "AnthropicProvider",
    "ChatProvider",
    "HTTPProvider",
    "NullProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "ProviderRefusal",
    "from_env",
    "merge_system",
    "schema_instruction",
]


def from_env() -> ChatProvider:
    """Build the configured provider, defaulting to `NullProvider`.

    `agentcenter` falls back to a direct Ollama provider when the gateway is
    unreachable. That is deliberate and narrow: both are local runtimes on this
    machine, so the fallback cannot change the residency of the run or move data
    anywhere it was not already going. No other provider falls back to anything
    — silently substituting a *different* backend would make the run record's
    `provider` field a lie.
    """
    name = os.environ.get(PROVIDER_ENV_VAR, "null").strip().lower()
    model = os.environ.get(MODEL_ENV_VAR) or None
    base_url = os.environ.get(BASE_URL_ENV_VAR) or None
    timeout = _timeout_from_env()

    if name in {"", "null", "none", "off"}:
        return NullProvider()

    if name == "ollama":
        return OllamaProvider(
            base_url=base_url or ollama_defaults.DEFAULT_BASE_URL,
            model=model or ollama_defaults.DEFAULT_MODEL,
            timeout=timeout,
        )

    if name == "agentcenter":
        gateway = AgentcenterProvider(
            base_url=base_url or agentcenter_defaults.DEFAULT_BASE_URL,
            model=model or agentcenter_defaults.DEFAULT_MODEL,
            timeout=timeout,
        )
        if gateway.available():
            return gateway
        log.warning(
            "agentcenter gateway is unreachable; falling back to Ollama directly. "
            "Runs will not be recorded in agentcenter's KPI store."
        )
        gateway.close()
        # The two backends do not share a model-id namespace — agentcenter's are
        # runtime-qualified (`ollama:<tag>`). Strip the prefix on the way down so
        # the fallback asks Ollama for a tag it recognises rather than failing
        # with an id that was only ever valid for the gateway.
        return OllamaProvider(
            model=_as_ollama_tag(model) or ollama_defaults.DEFAULT_MODEL, timeout=timeout
        )

    if name in {"openai_compat", "openai-compatible", "vllm", "lmstudio"}:
        if not base_url:
            raise ProviderError(f"{PROVIDER_ENV_VAR}={name} requires {BASE_URL_ENV_VAR} to be set")
        return OpenAICompatibleProvider(
            base_url=base_url,
            model=model or "local-model",
            timeout=timeout,
            residency=_residency_from_env(),
            api_key=os.environ.get("TRUSTLAYER_EVAL_API_KEY"),
        )

    if name == "anthropic":
        return AnthropicProvider(model=model or "claude-opus-5", timeout=timeout)

    raise ProviderError(
        f"unknown provider {name!r}. Valid: null, ollama, agentcenter, openai_compat, anthropic"
    )


def _timeout_from_env() -> float:
    raw = os.environ.get(TIMEOUT_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        log.warning("unrecognised %s=%r; using %.0fs", TIMEOUT_ENV_VAR, raw, DEFAULT_TIMEOUT)
        return DEFAULT_TIMEOUT
    if value <= 0:
        log.warning("%s must be positive; using %.0fs", TIMEOUT_ENV_VAR, DEFAULT_TIMEOUT)
        return DEFAULT_TIMEOUT
    return value


def _as_ollama_tag(model: str | None) -> str | None:
    """Strip agentcenter's `<runtime>:` prefix, leaving a bare Ollama tag.

    Only the `ollama:` prefix is stripped. A `vllm:` id names a model Ollama
    does not serve at all, so passing it through unchanged lets the fallback
    fail loudly rather than silently answering with the wrong model.
    """
    if model is None:
        return None
    prefix = "ollama:"
    return model[len(prefix) :] if model.startswith(prefix) else model


def _residency_from_env() -> Residency:
    """Residency is declared, never inferred.

    An OpenAI-compatible URL says nothing about where inference happens — the
    same protocol serves a vLLM process on this machine and a model in another
    jurisdiction. Unset means UNKNOWN, which the egress policy treats as
    THIRD_COUNTRY.
    """
    raw = os.environ.get(RESIDENCY_ENV_VAR, "").strip().lower()
    try:
        return Residency(raw) if raw else Residency.UNKNOWN
    except ValueError:
        log.warning("unrecognised %s=%r; treating as UNKNOWN", RESIDENCY_ENV_VAR, raw)
        return Residency.UNKNOWN
