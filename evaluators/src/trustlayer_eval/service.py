"""HTTP surface for the dashboard's Advisor pane.

Kept deliberately small: it assembles an evidence window from the trace store,
runs one evaluator role over it, and returns the run record. All the judgement
lives in the package; this module only marshals.

The dashboard is a static bundle in the browser, so it cannot hold an API key
or reach a provider directly — this service is the only place a model endpoint
is configured, which is also what keeps the egress policy enforceable.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from . import runs, telemetry
from .egress import EgressRefused
from .evidence import window_from_events
from .models import EvaluatorRole
from .providers import from_env
from .providers.base import ProviderError, ProviderRefusal
from .redaction import Redactor
from .roles import for_role

log = logging.getLogger("trustlayer_eval.service")

TRACE_STORE_ENV = "TRUSTLAYER_BASE_URL"
TOKEN_ENV = "TRUSTLAYER_API_TOKEN"
DEFAULT_EVENT_LIMIT = 200


class AdvisorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=8000)
    role: EvaluatorRole = EvaluatorRole.INSIGHT_ADVISOR
    agent_id: str | None = None
    session_id: str | None = None
    event_type: str | None = None
    limit: int = Field(default=DEFAULT_EVENT_LIMIT, ge=1, le=2000)
    include_raw_content: bool = False


class AdvisorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: dict[str, Any]
    provider: str
    model: str
    residency: str
    fell_back: bool = False


def _store_base() -> str:
    return os.environ.get(TRACE_STORE_ENV, "http://127.0.0.1:8089").rstrip("/")


def _store_headers() -> dict[str, str]:
    token = os.environ.get(TOKEN_ENV)
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_events(request: AdvisorRequest, *, client: httpx.Client) -> list[dict[str, Any]]:
    params: dict[str, str] = {"limit": str(request.limit)}
    if request.agent_id:
        params["agent_id"] = request.agent_id
    if request.session_id:
        params["session_id"] = request.session_id
    if request.event_type:
        params["event_type"] = request.event_type
    response = client.get(
        f"{_store_base()}/v1/events", params=params, headers=_store_headers(), timeout=30
    )
    response.raise_for_status()
    payload = response.json()
    return (
        [entry for entry in payload if isinstance(entry, dict)] if isinstance(payload, list) else []
    )


def run_advisor(
    request: AdvisorRequest,
    *,
    client: httpx.Client | None = None,
    repo_root: Path | None = None,
    system: dict[str, Any] | None = None,
) -> AdvisorResponse:
    owns_client = client is None
    http = client or httpx.Client()
    try:
        events = fetch_events(request, client=http)
    finally:
        if owns_client:
            http.close()

    redactor = Redactor(include_raw_content=request.include_raw_content)
    projected = redactor.redact_all(events)
    query = (
        f"agent_id={request.agent_id or '*'} session_id={request.session_id or '*'} "
        f"event_type={request.event_type or '*'} limit={request.limit}"
    )
    window = window_from_events(projected, query=query)

    provider = from_env()
    evaluator = for_role(request.role)(
        provider,
        window=window,
        repo_root=repo_root,
        system=system,
        redactions=redactor.summary(),
    )
    run = evaluator.run(request.question)
    runs.append(run)

    return AdvisorResponse(
        run=run.model_dump(mode="json"),
        provider=provider.name,
        model=run.model,
        residency=provider.residency.value,
        fell_back=provider.name == "ollama"
        and os.environ.get("TRUSTLAYER_EVAL_PROVIDER", "").lower() == "agentcenter",
    )


def create_app() -> Any:
    """Build the FastAPI app. Imported lazily so the package stays usable
    (and testable) without a web server installed."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="TrustLayer evaluators", version="0.1.0")

    # The dashboard is served from a different origin (Vite dev server, or the
    # nginx container on :5173) and talks to this service directly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        provider = from_env()
        return {
            "status": "ok",
            "provider": provider.name,
            "model": provider.model,
            "residency": provider.residency.value,
            "available": provider.available(),
            "guardian_enabled": telemetry.enabled(),
            # Where run records land. Reported because it is configurable and
            # because an audit trail nobody can locate is not one.
            "runs_dir": str(runs.runs_dir()),
        }

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        """Model ids the configured provider can actually serve."""
        provider = from_env()
        listed: tuple[str, ...] = ()
        if hasattr(provider, "installed_models"):
            listed = provider.installed_models()
        elif hasattr(provider, "registered_models"):
            listed = provider.registered_models()
        return {"provider": provider.name, "current": provider.model, "models": list(listed)}

    @app.post("/v1/advisor/chat", response_model=AdvisorResponse)
    def advisor_chat(request: AdvisorRequest) -> AdvisorResponse:
        try:
            return run_advisor(request)
        except EgressRefused as exc:
            # 451: the request was understood and refused on legal/policy
            # grounds, which is exactly what an egress refusal is.
            raise HTTPException(status_code=451, detail=exc.decision.reason) from exc
        except telemetry.PolicyRefusal as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ProviderRefusal as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"trace store unreachable: {exc}") from exc

    return app


def _allowed_origins() -> list[str]:
    raw = os.environ.get("TRUSTLAYER_EVAL_CORS_ORIGINS")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


def main() -> None:
    import uvicorn

    uvicorn.run(
        create_app(),
        host=os.environ.get("TRUSTLAYER_EVAL_HOST", "127.0.0.1"),
        port=int(os.environ.get("TRUSTLAYER_EVAL_PORT", "8091")),
    )


if __name__ == "__main__":
    main()
