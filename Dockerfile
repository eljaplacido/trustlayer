# ── Build stage ──────────────────────────────────────────────────────────────
FROM rust:1.84-slim-bookworm AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY core-rs /src/core-rs

# Feature set baked into the binary. Default includes `postgres` so the same
# image works for the JSONL default (no DSN) and Postgres (TRUSTLAYER_DATABASE_URL
# set). Override with `--build-arg FEATURES=server` for a slimmer JSONL-only image.
ARG FEATURES=server,postgres

RUN cd core-rs && \
    cargo build --release --features "${FEATURES}" --bin trustlayer-guardian && \
    cp target/release/trustlayer-guardian /usr/local/bin/

# ── Runtime stage ───────────────────────────────────────────────────────────
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/bin/trustlayer-guardian /usr/local/bin/

ENV TRUSTLAYER_POLICY=/etc/trustlayer/policy.json \
    TRUSTLAYER_BIND=0.0.0.0:8089 \
    TRUSTLAYER_EVENTS_PATH=/data/events.jsonl \
    TRUSTLAYER_VAULT_PATH=/data/vault

EXPOSE 8089

CMD ["trustlayer-guardian"]
