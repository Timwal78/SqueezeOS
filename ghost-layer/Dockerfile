FROM golang:1.22-alpine AS builder
WORKDIR /app

RUN apk add --no-cache git ca-certificates

COPY . .
RUN go mod tidy && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o bridge ./cmd/bridge/main.go

FROM alpine:latest
RUN apk --no-cache add ca-certificates && \
    addgroup -S ghost && adduser -S ghost -G ghost

WORKDIR /app
COPY --from=builder /app/bridge .
COPY --from=builder /app/public ./public

USER ghost
EXPOSE 8080
CMD ["./bridge"]
