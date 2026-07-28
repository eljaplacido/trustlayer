#!/usr/bin/env bash
# Canonical local verification gate. Run from any directory in this repository.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
MODE="${1:-all}"

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
    (cd "$ROOT" && MYPYPATH=. mypy -p compliance.src)
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
  )
}

run_security() {
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
