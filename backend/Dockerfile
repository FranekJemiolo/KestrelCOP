# -----------------------------------------------------------------------------
# KestrelCOP Go Collector Backend Dockerfile
# Multi-stage minimal scratch/alpine build
# -----------------------------------------------------------------------------

FROM golang:1.24-alpine AS builder

RUN apk add --no-cache git ca-certificates tzdata

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Compile static binary without CGO
RUN CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -ldflags="-w -s" -o /collector ./cmd/collector

# -----------------------------------------------------------------------------
# Minimal Production Runtime
# -----------------------------------------------------------------------------
FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata && \
    addgroup -g 10001 kestrel && \
    adduser -u 10001 -G kestrel -D kestrel

WORKDIR /app
COPY --from=builder /collector /app/collector

USER kestrel

EXPOSE 8080 9090

ENTRYPOINT ["/app/collector"]
