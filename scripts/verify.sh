#!/usr/bin/env bash
# Canonical local verification gate. Run from any directory in this repository.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
MODE="${1:-all}"

# The audit tools are installed by CI but are not part of any language
# toolchain, so a fresh clone does not have them. Without this, the security
# gate fails with a bare `No module named pip_audit` and no indication that the
# fix is one pip install away.
#
# It still fails. A missing auditor is not a passing audit — that is precisely
# the "gate switched off without failing" shape this repository keeps finding.
require_tool() {
  local probe="$1" name="$2" install="$3"
  if ! eval "$probe" >/dev/null 2>&1; then
    printf '\n%s is required by `verify.sh security` and is not installed.\n' "$name" >&2
    printf 'Install it with:\n    %s\n\n' "$install" >&2
    exit 1
  fi
}

run_tests() {
  (
    cd "$ROOT/sdks/python"
    ruff format --check .
    ruff check src/ tests/
    mypy src/trustlayer
    pytest --tb=short -q
  )
  (
    cd "$ROOT/skills/hermes"
    ruff format --check .
    ruff check . --config pyproject.toml
    mypy --config-file pyproject.toml
    pytest --tb=short -q
  )
  (
    cd "$ROOT/mcp-server"
    ruff format --check .
    ruff check src/ tests/
    mypy src/trustlayer_mcp
    PYTHONPATH=src:../sdks/python/src:../skills python3 -m pytest --tb=short -q
  )
  (
    cd "$ROOT/compliance"
    ruff format --check src/ tests/
    ruff check src/ tests/
    # Run from the repo root so `compliance.src` resolves, but point mypy at
    # this package's config explicitly — otherwise it looks for one next to the
    # working directory, finds none, and silently runs with defaults, which
    # would leave the Phase 8 typing gate switched off without failing.
    (cd "$ROOT" && MYPYPATH=. mypy --config-file compliance/pyproject.toml -p compliance.src)
    python3 -m pytest --tb=short -q
  )
  (
    cd "$ROOT/sdks/typescript"
    npm run typecheck
    npm test -- --reporter=dot
  )
  (
    cd "$ROOT/dashboard"
    npm run typecheck
    npm test -- --reporter=dot
    npm run build
  )
  (
    cd "$ROOT/sdks/go"
    go vet ./...
    go test ./... -count=1 -race
  )
  (
    cd "$ROOT/core-rs"
    cargo fmt --all -- --check
    cargo clippy --features server --all-targets -- -D warnings
    cargo test --features server
    # `python` (pyo3, ADR-014) and `postgres` (ADR-015) are shipped code paths
    # nothing else compiles. `check` needs neither a Python toolchain nor a
    # database, so it runs everywhere the rest of this gate does.
    cargo check --features python
    cargo check --features server,postgres
    cargo clippy --features server,postgres --all-targets -- -D warnings
  )
}

run_security() {
  require_tool "cargo audit --version" "cargo-audit" "cargo install cargo-audit"
  require_tool "python3 -m pip_audit --version" "pip-audit" "python3 -m pip install pip-audit"
  (
    cd "$ROOT"
    git grep -nEI '(AKIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----|ghp_[A-Za-z0-9]{36})' -- . ':!docs/**' ':!CHANGELOG.md' && exit 1 || true
  )
  (
    cd "$ROOT/core-rs"
    cargo audit
  )
  (
    cd "$ROOT/sdks/typescript"
    npm audit --omit=dev --audit-level=high
  )
  (
    cd "$ROOT/dashboard"
    npm audit --omit=dev --audit-level=high
  )
  (
    cd "$ROOT"
    python3 -m pip_audit -r sdks/python/requirements-release.txt
    python3 -m pip_audit -r mcp-server/requirements-release.txt
    python3 -m pip_audit -r compliance/requirements-release.txt
  )
}

case "$MODE" in
  all) run_tests; run_security ;;
  test) run_tests ;;
  security) run_security ;;
  compliance)
    (cd "$ROOT/compliance" && python3 -m pytest --tb=short -q)
    ;;
  *)
    printf 'Usage: %s [all|test|security|compliance]\n' "$0" >&2
    exit 64
    ;;
esac
