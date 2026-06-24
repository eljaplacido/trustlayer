//! Python native extension via pyo3 (ADR-014).
//!
//! Exposes `trustlayer_native.TrustLayerGuardian` — a Python class backed by
//! the `CynepicGuardian` evaluator. All inputs and outputs are JSON strings so
//! the Python side does `model_dump_json()` / `verdict_json` and the Rust side
//! stays free of Pydantic coupling.
//!
//! Build with [maturin](https://maturin.rs):
//! ```bash
//! cd core-rs
//! maturin develop --features python
//! ```

use pyo3::prelude::*;

use crate::guardian::CynepicGuardian;
use crate::policy::Policy;

/// Python `TrustLayerGuardian` — wraps the Rust `CynepicGuardian`.
///
/// ```python
/// import trustlayer_native
///
/// g = trustlayer_native.TrustLayerGuardian(
///     '{"name": "default", "rules": [...]}'
/// )
/// verdict = g.evaluate('{"trace_id": "...", ...}')
/// assert '"PASS"' in verdict or '"FAIL"' in verdict or '"ESCALATE"' in verdict
/// ```
#[pyo3::pyclass(name = "TrustLayerGuardian")]
pub struct PyGuardian {
    inner: CynepicGuardian,
}

#[pyo3::pymethods]
impl PyGuardian {
    /// Build a guardian from a policy JSON string.
    ///
    /// Raises `ValueError` if the JSON does not parse as a valid
    /// `Policy` document.
    #[new]
    fn new(policy_json: &str) -> PyResult<Self> {
        let policy: Policy = serde_json::from_str(policy_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("invalid policy JSON: {e}"))
        })?;
        Ok(Self {
            inner: CynepicGuardian::new(policy),
        })
    }

    /// Evaluate an `AgentTraceEvent` JSON and return the verdict as
    /// a JSON string.
    ///
    /// The verdict shape matches `docs/SCHEMA.md`:
    /// ```json
    /// {"decision": "PASS", "rule": null, "reason": null, "policy": "default"}
    /// ```
    fn evaluate(&self, event_json: &str) -> PyResult<String> {
        let event: crate::schema::AgentTraceEvent =
            serde_json::from_str(event_json).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "invalid AgentTraceEvent JSON: {e}"
                ))
            })?;
        let verdict = self.inner.evaluate(&event);
        let json = serde_json::to_string(&verdict).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("verdict serialisation: {e}"))
        })?;
        Ok(json)
    }

    /// Atomically replace the active policy at runtime (hot-reload).
    ///
    /// The new policy takes effect on the next `evaluate()` call and
    /// is visible to all Python threads. Parse failures raise
    /// `ValueError` and leave the live policy untouched.
    fn replace_policy(&mut self, policy_json: &str) -> PyResult<()> {
        let policy: Policy = serde_json::from_str(policy_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("invalid policy JSON: {e}"))
        })?;
        self.inner.replace_policy(policy);
        Ok(())
    }

    /// Return the active policy as a JSON string.
    fn policy(&self) -> PyResult<String> {
        let p = self.inner.policy();
        let json = serde_json::to_string(&p.as_ref()).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("policy serialisation: {e}"))
        })?;
        Ok(json)
    }
}

/// Register the `trustlayer_native` Python module.
#[pyo3::pymodule]
fn trustlayer_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyGuardian>()?;
    Ok(())
}
