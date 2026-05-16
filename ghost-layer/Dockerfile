FROM golang:1.22-alpine AS builder
WORKDIR /app

# Install git (needed for go mod to fetch from GitHub)
RUN apk add --no-cache git ca-certificates

COPY . .
RUN go mod tidy && \
    CGO_ENABLED=0 GOOS=linux go build -o bridge ./cmd/bridge/main.go

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/
COPY --from=builder /app/bridge .
COPY --from=builder /app/public ./public
EXPOSE 8080
CMD ["./bridge"]
