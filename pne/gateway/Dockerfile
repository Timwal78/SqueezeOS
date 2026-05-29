FROM rust:1.78-slim AS builder

WORKDIR /app

# Cache dependencies separately so rebuilds are fast
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && \
    cargo build --release && \
    rm -rf src

# Build actual source
COPY src ./src
# Touch main.rs so cargo knows to recompile
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends libssl3 ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/pne-gateway /usr/local/bin/pne-gateway
EXPOSE 8402
ENTRYPOINT ["/usr/local/bin/pne-gateway"]
