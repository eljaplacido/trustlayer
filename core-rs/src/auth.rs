//! Bearer-token authentication middleware (ADR-007).
//!
//! The sidecar's "open by default, gated when configured" auth story lives
//! entirely in this module. If [`AppState::api_token`] is `None`, the
//! middleware is a no-op — preserving the local-dev UX. When the operator
//! sets `TRUSTLAYER_API_TOKEN`, every authenticated route demands
//! `Authorization: Bearer <token>` and uses a constant-time compare to
//! avoid timing-oracle attacks.
//!
//! `/healthz` is wired *outside* the middleware in [`crate::server`] so
//! liveness probes and load balancers can call it without a secret.

use axum::body::Body;
use axum::extract::State;
use axum::http::header::{AUTHORIZATION, WWW_AUTHENTICATE};
use axum::http::{Request, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use subtle::ConstantTimeEq;

use crate::server::AppState;

/// Axum middleware that gates requests on a shared bearer token.
///
/// - Token unset on the server: pass through (no-op).
/// - Token set + matching `Authorization: Bearer ...` header: pass through.
/// - Token set + missing/wrong header: `401 Unauthorized` with
///   `WWW-Authenticate: Bearer realm="trustlayer"`.
pub async fn require_token(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    let Some(expected) = state.api_token.as_deref() else {
        return next.run(request).await;
    };

    let provided = request
        .headers()
        .get(AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "));

    let ok = match provided {
        Some(p) => bool::from(p.as_bytes().ct_eq(expected.as_bytes())),
        None => false,
    };

    if ok {
        next.run(request).await
    } else {
        (
            StatusCode::UNAUTHORIZED,
            [(WWW_AUTHENTICATE, "Bearer realm=\"trustlayer\"")],
        )
            .into_response()
    }
}
