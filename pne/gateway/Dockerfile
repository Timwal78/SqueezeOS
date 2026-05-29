FROM rust:1.78-slim AS builder

WORKDIR /app
COPY Cargo.toml ./
COPY src ./src

RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y libssl3 ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/pne-gateway /usr/local/bin/pne-gateway
EXPOSE 8402
ENTRYPOINT ["/usr/local/bin/pne-gateway"]
