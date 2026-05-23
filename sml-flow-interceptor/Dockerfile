FROM golang:1.22-alpine AS builder
WORKDIR /app

RUN apk add --no-cache git ca-certificates

COPY go.mod go.sum* ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-w -s" -o interceptor ./cmd/interceptor

FROM alpine:latest
RUN apk --no-cache add ca-certificates tzdata && \
    addgroup -S sml && adduser -S sml -G sml && \
    mkdir -p /var/data && chown -R sml:sml /var/data

WORKDIR /app
COPY --from=builder /app/interceptor /app/interceptor

USER sml
ENV EVENT_LOG_PATH=/var/data/events.ndjson
ENTRYPOINT ["/app/interceptor"]
