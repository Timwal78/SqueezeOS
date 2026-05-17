FROM golang:1.22-alpine AS builder
WORKDIR /app

RUN apk add --no-cache git ca-certificates

COPY . .
RUN go mod tidy && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o proof402-server ./cmd/server/main.go

FROM alpine:latest
RUN apk --no-cache add ca-certificates && \
    addgroup -S proof402 && adduser -S proof402 -G proof402

WORKDIR /app
COPY --from=builder /app/proof402-server .
COPY --from=builder /app/public ./public

USER proof402
EXPOSE 9090
CMD ["./proof402-server"]
